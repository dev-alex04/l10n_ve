# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la Retención Gubernamental por Asiento Contable en Factura de Venta.

Cubre el tope contra el saldo pendiente —que es lo que acota la suma cuando se
registran VARIAS retenciones sobre la misma factura— y la conversión del pendiente
a la moneda de la empresa, que es donde la versión anterior adivinaba.
"""

from unittest import TestCase
from unittest.mock import patch, MagicMock

import frappe

from l10n_ve.overrides.sales_invoice import (
    get_company_government_withholding_account,
    create_government_withholding_journal_entry,
    _outstanding_in_company_currency,
)

_MOD = "l10n_ve.overrides.sales_invoice"


def setUpModule() -> None:
    """`frappe.throw` escribe en `frappe.local.message_log`; bajo `bench run-tests` ya
    existe, pero así el archivo también corre suelto con `python -m unittest`."""
    if getattr(frappe.local, "message_log", None) is None:
        frappe.local.message_log = []


BS = "VED"
USD = "USD"


def _invoice(**overrides) -> frappe._dict:
    """Factura de venta aprobada, en Bs, sin cruce de monedas salvo que se pida."""
    data = frappe._dict({
        "name": "ACC-SINV-2026-00001",
        "docstatus": 1,
        "company": "_Test Company",
        "customer": "_Test Customer",
        "debit_to": "Debtors - _TC",
        "cost_center": "Main - _TC",
        "currency": BS,
        "conversion_rate": 1.0,
        "party_account_currency": BS,
        "outstanding_amount": 500.0,
        "grand_total": 500.0,
        "base_grand_total": 500.0,
    })
    data.update(overrides)
    return data


class TestOutstandingInCompanyCurrency(TestCase):
    """La conversión del pendiente: el punto donde antes se adivinaba."""

    def setUp(self) -> None:
        self._cached = patch(f"{_MOD}.frappe.get_cached_value", return_value=BS)
        self._cached.start()
        self.addCleanup(self._cached.stop)

    def test_receivable_in_company_currency_is_used_as_is(self) -> None:
        self.assertEqual(_outstanding_in_company_currency(_invoice()), 500.0)

    def test_receivable_in_invoice_currency_is_converted(self) -> None:
        """CxC en USD sobre factura en USD: el pendiente se lleva a Bs con la tasa."""
        inv = _invoice(currency=USD, party_account_currency=USD,
                       conversion_rate=40.0, outstanding_amount=100.0)
        self.assertEqual(_outstanding_in_company_currency(inv), 4000.0)

    def test_conversion_without_rate_fails_closed(self) -> None:
        inv = _invoice(currency=USD, party_account_currency=USD,
                       conversion_rate=0.0, outstanding_amount=100.0)
        with self.assertRaises(frappe.ValidationError):
            _outstanding_in_company_currency(inv)

    def test_unresolvable_currency_combination_fails_closed(self) -> None:
        """CxC en una moneda que no es ni la de la empresa ni la de la factura: corta."""
        inv = _invoice(currency=USD, party_account_currency="EUR")
        with self.assertRaises(frappe.ValidationError):
            _outstanding_in_company_currency(inv)


class TestGovernmentWithholdingJournalEntry(TestCase):

    def setUp(self) -> None:
        self.gov_account = "Retenciones Gubernamentales - _TC"

        # frappe.db se reemplaza sólo durante el test: dejarlo mockeado a nivel de
        # módulo contamina el resto de la corrida.
        self._db = patch(f"{_MOD}.frappe.db", MagicMock())
        self._db.start()
        self.addCleanup(self._db.stop)

        self._cached = patch(f"{_MOD}.frappe.get_cached_value", side_effect=self._cached_value)
        self._cached.start()
        self.addCleanup(self._cached.stop)

        self._link = patch(f"{_MOD}.get_link_to_form", return_value="<a>JV</a>")
        self._link.start()
        self.addCleanup(self._link.stop)

        self._perm = patch(f"{_MOD}._require_withholding_permissions")
        self._perm.start()
        self.addCleanup(self._perm.stop)

    @staticmethod
    def _cached_value(doctype, name, fieldname):
        return {"default_currency": BS, "cost_center": "Main - _TC"}.get(fieldname)

    def _make_je(self):
        je = MagicMock()
        je.name = "ACC-JV-2026-00001"
        je.accounts = []
        je.append = lambda field, row: je.accounts.append(row)
        return je

    # ── Validaciones ────────────────────────────────────────────────────────

    def test_amount_must_be_positive(self) -> None:
        with self.assertRaises(frappe.ValidationError):
            create_government_withholding_journal_entry("ACC-SINV-2026-00001", 0)

    def test_draft_invoice_is_rejected(self) -> None:
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice(docstatus=0)):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    def test_amount_above_outstanding_is_rejected(self) -> None:
        """Es el tope que acota la suma de varias retenciones sobre la misma factura."""
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice(outstanding_amount=50.0)), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=BS):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    def test_amount_equal_to_outstanding_is_allowed(self) -> None:
        je = self._make_je()
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice(outstanding_amount=100.0)), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=BS), \
             patch(f"{_MOD}.frappe.new_doc", return_value=je):
            res = create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)
        self.assertEqual(res["status"], "success")

    def test_gov_account_in_another_currency_fails_closed(self) -> None:
        """Antes se posteaba el importe en Bs como si fuera la moneda de la cuenta, a tasa 1."""
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice()), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=USD):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    def test_missing_company_account_raises(self) -> None:
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice()), \
             patch(f"{_MOD}.get_company_government_withholding_account",
                   side_effect=frappe.ValidationError("sin cuenta")):
            with self.assertRaises(frappe.ValidationError):
                create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

    # ── El asiento ──────────────────────────────────────────────────────────

    def test_journal_entry_shape_in_local_currency(self) -> None:
        je = self._make_je()
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice()), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=BS), \
             patch(f"{_MOD}.frappe.new_doc", return_value=je):
            res = create_government_withholding_journal_entry(
                "ACC-SINV-2026-00001", 100.0,
                description="Timbre fiscal", voucher_number="V-01",
            )

        self.assertEqual(res["journal_entry"], "ACC-JV-2026-00001")
        je.insert.assert_called_once_with(ignore_permissions=True)
        je.submit.assert_called_once()
        self.assertEqual(je.user_remark, "Comprobante N°: V-01 - Timbre fiscal")
        self.assertEqual(je.multi_currency, 0)

        debe, haber = je.accounts
        self.assertEqual(debe["account"], self.gov_account)
        self.assertEqual(debe["debit"], 100.0)
        self.assertEqual(haber["account"], "Debtors - _TC")
        self.assertEqual(haber["credit"], 100.0)
        self.assertEqual(haber["reference_type"], "Sales Invoice")
        self.assertEqual(haber["reference_name"], "ACC-SINV-2026-00001")

    def test_receivable_in_foreign_currency_splits_the_amount(self) -> None:
        """CxC en USD: el Haber va en Bs y la moneda de cuenta lleva el equivalente."""
        je = self._make_je()
        inv = _invoice(currency=USD, party_account_currency=USD,
                       conversion_rate=40.0, outstanding_amount=100.0)
        with patch(f"{_MOD}.frappe.get_doc", return_value=inv), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", side_effect=[BS, USD]), \
             patch(f"{_MOD}.frappe.new_doc", return_value=je):
            create_government_withholding_journal_entry("ACC-SINV-2026-00001", 800.0)

        haber = je.accounts[1]
        self.assertEqual(je.multi_currency, 1)
        self.assertEqual(haber["credit"], 800.0)
        self.assertEqual(haber["exchange_rate"], 40.0)
        self.assertEqual(haber["credit_in_account_currency"], 20.0)

    def test_voucher_number_is_optional(self) -> None:
        je = self._make_je()
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice()), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=BS), \
             patch(f"{_MOD}.frappe.new_doc", return_value=je):
            create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

        self.assertNotIn("Comprobante", je.user_remark)

    def test_invoice_row_is_locked_before_reading_the_balance(self) -> None:
        """Sin el bloqueo, dos clics simultáneos leen el mismo pendiente y ambos pasan."""
        je = self._make_je()
        with patch(f"{_MOD}.frappe.get_doc", return_value=_invoice()), \
             patch(f"{_MOD}.get_company_government_withholding_account", return_value=self.gov_account), \
             patch(f"{_MOD}.get_account_currency", return_value=BS), \
             patch(f"{_MOD}.frappe.new_doc", return_value=je):
            create_government_withholding_journal_entry("ACC-SINV-2026-00001", 100.0)

        frappe.db.get_value.assert_any_call(
            "Sales Invoice", "ACC-SINV-2026-00001", "outstanding_amount", for_update=True
        )


class TestCompanyAccountLookup(TestCase):

    def test_returns_configured_account(self) -> None:
        with patch(f"{_MOD}.frappe.db") as db:
            db.get_value.return_value = "Retenciones - _TC"
            self.assertEqual(
                get_company_government_withholding_account("_Test Company"), "Retenciones - _TC"
            )

    def test_missing_account_raises(self) -> None:
        with patch(f"{_MOD}.frappe.db") as db:
            db.get_value.return_value = None
            with self.assertRaises(frappe.ValidationError):
                get_company_government_withholding_account("_Test Company")

    def test_missing_company_raises(self) -> None:
        with self.assertRaises(frappe.ValidationError):
            get_company_government_withholding_account("")
