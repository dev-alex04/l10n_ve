# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de make_vat_withholding_voucher / make_islr_withholding_voucher:
creación de comprobantes de retención pre-llenados desde una factura de
compra (botones del formulario de Purchase Invoice).

La línea se calcula con el get_valid_invoices existente (mockeado aquí);
estos tests cubren el armado del borrador, los totales del padre (que no
se recalculan en el servidor) y los guards de duplicado/estado.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher import (
    make_islr_withholding_voucher,
)
from l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher import (
    make_vat_withholding_voucher,
)

_VAT_MOD = "l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher"
_ISLR_MOD = "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher"

_PI_NAME = "ACC-PINV-TEST-0001"

_real_get_doc = frappe.get_doc


def _fake_purchase_invoice(**overrides) -> frappe._dict:
    invoice = frappe._dict(
        name=_PI_NAME,
        docstatus=1,
        supplier="PROVEEDOR TEST",
        company="Galanet Solution C.A.",
        posting_date="2026-07-01",
        branch="HQ",
    )
    invoice.update(overrides)
    return invoice


def _patch_get_doc(invoice):
    """Patch selectivo: Purchase Invoice → mock; el resto (new_doc) pasa al real."""

    def side_effect(*args, **kwargs):
        if args and args[0] == "Purchase Invoice":
            return invoice
        return _real_get_doc(*args, **kwargs)

    return patch("frappe.get_doc", side_effect=side_effect)


def _vat_row(**overrides) -> dict:
    row = {
        "purchase_invoice_type": "Purchase Invoice",
        "purchase_invoice": _PI_NAME,
        "bill_no": "81532861",
        "bill_control": "0004188108",
        "posting_date": "2026-07-01",
        "grand_total": 790804.14,
        "total_exempt": 3067.89,
        "total": 679082.97,
        "taxes_and_charges_added": 108653.28,
        "tax_amount_vat": 81489.96,
        "rate": 16,
        "withholding_rate": 75,
        "is_return": 0,
    }
    row.update(overrides)
    return row


def _islr_row(**overrides) -> dict:
    row = {
        "purchase_invoice_type": "Purchase Invoice",
        "purchase_invoice": _PI_NAME,
        "doc_no": "81532861",
        "doc_type": "FACT",
        "bill_control": "0004188108",
        "posting_date": "2026-07-01",
        "rate": 5.0,
        "subtracting": 0.0,
        "islr_amount": 9723.92,
        "code": "P051",
        "islr_base_amount": 194478.20,
        "grand_total": 177947.55,
        "total": 194478.20,
        "paid_amount": 0.0,
        "is_return": 0,
    }
    row.update(overrides)
    return row


class TestMakeVatWithholdingVoucher(FrappeTestCase):
    """make_vat_withholding_voucher: borrador IVA desde la factura."""

    def test_happy_path_builds_unsaved_draft(self) -> None:
        """Factura válida → borrador sin insertar con línea y totales."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_VAT_MOD}._find_voucher_containing_invoice", return_value=None), \
             patch(f"{_VAT_MOD}.get_valid_invoices", return_value=[_vat_row()]) as mock_fetch:
            doc = make_vat_withholding_voucher(_PI_NAME)

        mock_fetch.assert_called_once_with(
            supplier="PROVEEDOR TEST",
            start_date="2026-07-01",
            end_date="2026-07-01",
            company="Galanet Solution C.A.",
            branch="HQ",
        )
        self.assertTrue(doc.get("__islocal"))
        self.assertEqual(doc.empresa, "Galanet Solution C.A.")
        self.assertEqual(doc.supplier, "PROVEEDOR TEST")
        self.assertEqual(doc.branch, "HQ")
        self.assertEqual(str(doc.start_date), "2026-07-01")
        self.assertEqual(str(doc.end_date), "2026-07-01")
        self.assertEqual(len(doc.vat_withholding_voucher_item), 1)
        self.assertEqual(doc.vat_withholding_voucher_item[0].purchase_invoice, _PI_NAME)
        self.assertAlmostEqual(doc.totals_grand_total, 790804.14)
        self.assertAlmostEqual(doc.totals_total, 679082.97)
        self.assertAlmostEqual(doc.totals_total_exempt, 3067.89)
        self.assertAlmostEqual(doc.totals_taxes_and_charges_added, 108653.28)
        self.assertAlmostEqual(doc.totals_tax_amount_vat, 81489.96)

    def test_branchless_invoice_passes_empty_branch(self) -> None:
        """Factura sin sucursal → branch='' (semántica NULL-only de get_valid_invoices)."""
        invoice = _fake_purchase_invoice(branch=None)
        with _patch_get_doc(invoice), \
             patch(f"{_VAT_MOD}._find_voucher_containing_invoice", return_value=None), \
             patch(f"{_VAT_MOD}.get_valid_invoices", return_value=[_vat_row()]) as mock_fetch:
            doc = make_vat_withholding_voucher(_PI_NAME)

        self.assertEqual(mock_fetch.call_args.kwargs["branch"], "")
        self.assertFalse(doc.branch)

    def test_draft_invoice_blocked(self) -> None:
        """Factura sin validar → throw."""
        invoice = _fake_purchase_invoice(docstatus=0)
        with _patch_get_doc(invoice):
            self.assertRaises(
                frappe.ValidationError, make_vat_withholding_voucher, _PI_NAME
            )

    def test_already_in_draft_voucher_blocked(self) -> None:
        """Factura ya en un comprobante en borrador → throw con el nombre."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_VAT_MOD}._find_voucher_containing_invoice",
                   side_effect=lambda name, docstatus: "COMP-RET-IVA-2026-00099" if docstatus == 0 else None):
            with self.assertRaises(frappe.ValidationError) as ctx:
                make_vat_withholding_voucher(_PI_NAME)
        self.assertIn("COMP-RET-IVA-2026-00099", str(ctx.exception))

    def test_already_in_submitted_voucher_blocked(self) -> None:
        """Sin filas y ya en comprobante aprobado → throw con el nombre."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_VAT_MOD}._find_voucher_containing_invoice",
                   side_effect=lambda name, docstatus: "COMP-RET-IVA-2026-00042" if docstatus == 1 else None), \
             patch(f"{_VAT_MOD}.get_valid_invoices", return_value=[]):
            with self.assertRaises(frappe.ValidationError) as ctx:
                make_vat_withholding_voucher(_PI_NAME)
        self.assertIn("COMP-RET-IVA-2026-00042", str(ctx.exception))

    def test_no_withholding_row_blocked(self) -> None:
        """Sin filas y sin comprobante previo → 'no tiene retención de IVA'."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_VAT_MOD}._find_voucher_containing_invoice", return_value=None), \
             patch(f"{_VAT_MOD}.get_valid_invoices", return_value=[]):
            with self.assertRaises(frappe.ValidationError) as ctx:
                make_vat_withholding_voucher(_PI_NAME)
        self.assertIn("retención de IVA", str(ctx.exception))


