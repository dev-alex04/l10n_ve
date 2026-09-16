# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de «Quitar Retención» en facturas de compra aprobadas.

Lo que se fija acá es la guarda que protege el documento fiscal: mientras un comprobante
de retención siga vivo (docstatus < 2), la retención que respalda no se toca. Si se
vaciara por debajo, el comprobante quedaría declarando ante el SENIAT un monto que la
factura ya no dice.

Caso que originó la función (16-sep-2026, ACC-PINV-2026-00369): el ISLR se cargó con el
concepto equivocado, su comprobante se anuló, y no había forma de corregirlo porque en la
factura aprobada solo existía el camino para AGREGAR retenciones.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides.purchase_invoice import (
    _PURCHASE_WITHHOLDING_VOUCHER,
    _validate_no_live_withholding_voucher,
    remove_retroactive_purchase_withholding,
)

_FACTURA = "ACC-PINV-2026-99999"
_GET_ALL = "frappe.get_all"
_COMPROBANTE = "COMP-RET-IVA-2026-00380"


class TestGuardaComprobanteVivo(FrappeTestCase):
    """La guarda consulta dos veces: los comprobantes que citan la factura, y cuáles siguen vivos."""

    def test_corta_si_el_comprobante_sigue_vivo(self) -> None:
        consultas = [[_COMPROBANTE], [_COMPROBANTE]]
        with patch(_GET_ALL, side_effect=consultas), \
                self.assertRaises(frappe.ValidationError) as ctx:
            _validate_no_live_withholding_voucher(_FACTURA, "VAT")

        self.assertIn(_COMPROBANTE, str(ctx.exception))

    def test_pasa_si_el_comprobante_esta_cancelado(self) -> None:
        """Lo cita un comprobante, pero está cancelado: la segunda consulta vuelve vacía."""
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], []]):
            _validate_no_live_withholding_voucher(_FACTURA, "ISLR")

    def test_pasa_si_ningun_comprobante_la_cita(self) -> None:
        """Sin comprobantes no hay segunda consulta: sale de una."""
        with patch(_GET_ALL, side_effect=[[]]) as mock_get_all:
            _validate_no_live_withholding_voucher(_FACTURA, "ISLR")

        self.assertEqual(mock_get_all.call_count, 1)

    def test_cada_retencion_mira_su_propio_comprobante(self) -> None:
        """El IVA no se bloquea por un comprobante de ISLR ni al revés."""
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["VAT"], "VAT Withholding Voucher")
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["ISLR"], "ISLR Withholding Voucher")

    def test_solo_cuentan_los_comprobantes_sin_cancelar(self) -> None:
        """El filtro docstatus < 2 es la guarda: si se cae, un comprobante vivo pasaría."""
        with patch(_GET_ALL, side_effect=[[_COMPROBANTE], []]) as mock_get_all:
            _validate_no_live_withholding_voucher(_FACTURA, "ISLR")

        doctype = mock_get_all.call_args_list[1][0][0]
        filtros = mock_get_all.call_args_list[1][1]["filters"]
        self.assertEqual(doctype, "ISLR Withholding Voucher")
        self.assertEqual(filtros["docstatus"], ["<", 2])


class TestValidacionesDeEntrada(FrappeTestCase):

    def test_tipo_de_retencion_invalido(self) -> None:
        with self.assertRaises(frappe.ValidationError) as ctx:
            remove_retroactive_purchase_withholding(_FACTURA, "IGTF", "Galanet Solution C.A.")

        self.assertIn("IGTF", str(ctx.exception))

    def test_factura_inexistente_o_no_aprobada(self) -> None:
        with patch("frappe.db.exists", return_value=False), \
                self.assertRaises(frappe.ValidationError) as ctx:
            remove_retroactive_purchase_withholding(_FACTURA, "ISLR", "Galanet Solution C.A.")

        self.assertIn(_FACTURA, str(ctx.exception))
