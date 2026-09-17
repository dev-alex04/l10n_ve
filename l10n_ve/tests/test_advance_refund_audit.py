# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Detección de reembolsos que quedaron sin enlazar con el cobro que devolvieron.

Lo que se prueba sin tocar la base es la clasificación: cuándo un descuadre se puede corregir
solo, cuándo hay que revisarlo a mano y por qué. Contra el sitio se prueba que el diagnóstico
corra y que solo informe la dirección que importa (los cobros ofreciendo de más).
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt

from l10n_ve.overrides.advance_refund_audit import (
    _allocation_to_undo,
    _build_case,
    _close_refund_receipt,
    _not_a_refund,
    scan,
)


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


class TestElReciboDelReembolso(unittest.TestCase):
    """Que el recibo del reembolso deje de mostrar su monto como saldo a favor.

    Aurelys lo reportó el 16-sep-2026, con ZAPATERIA GASOLINA EXTRA ya corregido: «el cliente
    está saldado pero el recibo sigue saliendo con el monto». La contabilidad estaba bien; lo
    que no se enteraba era el documento.
    """

    def _cerrar(self, refund: dict, receipt: dict, ya_enlazado: bool = False):
        """Corre el cierre con la base simulada y devuelve (fila escrita, campos del recibo)."""
        fila = MagicMock()
        with (
            patch.object(frappe.db, "get_value", return_value=frappe._dict(receipt)),
            patch.object(frappe.db, "exists", return_value=ya_enlazado),
            patch.object(frappe.db, "count", return_value=0),
            patch.object(frappe, "new_doc", return_value=fila),
            patch.object(frappe.db, "set_value") as set_value,
        ):
            _close_refund_receipt(refund, "ACC-JV-2026-35430", 232565.54)
        escrita = fila.update.call_args[0][0] if fila.update.call_args else None
        campos = set_value.call_args[0][2] if set_value.call_args else None
        return escrita, campos

    def test_el_recibo_queda_enlazado_y_sin_monto_a_favor(self):
        escrita, campos = self._cerrar(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 232565.54,
                "total_allocated_amount": 0.0,
                "base_total_allocated_amount": 0.0,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertEqual(escrita["reference_doctype"], "Journal Entry")
        self.assertEqual(escrita["reference_name"], "ACC-JV-2026-35430")
        self.assertEqual(escrita["allocated_amount"], 232565.54)
        self.assertEqual(campos["unallocated_amount"], 0.0)
        self.assertEqual(campos["total_allocated_amount"], 232565.54)

    def test_nunca_asigna_mas_de_lo_que_quedaba_sin_asignar(self):
        """Si el recibo ya tenía parte aplicada, solo se cierra lo que quedaba libre."""
        escrita, campos = self._cerrar(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 100.0,
                "total_allocated_amount": 50.0,
                "base_total_allocated_amount": 50.0,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertEqual(escrita["allocated_amount"], 100.0)
        self.assertEqual(campos["total_allocated_amount"], 150.0)
        self.assertEqual(campos["unallocated_amount"], 0.0)

    def test_el_reembolso_asentado_en_diario_no_tiene_recibo_que_cerrar(self):
        with patch.object(frappe.db, "get_value") as consulta:
            _close_refund_receipt(
                {"doctype": "Journal Entry", "name": "ACC-JV-2026-30001"},
                "ACC-JV-2026-35430",
                100.0,
            )
        consulta.assert_not_called()

    def test_si_ya_estaba_enlazado_no_lo_escribe_dos_veces(self):
        """El script se puede volver a correr sin duplicar la fila."""
        escrita, campos = self._cerrar(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 232565.54,
                "total_allocated_amount": 0.0,
                "base_total_allocated_amount": 0.0,
                "target_exchange_rate": 1.0,
            },
            ya_enlazado=True,
        )
        self.assertIsNone(escrita)
        self.assertIsNone(campos)

    def test_un_recibo_sin_nada_libre_se_deja_como_esta(self):
        escrita, campos = self._cerrar(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 0.0,
                "total_allocated_amount": 232565.54,
                "base_total_allocated_amount": 232565.54,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertIsNone(escrita)
        self.assertIsNone(campos)


class TestElEmpateEntreAplicaciones(unittest.TestCase):
    """Cuando dos aplicaciones encajan igual de bien, no se elige al azar.

    Quedarse con la primera es elegir a suertes de qué factura se saca la deuda, y nada lo
    atraparía: `_verify` compara el agregado del cliente contra el mayor, no la factura que se
    tocó. Elegir mal deja la factura buena mostrando deuda y la que sí se pagó con la plata
    devuelta marcada «Pagada»: el mismo problema que esto viene a resolver.
    """

    def _aplicacion(self, factura: str, monto: float, cobro: str = "ACC-PAY-1") -> dict:
        return frappe._dict(payment_entry=cobro, sales_invoice=factura, amount=monto)

    def _elegir(self, aplicaciones: list, falta: float = 100.0) -> tuple:
        caso = frappe._dict(difference=falta, offered=0.0, tied_invoices=None)
        with patch(
            "l10n_ve.overrides.advance_refund_audit._applications_after_refund",
            return_value=aplicaciones,
        ):
            return _allocation_to_undo(caso), caso

    def test_dos_aplicaciones_exactas_en_facturas_distintas_van_a_revision(self):
        elegido, caso = self._elegir(
            [
                self._aplicacion("ACC-SINV-A", 100.0),
                self._aplicacion("ACC-SINV-B", 100.0),
            ]
        )
        self.assertIsNone(elegido)
        self.assertEqual(caso.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_el_empate_dentro_de_la_misma_factura_no_es_ambiguo(self):
        """Da igual cuál se deshaga: el resultado en esa factura es el mismo."""
        elegido, caso = self._elegir(
            [
                self._aplicacion("ACC-SINV-A", 100.0, "ACC-PAY-1"),
                self._aplicacion("ACC-SINV-A", 100.0, "ACC-PAY-2"),
            ]
        )
        self.assertEqual(elegido["invoice"], "ACC-SINV-A")
        self.assertIsNone(caso.tied_invoices)

    def test_dos_combinaciones_sobre_facturas_distintas_van_a_revision(self):
        elegido, caso = self._elegir(
            [
                self._aplicacion("ACC-SINV-A", 60.0),
                self._aplicacion("ACC-SINV-A", 40.0),
                self._aplicacion("ACC-SINV-B", 70.0),
                self._aplicacion("ACC-SINV-B", 30.0),
            ]
        )
        self.assertIsNone(elegido)
        self.assertEqual(caso.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_el_empate_en_la_aplicacion_mas_grande_tambien_va_a_revision(self):
        elegido, caso = self._elegir(
            [
                self._aplicacion("ACC-SINV-A", 150.0),
                self._aplicacion("ACC-SINV-B", 150.0),
            ]
        )
        self.assertIsNone(elegido)
        self.assertEqual(caso.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_sin_empate_se_sigue_eligiendo_como_antes(self):
        """Lo que ya se corregía no cambia: los 19 casos de Galanet no tienen empates."""
        elegido, caso = self._elegir(
            [
                self._aplicacion("ACC-SINV-A", 150.0),
                self._aplicacion("ACC-SINV-B", 260.0),
            ]
        )
        self.assertEqual(elegido["invoice"], "ACC-SINV-A")
        self.assertEqual(flt(elegido["undone"], 2), 150.0)
        self.assertEqual(flt(elegido["surplus"], 2), 50.0)
        self.assertIsNone(caso.tied_invoices)

    def test_el_caso_ambiguo_dice_por_que_hay_que_mirarlo(self):
        """El motivo no puede ser «no hay ninguna que alcance»: hay dos, y ese es el problema."""
        with (
            patch(
                "l10n_ve.overrides.advance_refund_audit._refunds",
                return_value=[
                    frappe._dict(name="ACC-PAY-1", amount=100.0, problem=None)
                ],
            ),
            patch(
                "l10n_ve.overrides.advance_refund_audit._applications_after_refund",
                return_value=[
                    self._aplicacion("ACC-SINV-A", 60.0),
                    self._aplicacion("ACC-SINV-B", 60.0),
                ],
            ),
        ):
            caso = _build_case(
                ("Empresa", "CLIENTE", "2104001 - Anticipo"), 40.0, -60.0
            )
        self.assertIsNone(caso.undo)
        self.assertIn("facturas distintas", caso.problem)
        self.assertIn("ACC-SINV-A", caso.problem)
        self.assertIn("ACC-SINV-B", caso.problem)