class TestMakeIslrWithholdingVoucher(FrappeTestCase):
    """make_islr_withholding_voucher: borrador ISLR desde la factura."""

    def test_happy_path_multi_concept_sums_totals(self) -> None:
        """Dos conceptos ISLR → dos líneas y totales sumados."""
        invoice = _fake_purchase_invoice()
        rows = [
            _islr_row(),
            _islr_row(code="P034", rate=3.0, islr_amount=1500.0,
                      islr_base_amount=50000.0, grand_total=52000.0),
        ]
        with _patch_get_doc(invoice), \
             patch(f"{_ISLR_MOD}._find_voucher_containing_invoice", return_value=None), \
             patch(f"{_ISLR_MOD}.get_valid_invoices", return_value=rows) as mock_fetch:
            doc = make_islr_withholding_voucher(_PI_NAME)

        mock_fetch.assert_called_once_with(
            supplier="PROVEEDOR TEST",
            start_date="2026-07-01",
            end_date="2026-07-01",
            company="Galanet Solution C.A.",
            branch="HQ",
        )
        self.assertTrue(doc.get("__islocal"))
        self.assertEqual(len(doc.islr_withholding_voucher_item), 2)
        self.assertAlmostEqual(doc.totals_islr_amount, 9723.92 + 1500.0)
        self.assertAlmostEqual(doc.totals_islr_base_amount, 194478.20 + 50000.0)
        self.assertAlmostEqual(doc.totals_grand_total, 177947.55 + 52000.0)
        self.assertAlmostEqual(doc.totals_paid_amount, 0.0)

    def test_already_in_draft_voucher_blocked(self) -> None:
        """Factura ya en un comprobante ISLR en borrador → throw."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_ISLR_MOD}._find_voucher_containing_invoice",
                   side_effect=lambda name, docstatus: "COMP-RET-ISLR-2026-00007" if docstatus == 0 else None):
            with self.assertRaises(frappe.ValidationError) as ctx:
                make_islr_withholding_voucher(_PI_NAME)
        self.assertIn("COMP-RET-ISLR-2026-00007", str(ctx.exception))

    def test_no_islr_concepts_blocked(self) -> None:
        """Sin conceptos ISLR ni comprobante previo → mensaje de 'Agregar ISLR'."""
        invoice = _fake_purchase_invoice()
        with _patch_get_doc(invoice), \
             patch(f"{_ISLR_MOD}._find_voucher_containing_invoice", return_value=None), \
             patch(f"{_ISLR_MOD}.get_valid_invoices", return_value=[]):
            with self.assertRaises(frappe.ValidationError) as ctx:
                make_islr_withholding_voucher(_PI_NAME)
        self.assertIn("ISLR", str(ctx.exception))
