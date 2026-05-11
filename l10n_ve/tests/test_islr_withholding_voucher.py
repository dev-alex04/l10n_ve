# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para el controlador ISLRWithholdingVoucher.

Valida la lógica de negocio del comprobante de retención de ISLR:
- Unicidad del número de comprobante
- Validación de monto retenido > 0
- Bloqueo de cancelación con emisión fiscal activa
- Restricción de eliminación por periodo
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, getdate, add_months
from unittest.mock import patch, MagicMock

from l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher import (
    ISLRWithholdingVoucher,
)


def _get_islr_voucher_instance(**overrides) -> ISLRWithholdingVoucher:
    """Crea una instancia mock de ISLRWithholdingVoucher sin tocar la BD."""
    doc = ISLRWithholdingVoucher.__new__(ISLRWithholdingVoucher)
    doc.name = "COMP-RET-ISLR-2026-00001"
    doc.voucher_number = "20260400000001"
    doc.digital_invoice_status = ""
    doc.totals_islr_amount = 100.0
    doc.posting_date = nowdate()
    doc.docstatus = 1
    doc.empresa = "Galanet Solution C.A."
    doc.supplier = "DESIGNET SERVICES 1815 C.A"
    doc.flags = frappe._dict()
    doc.meta = MagicMock()

    for key, value in overrides.items():
        setattr(doc, key, value)

    return doc


class TestISLRWithholdingVoucher(FrappeTestCase):
    """Tests para ISLRWithholdingVoucher: validaciones y hooks del controlador."""

    # ─────────────────────────────────────────────
    # validate_unique_voucher_number()
    # ─────────────────────────────────────────────

    def test_voucher_number_empty_skips_validation(self) -> None:
        """Sin voucher_number → la validación no ejecuta query."""
        doc = _get_islr_voucher_instance(voucher_number="")

        # No debería lanzar error
        doc.validate_unique_voucher_number()

    @patch("frappe.db.get_value")
    def test_voucher_number_duplicate_raises_error(self, mock_get_value: MagicMock) -> None:
        """Con voucher_number duplicado en otro doc activo → frappe.throw."""
        mock_get_value.return_value = "COMP-RET-ISLR-2026-00099"
        doc = _get_islr_voucher_instance()

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_unique_voucher_number()

    @patch("frappe.db.get_value")
    def test_voucher_number_no_duplicate_passes(self, mock_get_value: MagicMock) -> None:
        """Sin duplicado → la validación pasa sin error."""
        mock_get_value.return_value = None
        doc = _get_islr_voucher_instance()

        # No debería lanzar error
        doc.validate_unique_voucher_number()

    # ─────────────────────────────────────────────
    # validate_withholding_amount()
    # ─────────────────────────────────────────────

    def test_zero_islr_amount_raises_error(self) -> None:
        """totals_islr_amount = 0 → frappe.throw."""
        doc = _get_islr_voucher_instance(totals_islr_amount=0)

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_withholding_amount()

    def test_positive_islr_amount_passes(self) -> None:
        """totals_islr_amount > 0 → la validación pasa."""
        doc = _get_islr_voucher_instance(totals_islr_amount=9723.92)

        # No debería lanzar error
        doc.validate_withholding_amount()

    # ─────────────────────────────────────────────
    # before_cancel()
    # ─────────────────────────────────────────────

    def test_before_cancel_blocks_when_sent(self) -> None:
        """digital_invoice_status='Sent' → bloquea cancelación."""
        doc = _get_islr_voucher_instance(digital_invoice_status="Sent")

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.before_cancel()

    def test_before_cancel_allows_with_hka_void_flag(self) -> None:
        """digital_invoice_status='Sent' + hka_void_confirmed flag → permite."""
        doc = _get_islr_voucher_instance(digital_invoice_status="Sent")
        frappe.flags.hka_void_confirmed = True

        try:
            doc.before_cancel()  # No debería lanzar
        finally:
            frappe.flags.pop("hka_void_confirmed", None)

    def test_before_cancel_allows_when_not_sent(self) -> None:
        """digital_invoice_status vacío o 'Error' → permite cancelación."""
        for status in ["", "Error", "Pending"]:
            doc = _get_islr_voucher_instance(digital_invoice_status=status)
            doc.before_cancel()  # No debería lanzar

    # ─────────────────────────────────────────────
    # on_trash()
    # ─────────────────────────────────────────────

    def test_on_trash_allows_current_month(self) -> None:
        """posting_date en mes actual → permite eliminar."""
        doc = _get_islr_voucher_instance(posting_date=nowdate())

        # No debería lanzar error
        doc.on_trash()

    def test_on_trash_blocks_previous_month(self) -> None:
        """posting_date en mes anterior → frappe.throw."""
        previous_month: str = add_months(nowdate(), -1)
        doc = _get_islr_voucher_instance(posting_date=previous_month)

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.on_trash()
