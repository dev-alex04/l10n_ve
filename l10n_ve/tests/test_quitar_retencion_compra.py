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
_SQL = "frappe.db.sql"


class TestGuardaComprobanteVivo(FrappeTestCase):

    def test_corta_si_el_comprobante_sigue_vivo(self) -> None:
        vivo = [{"voucher": "COMP-RET-IVA-2026-00380", "docstatus": 1}]
        with patch(_SQL, return_value=vivo), self.assertRaises(frappe.ValidationError) as ctx:
            _validate_no_live_withholding_voucher(_FACTURA, "VAT")

        self.assertIn("COMP-RET-IVA-2026-00380", str(ctx.exception))

    def test_pasa_si_no_queda_ningun_comprobante_vivo(self) -> None:
        """Un comprobante cancelado (docstatus 2) no bloquea: la consulta no lo devuelve."""
        with patch(_SQL, return_value=[]):
            _validate_no_live_withholding_voucher(_FACTURA, "ISLR")

    def test_cada_retencion_mira_su_propio_comprobante(self) -> None:
        """El IVA no se bloquea por un comprobante de ISLR ni al revés."""
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["VAT"], "VAT Withholding Voucher")
        self.assertEqual(_PURCHASE_WITHHOLDING_VOUCHER["ISLR"], "ISLR Withholding Voucher")

    def test_la_consulta_solo_trae_comprobantes_sin_cancelar(self) -> None:
        """La condición docstatus < 2 vive en el SQL: si se cae, la guarda deja de servir."""
        with patch(_SQL, return_value=[]) as mock_sql:
            _validate_no_live_withholding_voucher(_FACTURA, "ISLR")

        consulta = mock_sql.call_args[0][0]
        self.assertIn("docstatus < 2", consulta)
        self.assertIn("ISLR Withholding Voucher", consulta)


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
