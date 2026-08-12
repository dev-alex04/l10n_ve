# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios de la funcionalidad de Asiento Contable para Retención Gubernamental
en Facturas de Venta (Sales Invoice).
"""

from unittest import TestCase
from unittest.mock import patch, MagicMock

import frappe

from l10n_ve.overrides.sales_invoice import (
    get_company_government_withholding_account,
    create_government_withholding_journal_entry,
)

_MOD = "l10n_ve.overrides.sales_invoice"


class TestGovernmentWithholdingJournalEntry(TestCase):
    def setUp(self) -> None:
        super().setUp()
        if not hasattr(frappe.local, "flags"):
            frappe.local.flags = frappe._dict()
        frappe.local.flags.in_test = True
        frappe.local.message_log = []
        frappe.local.conf = frappe._dict(host_name="http://localhost")
        frappe.cache = MagicMock()
        frappe.db = MagicMock()

        self._patch_trans = patch(f"{_MOD}._", side_effect=lambda msg, *a, **kw: msg)
        self._patch_trans.start()

        self.company_name = "_Test Company"
        self.gov_account = "_Test Retenciones Gubernamentales - _TC"
        self.debtors_account = "Debtors - _TC"

    def tearDown(self) -> None:
        self._patch_trans.stop()
        super().tearDown()

    def test_get_company_government_withholding_account_success(self) -> None:
        with patch(f"{_MOD}.frappe.db.get_value", return_value=self.gov_account):
            acc = get_company_government_withholding_account(self.company_name)
            self.assertEqual(acc, self.gov_account)

    def test_get_company_government_withholding_account_missing_raises(self) -> None:
        with patch(f"{_MOD}.frappe.db.get_value", return_value=None):
            with self.assertRaises(frappe.ValidationError):
                get_company_government_withholding_account(self.company_name)

    @patch(f"{_MOD}._require_withholding_permissions")
    def test_create_government_withholding_je_draft_invoice_raises(self, mock_perm) -> None:
        mock_doc = MagicMock()
        mock_doc.name = "ACC-SINV-2026-00001"
        mock_doc.docstatus = 0
        mock_doc.company = self.company_name

        with patch(f"{_MOD}.frappe.get_doc", return_value=mock_doc):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    @patch(f"{_MOD}._require_withholding_permissions")
    def test_create_government_withholding_je_exceeds_outstanding_raises(self, mock_perm) -> None:
        mock_doc = MagicMock()
        mock_doc.name = "ACC-SINV-2026-00001"
        mock_doc.docstatus = 1
        mock_doc.outstanding_amount = 50.0
        mock_doc.base_grand_total = 500.0
        mock_doc.grand_total = 500.0
        mock_doc.company = self.company_name

        with patch(f"{_MOD}.frappe.get_doc", return_value=mock_doc), \
             patch(f"{_MOD}.frappe.db.get_value", return_value="VED"):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    @patch(f"{_MOD}._require_withholding_permissions")
    def test_create_government_withholding_je_missing_company_account_raises(self, mock_perm) -> None:
        mock_doc = MagicMock()
        mock_doc.name = "ACC-SINV-2026-00001"
        mock_doc.docstatus = 1
        mock_doc.outstanding_amount = 150.0
        mock_doc.base_grand_total = 500.0
        mock_doc.grand_total = 500.0
        mock_doc.company = self.company_name

        with patch(f"{_MOD}.frappe.get_doc", return_value=mock_doc), \
             patch(f"{_MOD}.get_company_government_withholding_account", side_effect=frappe.ValidationError("Missing account")):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    @patch(f"{_MOD}._require_withholding_permissions")
    def test_create_government_withholding_je_positive_flow(self, mock_perm) -> None:
        mock_invoice = frappe._dict({
            "name": "ACC-SINV-2026-00001",
            "docstatus": 1,
            "outstanding_amount": 500.0,
            "base_grand_total": 500.0,
            "grand_total": 500.0,
            "company": self.company_name,
            "customer": "_Test Customer",
            "debit_to": self.debtors_account,
            "cost_center": "Main - _TC",
            "currency": "VED",
            "conversion_rate": 1.0,
        })

        mock_je = MagicMock()
        mock_je.name = "ACC-JV-2026-00001"
        mock_je.accounts = []
        def append_acc(field, row):
            mock_je.accounts.append(row)
        mock_je.append = append_acc

        with patch(f"{_MOD}.frappe.get_doc", return_value=mock_invoice), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.frappe.db.get_value", return_value="VED"), \
             patch(f"{_MOD}.frappe.new_doc", return_value=mock_je):

            res = create_government_withholding_journal_entry(
                docname="ACC-SINV-2026-00001",
                amount=100.0,
                description="Retención Timbre Fiscal 100 Bs",
                voucher_number="V-202608-01"
            )

            self.assertEqual(res["status"], "success")
            self.assertEqual(res["journal_entry"], "ACC-JV-2026-00001")
            self.assertEqual(mock_je.user_remark, "Comprobante N°: V-202608-01 - Retención Timbre Fiscal 100 Bs")
            mock_je.insert.assert_called_once()
            mock_je.submit.assert_called_once()
            self.assertEqual(len(mock_je.accounts), 2)
            # Fila Debe: Retenciones Gubernamentales
            self.assertEqual(mock_je.accounts[0]["account"], self.gov_account)
            self.assertEqual(mock_je.accounts[0]["debit"], 100.0)
            # Fila Haber: Debtors vinculado a Sales Invoice
            self.assertEqual(mock_je.accounts[1]["account"], self.debtors_account)
            self.assertEqual(mock_je.accounts[1]["party"], "_Test Customer")
            self.assertEqual(mock_je.accounts[1]["reference_type"], "Sales Invoice")
            self.assertEqual(mock_je.accounts[1]["reference_name"], "ACC-SINV-2026-00001")
            self.assertEqual(mock_je.accounts[1]["credit"], 100.0)
