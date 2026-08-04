# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate
from l10n_ve.l10n_ve.report.islr_withholding import islr_withholding
from l10n_ve.l10n_ve.report.islr_withholding_voucher_purchase.islr_withholding_voucher_purchase import generate_islr_report

_COMPANY = "GS LATAM TELECOM, C.A"
_SUPPLIER = "TEST-ISLR-REP-SUPP"
_VOUCHER_DRAFT = "TEST-ISLR-V-DRAFT"
_VOUCHER_APPROVED = "TEST-ISLR-V-APPROVED"
_VOUCHER_CANCELLED = "TEST-ISLR-V-CANCELLED"

class TestISLRWithholdingReport(FrappeTestCase):
    """Tests for ISLR withholding report queries and document calculations."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._cleanup()
        cls._make_supplier()
        cls._make_vouchers()
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup()
        frappe.db.commit()
        super().tearDownClass()

    @classmethod
    def _cleanup(cls) -> None:
        targets = [_VOUCHER_DRAFT, _VOUCHER_APPROVED, _VOUCHER_CANCELLED]
        frappe.db.delete("ISLR Withholding Voucher Item", {"parent": ["in", targets]})
        frappe.db.delete("ISLR Withholding Voucher", {"name": ["in", targets]})
        frappe.db.delete("Supplier", {"name": _SUPPLIER})

    @classmethod
    def _make_supplier(cls) -> None:
        supp = frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": _SUPPLIER,
            "supplier_group": "All Supplier Groups",
            "tax_id": "J-12345678-9",
            "type_of_person": "Domiciled legal entity",
        })
        supp.name = _SUPPLIER
        supp.db_insert()

    @classmethod
    def _make_vouchers(cls) -> None:
        # 1. Draft Voucher (docstatus = 0)
        v_draft = frappe.get_doc({
            "doctype": "ISLR Withholding Voucher",
            "empresa": _COMPANY,
            "supplier": _SUPPLIER,
            "posting_date": nowdate(),
            "start_date": nowdate(),
            "end_date": nowdate(),
            "voucher_number": "20260700000001",
            "docstatus": 0,  # Draft
        })
        v_draft.name = _VOUCHER_DRAFT
        v_draft.db_insert()
        cls._make_item(_VOUCHER_DRAFT, "FACT", "TEST-INV-DRAFT", 10000, 100, 1)

        # 2. Approved Voucher (docstatus = 1)
        v_approved = frappe.get_doc({
            "doctype": "ISLR Withholding Voucher",
            "empresa": _COMPANY,
            "supplier": _SUPPLIER,
            "posting_date": nowdate(),
            "start_date": nowdate(),
            "end_date": nowdate(),
            "voucher_number": "20260700000002",
            "docstatus": 1,  # Approved
        })
        v_approved.name = _VOUCHER_APPROVED
        v_approved.db_insert()
        # Mix invoice (FACT) and credit note (N/CR) to test subtracting sign!
        cls._make_item(_VOUCHER_APPROVED, "FACT", "TEST-INV-APP-1", 20000, 200, 1)
        cls._make_item(_VOUCHER_APPROVED, "N/CR", "TEST-INV-APP-2", 5000, 50, 2)

        # 3. Cancelled Voucher (docstatus = 2)
        v_cancelled = frappe.get_doc({
            "doctype": "ISLR Withholding Voucher",
            "empresa": _COMPANY,
            "supplier": _SUPPLIER,
            "posting_date": nowdate(),
            "start_date": nowdate(),
            "end_date": nowdate(),
            "voucher_number": "20260700000003",
            "docstatus": 2,  # Cancelled
        })
        v_cancelled.name = _VOUCHER_CANCELLED
        v_cancelled.db_insert()
        cls._make_item(_VOUCHER_CANCELLED, "FACT", "TEST-INV-CANC", 30000, 300, 1)

    @classmethod
    def _make_item(cls, parent, doc_type, purchase_invoice, islr_base_amount, subtracting, idx) -> None:
        item = frappe.get_doc({
            "doctype": "ISLR Withholding Voucher Item",
            "parent": parent,
            "parenttype": "ISLR Withholding Voucher",
            "parentfield": "islr_withholding_voucher_item",
            "idx": idx,
            "doc_type": doc_type,
            "purchase_invoice": purchase_invoice,
            "purchase_invoice_type": "Purchase Invoice" if doc_type == "FACT" else "VE Purchase Credit Note",
            "posting_date": nowdate(),
            "doc_no": f"DOC-{purchase_invoice}",
            "bill_control": "00-00001",
            "islr_base_amount": islr_base_amount,
            "subtracting": subtracting,
            "islr_amount": islr_base_amount * 0.02 - subtracting,
            "code": "001",
        })
        item.name = f"TEST-ISLR-ITEM-{parent}-{idx}"
        item.db_insert()

    def test_grouped_by_supplier_excludes_draft_and_cancelled(self) -> None:
        """Grouped report 'Por Proveedor' must only include docstatus = 1 (Approved)."""
        filters = {
            "company": _COMPANY,
            "from_date": nowdate(),
            "to_date": nowdate(),
            "group_by": "Por Proveedor",
            "supplier": _SUPPLIER,
        }
        _columns, data = islr_withholding.execute(filters)
        self.assertEqual(len(data), 1, "Only one row (approved voucher) should be aggregated for the supplier")
        
        row = data[0]
        # Sum of islr_base_amount for approved: 20000 (FACT) + 5000 (N/CR) = 25000
        self.assertAlmostEqual(flt(row.get("islr_base_amount")), 25000.0, places=2)

    def test_detailed_view_includes_draft_but_excludes_cancelled(self) -> None:
        """Detailed report must include docstatus = 0 & 1, but exclude docstatus = 2."""
        filters = {
            "company": _COMPANY,
            "from_date": nowdate(),
            "to_date": nowdate(),
            "group_by": "Detalle",
            "supplier": _SUPPLIER,
        }
        _columns, data = islr_withholding.execute(filters)
        
        # Should include: 1 draft row + 2 approved rows = 3 rows total
        self.assertEqual(len(data), 3, "Detailed view should contain draft and approved rows, but no cancelled rows")
        
        cancelled_rows = [r for r in data if r.get("parent") == _VOUCHER_CANCELLED]
        self.assertEqual(len(cancelled_rows), 0, "Cancelled voucher must be excluded from detailed report")

    def test_totals_subtracting_calculates_with_nc_sign(self) -> None:
        """Totals subtracting must correctly handle N/CR sign (subtracting it)."""
        # Approved voucher has:
        #   Item 1 (FACT): subtracting = 200
        #   Item 2 (N/CR): subtracting = 50
        # Expected totals_subtracting: 200 - 50 = 150
        html = generate_islr_report(_VOUCHER_APPROVED)
        
        # Verify that 150.00 is rendered in the HTML totals row
        self.assertTrue("150.00" in html or "150,00" in html, "The total subtracting amount 150.00 should be formatted and rendered in the report HTML")

    def test_xml_doc_number_sanitization(self) -> None:
        """_clean_xml_doc_number: dígitos declarables, o None si habría que inventar el número."""
        from l10n_ve.l10n_ve.report.purchase_book.purchase_book import (
            _XML_MAX_CONTROL_DIGITS,
            _XML_MAX_FACTURA_DIGITS,
            _clean_xml_doc_number,
        )

        def factura(val: str | None) -> str | None:
            return _clean_xml_doc_number(val, _XML_MAX_FACTURA_DIGITS)

        def control(val: str | None) -> str | None:
            return _clean_xml_doc_number(val, _XML_MAX_CONTROL_DIGITS)

        # Serie-número: se declara la parte numérica, con su relleno original intacto.
        self.assertEqual(factura("B-9523"), "9523")
        self.assertEqual(factura("MSO-01-0000028078"), "0000028078")
        self.assertEqual(factura("MSO-01-0000028079"), "0000028079")
        self.assertEqual(factura("F01-0001234"), "0001234")
        self.assertEqual(control("00-03367729"), "03367729")

        # Excede el tope solo por el relleno: quitarlo no cambia el número.
        self.assertEqual(control("00003367734"), "3367734")

        # Sin dígitos tras el guion: se reintenta sobre el valor completo.
        self.assertEqual(factura("0001234-A"), "0001234")

        # Excede el tope AUN sin relleno -> no se declara. Recortarlo daría un número
        # que no es el del documento y rompería el cruce del SENIAT.
        self.assertIsNone(factura("22225011624"), "11 dígitos significativos: no se recorta")
        self.assertIsNone(control("0158353167"), "9 significativos tras el cero: no se recorta")
        self.assertIsNone(control("123456789"))

        # Sin nada declarable.
        for empty in (None, "", "   ", "N/A", "SIN NUMERO"):
            self.assertIsNone(factura(empty), f"{empty!r} no aporta dígitos")

    def test_xml_rif_sanitization(self) -> None:
        """_clean_xml_rif: letra y dígitos en mayúsculas, sin separadores."""
        from l10n_ve.l10n_ve.report.purchase_book.purchase_book import _clean_xml_rif

        self.assertEqual(_clean_xml_rif("J-30909786-5"), "J309097865")
        self.assertEqual(_clean_xml_rif(" j-30909786-5 "), "J309097865")
        self.assertEqual(_clean_xml_rif("V12345678"), "V12345678")

        for empty in (None, "", "  ", "---"):
            self.assertIsNone(_clean_xml_rif(empty), f"{empty!r} no deja RIF declarable")

