# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para el controlador VATWithholdingVoucher.

Valida paridad con ISLR en:
- Bloqueo de cancelación con emisión fiscal activa
- Unicidad del número de comprobante
- Validación de periodo fiscal
- Validación de monto retenido
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate, add_months
from unittest.mock import patch, MagicMock

from l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher import (
    VATWithholdingVoucher,
)


def _get_vat_voucher_instance(**overrides) -> VATWithholdingVoucher:
    """Crea una instancia mock de VATWithholdingVoucher sin tocar la BD."""
    doc = VATWithholdingVoucher.__new__(VATWithholdingVoucher)
    doc.name = "COMP-RET-IVA-2026-00001"
    doc.voucher_number = "20260400000001"
    doc.digital_invoice_status = ""
    doc.totals_tax_amount_vat = 150.0
    doc.issue_date = nowdate()
    doc.posting_date = nowdate()
    doc.fiscal_period = "04/2026"
    doc.docstatus = 1
    doc.empresa = "Galanet Solution C.A."
    doc.supplier = "DESIGNET SERVICES 1815 C.A"
    doc.flags = frappe._dict()
    doc.meta = MagicMock()

    # Child table requerido por validate_withholding_amount()
    doc.vat_withholding_voucher_item = [
        frappe._dict({"tax_amount_vat": overrides.get("totals_tax_amount_vat", 150.0)}),
    ]

    for key, value in overrides.items():
        setattr(doc, key, value)

    return doc


class TestVATWithholdingVoucher(FrappeTestCase):
    """Tests para VATWithholdingVoucher: bloqueo HKA, unicidad y fiscal period."""

    # ─────────────────────────────────────────────
    # before_cancel() — paridad con ISLR
    # ─────────────────────────────────────────────

    def test_before_cancel_blocks_when_sent(self) -> None:
        """digital_invoice_status='Sent' → bloquea cancelación."""
        doc = _get_vat_voucher_instance(digital_invoice_status="Sent")

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.before_cancel()

    def test_before_cancel_allows_with_hka_void_flag(self) -> None:
        """digital_invoice_status='Sent' + hka_void_confirmed flag → permite."""
        doc = _get_vat_voucher_instance(digital_invoice_status="Sent")
        frappe.flags.hka_void_confirmed = True

        try:
            doc.before_cancel()
        finally:
            frappe.flags.pop("hka_void_confirmed", None)

    def test_before_cancel_allows_when_not_sent(self) -> None:
        """digital_invoice_status vacío → permite cancelación."""
        doc = _get_vat_voucher_instance(digital_invoice_status="")

        doc.before_cancel()  # No debería lanzar

    # ─────────────────────────────────────────────
    # validate_unique_voucher_number()
    # ─────────────────────────────────────────────

    @patch("frappe.db.get_value")
    def test_voucher_number_duplicate_raises_error(self, mock_get_value: MagicMock) -> None:
        """Con duplicado activo → frappe.throw."""
        mock_get_value.return_value = "COMP-RET-IVA-2026-00099"
        doc = _get_vat_voucher_instance()

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_unique_voucher_number()

    @patch("frappe.db.get_value")
    def test_voucher_number_no_duplicate_passes(self, mock_get_value: MagicMock) -> None:
        """Sin duplicado → OK."""
        mock_get_value.return_value = None
        doc = _get_vat_voucher_instance()

        doc.validate_unique_voucher_number()  # No debería lanzar

    # ─────────────────────────────────────────────
    # validate_fiscal_period()
    # ─────────────────────────────────────────────

    def test_fiscal_period_valid_format(self) -> None:
        """Formato MM/YYYY válido → pasa sin error."""
        doc = _get_vat_voucher_instance(fiscal_period="04/2026")

        doc.validate_fiscal_period()

    def test_fiscal_period_invalid_format_raises(self) -> None:
        """Formato inválido (YYYY-MM) → frappe.throw."""
        doc = _get_vat_voucher_instance(fiscal_period="2026-04")

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_fiscal_period()

    def test_fiscal_period_invalid_month_raises(self) -> None:
        """Mes fuera de rango (13) → frappe.throw."""
        doc = _get_vat_voucher_instance(fiscal_period="13/2026")

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_fiscal_period()

    def test_fiscal_period_empty_skips(self) -> None:
        """Periodo fiscal vacío → skip sin error."""
        doc = _get_vat_voucher_instance(fiscal_period="")

        doc.validate_fiscal_period()

    # ─────────────────────────────────────────────
    # validate_withholding_amount()
    # ─────────────────────────────────────────────

    def test_zero_vat_amount_raises_error(self) -> None:
        """totals_tax_amount_vat = 0 → frappe.throw."""
        doc = _get_vat_voucher_instance(totals_tax_amount_vat=0)

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.validate_withholding_amount()

    def test_positive_vat_amount_passes(self) -> None:
        """totals_tax_amount_vat > 0 → OK."""
        doc = _get_vat_voucher_instance(totals_tax_amount_vat=500.0)

        doc.validate_withholding_amount()

    # ─────────────────────────────────────────────
    # on_trash()
    # ─────────────────────────────────────────────

    def test_on_trash_allows_current_month(self) -> None:
        """issue_date en mes actual → permite eliminar."""
        doc = _get_vat_voucher_instance(issue_date=nowdate())

        doc.on_trash()

    def test_on_trash_blocks_previous_month(self) -> None:
        """issue_date en mes anterior → frappe.throw."""
        previous_month: str = add_months(nowdate(), -1)
        doc = _get_vat_voucher_instance(issue_date=previous_month)

        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.on_trash()
