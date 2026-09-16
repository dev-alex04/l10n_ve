# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Detección de reembolsos que quedaron sin enlazar con el cobro que devolvieron.

Lo que se prueba sin tocar la base es la clasificación: cuándo un descuadre se puede corregir
solo, cuándo hay que revisarlo a mano y por qué. Contra el sitio se prueba que el diagnóstico
corra y que solo informe la dirección que importa (los cobros ofreciendo de más).
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from l10n_ve.overrides.advance_refund_audit import _build_case, _not_a_refund, scan


class TestSiEsUnReembolsoDeVerdad(unittest.TestCase):
    def test_sin_movimiento_del_banco_no_lo_es(self):
        motivo = _not_a_refund("ACC-PAY-1", [])
        self.assertIn("ningún movimiento del banco", motivo)

    def test_contra_un_deposito_tampoco(self):
        motivo = _not_a_refund(
            "ACC-PAY-1", [frappe._dict(name="ACC-BTN-1", deposit=100.0, withdrawal=0.0)]
        )
        self.assertIn("DEPÓSITO", motivo)
        self.assertIn("ACC-BTN-1", motivo)

    def test_con_un_retiro_si_lo_es(self):
        self.assertIsNone(
            _not_a_refund(
                "ACC-PAY-1",
                [frappe._dict(name="ACC-BTN-1", deposit=0.0, withdrawal=100.0)],
            )
        )


class TestLaClasificacionDelCaso(unittest.TestCase):
    """`_build_case` decide si el caso se corrige solo o hay que mirarlo."""

    clave = ("Empresa", "CLIENTE", "2104001 - Anticipo")

    def _caso(self, refunds, ofrecen, mayor, undo=None):
        with (
            patch(
                "l10n_ve.overrides.advance_refund_audit._refunds", return_value=refunds
            ),
            patch(
                "l10n_ve.overrides.advance_refund_audit._allocation_to_undo",
                return_value=undo,
            ),
        ):
            return _build_case(self.clave, ofrecen, mayor)

    def test_sin_reembolso_que_lo_explique_se_revisa(self):
        caso = self._caso([], 100.0, 0.0)
        self.assertIn("No se encontró el reembolso", caso.problem)

    def test_si_el_reembolso_no_explica_la_diferencia_se_revisa(self):
        """Otros movimientos en la cuenta de anticipos: no se toca hasta entender cuáles."""
        caso = self._caso(
            [frappe._dict(name="JV-1", amount=40.0, problem=None)], 100.0, 0.0
        )
        self.assertIn("otros movimientos", caso.problem)

    def test_el_credito_fantasma_se_corrige_solo(self):
        """El saldo devuelto sigue entero en los cobros: basta el asiento de enlace."""
        caso = self._caso(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)], 150.0, 50.0
        )
        self.assertIsNone(caso.problem)
        self.assertIsNone(caso.undo)
        self.assertEqual(flt(caso.difference, 2), 100.0)

    def test_la_deuda_escondida_necesita_deshacer_una_aplicacion(self):
        undo = {
            "applications": [
                {
                    "payment_entry": "ACC-PAY-1",
                    "sales_invoice": "ACC-SINV-1",
                    "amount": 60.0,
                }
            ],
            "invoice": "ACC-SINV-1",
            "undone": 60.0,
            "surplus": 0.0,
        }
        caso = self._caso(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)],
            40.0,
            -60.0,
            undo=undo,
        )
        self.assertIsNone(caso.problem)
        self.assertEqual(caso.undo, undo)

    def test_si_ninguna_aplicacion_alcanza_se_revisa(self):
        caso = self._caso(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)],
            40.0,
            -60.0,
            undo=None,
        )
        self.assertIn("que alcance", caso.problem)

    def test_el_problema_del_reembolso_manda(self):
        """Si el «Pago» está contra un depósito, no se corrige aunque las cuentas cuadren."""
        refund = frappe._dict(
            name="ACC-PAY-1", amount=100.0, problem="está conciliado con un DEPÓSITO"
        )
        caso = self._caso([refund], 150.0, 50.0)
        self.assertIn("DEPÓSITO", caso.problem)


class TestElDiagnosticoContraElSitio(unittest.TestCase):
    def setUp(self):
        self.company = frappe.db.get_value("Company", {}, "name")
        if not self.company:
            self.skipTest("el sitio no tiene empresas")

    def test_devuelve_casos_con_la_forma_esperada(self):
        for caso in scan(company=self.company):
            self.assertEqual(
                set(caso) >= {"party", "offered", "ledger", "difference", "refunds"},
                True,
            )
            self.assertGreater(flt(caso["difference"], 2), 0.0)

    def test_solo_informa_cuando_los_cobros_ofrecen_de_mas(self):
        """Al revés son los ajustes por diferencia en cambio, que no son un reembolso."""
        for caso in scan(company=self.company):
            self.assertGreater(flt(caso["offered"], 2), flt(caso["ledger"], 2))

    def test_la_tolerancia_descarta_los_centimos(self):
        amplio = scan(company=self.company, tolerance=0.01)
        acotado = scan(company=self.company, tolerance=1000.0)
        self.assertLessEqual(len(acotado), len(amplio))
