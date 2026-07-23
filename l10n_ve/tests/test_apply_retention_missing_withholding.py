# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la aplicación retroactiva de retenciones IVA/ISLR sobre facturas ya
aprobadas (``l10n_ve.overrides.sales_invoice``).

Cubre la lógica determinista del endpoint ``fix_missing_withholding`` y sus
ayudantes tras las correcciones del review del PR #424:

- ``_require_withholding_permissions``: gate por roles contables genéricos.
- ``validate_withholding_tax_account``: cuenta de la compañía / no-grupo / oficial.
- ``calculate_withholding_base_amount``: monto recalculado en el servidor, con la
  TASA resuelta server-side (get_vat_category_rate para IVA, alícuota del Tabulador
  para ISLR) — no se confía el ``rate`` del cliente.
- ``get_verified_invoice``: resolución por name / bill_no acotada por compañía.
- ``handle_voucher_metadata``: completitud, ask_overwrite, only_line, alta (delega
  en upload_voucher_data / upload_islr_voucher_data, propagando registration_date).
- ``create_sales_taxes_row``: fila "Deduct" bien formada.
- ``create_withholding_journal_entry``: cuadre del asiento, ramas
  pagada / parcial / sobrepago (con ``is_advance='Yes'``) y multimoneda USD
  (saldo convertido a Bs).
- ``fix_missing_withholding``: orquestación con ``company`` y guardia de duplicados.

Son tests unitarios con mocks: NO tocan la base de datos ni el sitio (se parchean
``frappe.new_doc`` / ``frappe.db.*`` / los ayudantes). Requieren sitio solo porque
``FrappeTestCase`` abre una transacción.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides import sales_invoice as si


# --------------------------------------------------------------------------- #
# Dobles de prueba
# --------------------------------------------------------------------------- #
class _FakeJournalEntry:
    """Doble de 'Journal Entry' que registra las filas apiladas en 'accounts'."""

    def __init__(self):
        self.accounts = []
        self.flags = frappe._dict()
        self.name = "ACC-JV-TEST-0001"

    def append(self, table, row):
        assert table == "accounts"
        d = frappe._dict(row)
        self.accounts.append(d)
        return d

    def insert(self, *args, **kwargs):
        return self

    def submit(self, *args, **kwargs):
        return self


class _FakeTaxRow:
    """Doble de 'Sales Taxes and Charges' que captura ``db_insert()``."""

    def __init__(self):
        self.name = "TAXROW-TEST-0001"
        self.inserted = False

    def db_insert(self):
        self.inserted = True


def _invoice(**overrides):
    inv = frappe._dict(
        name="ACC-SINV-TEST-0001",
        company="Test Company",
        cost_center="Main - TC",
        debit_to="1100 - CxC - TC",
        customer="CUST-TEST-0001",
        posting_date="2026-01-15",
        outstanding_amount=0.0,
        currency="VEF",
        conversion_rate=1.0,
        base_net_total=0.0,
        docstatus=1,
        taxes=[],
        vat_withholding_voucher_number=None,
        voucher_image=None,
        islr_receipt_number=None,
        voucher_image_islr=None,
    )
    inv.update(overrides)
    return inv


def _sum(rows, key):
    return round(sum((r.get(key) or 0) for r in rows), 2)


# --------------------------------------------------------------------------- #
# _require_withholding_permissions
# --------------------------------------------------------------------------- #
class TestRequireWithholdingPermissions(FrappeTestCase):

    def test_user_without_accounting_role_denied(self):
        with patch("frappe.get_roles", return_value=["Guest", "Sales User"]):
            with self.assertRaises(frappe.PermissionError):
                si._require_withholding_permissions()

    def test_accounts_user_allowed(self):
        with patch("frappe.get_roles", return_value=["Accounts User"]):
            self.assertIsNone(si._require_withholding_permissions())


# --------------------------------------------------------------------------- #
# validate_withholding_tax_account
# --------------------------------------------------------------------------- #
class TestValidateWithholdingTaxAccount(FrappeTestCase):

    def _run(self, account_data, company_config, wtype="VAT", tax_account="2408 - IVA Ret - TC"):
        inv = _invoice()

        def _gv(doctype, name, fields, *a, **k):
            return account_data if doctype == "Account" else company_config

        with patch("frappe.db.get_value", side_effect=_gv):
            si.validate_withholding_tax_account(inv, wtype, tax_account)

    def test_valid_official_account_passes(self):
        self._run(
            account_data=frappe._dict(company="Test Company", is_group=0),
            company_config=frappe._dict(
                sales_vat_withholding_account="2408 - IVA Ret - TC",
                sales_islr_account="2409 - ISLR - TC",
            ),
        )  # no lanza

    def test_wrong_company_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._run(
                account_data=frappe._dict(company="Otra Company", is_group=0),
                company_config=frappe._dict(sales_vat_withholding_account="2408 - IVA Ret - TC"),
            )

    def test_group_account_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._run(
                account_data=frappe._dict(company="Test Company", is_group=1),
                company_config=frappe._dict(sales_vat_withholding_account="2408 - IVA Ret - TC"),
            )

    def test_non_official_account_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._run(
                account_data=frappe._dict(company="Test Company", is_group=0),
                company_config=frappe._dict(sales_vat_withholding_account="9999 - Otra - TC"),
            )

    def test_missing_account_raises(self):
        with self.assertRaises(frappe.ValidationError):
            self._run(account_data=None, company_config=frappe._dict())


# --------------------------------------------------------------------------- #
# calculate_withholding_base_amount  (tasa resuelta en el servidor)
# --------------------------------------------------------------------------- #
class TestCalculateWithholdingBaseAmount(FrappeTestCase):

    def test_vat_uses_invoice_iva_times_server_rate(self):
        """La tasa IVA se resuelve en el server (get_vat_category_rate), no del cliente."""
        inv = _invoice(taxes=[
            frappe._dict(charge_type="VAT", base_tax_amount=1600.0),
            frappe._dict(charge_type="Actual", base_tax_amount=999.0),  # ignorada
        ])
        with patch("frappe.db.get_value", return_value="CAT-1"), \
                patch.object(si, "get_vat_category_rate", return_value=75.0):
            # 1600 Bs de IVA * 75% = 1200 Bs
            self.assertAlmostEqual(
                si.calculate_withholding_base_amount(inv, "VAT"), 1200.0, places=2
            )

    def test_vat_zero_result_raises(self):
        inv = _invoice(taxes=[frappe._dict(charge_type="VAT", base_tax_amount=0.0)])
        with patch("frappe.db.get_value", return_value="CAT-1"), \
                patch.object(si, "get_vat_category_rate", return_value=75.0):
            with self.assertRaises(frappe.ValidationError):
                si.calculate_withholding_base_amount(inv, "VAT")

    def test_islr_uses_tabulator_aliquot_and_person_type(self):
        """La alícuota ISLR se toma del tramo del Tabulador (server), no del cliente."""
        inv = _invoice(base_net_total=10000.0)
        customer = frappe._dict(type_of_person="Domiciled legal entity", tabulator_islr="TAB-1")
        tab = frappe._dict(aliquot=[
            frappe._dict(types_of_person="Natural person domiciled", subtracting=0, percentage_base=100, aliquot=1),
            frappe._dict(types_of_person="Domiciled legal entity", subtracting=50, percentage_base=100, aliquot=3),
        ])
        with patch("frappe.db.get_value", return_value=customer), \
                patch("frappe.get_doc", return_value=tab):
            # base = 10000 * 100/100 = 10000; 10000 * 3% - 50 = 250 Bs
            self.assertAlmostEqual(
                si.calculate_withholding_base_amount(inv, "ISLR"), 250.0, places=2
            )

    def test_islr_without_tabulator_raises(self):
        inv = _invoice()
        with patch("frappe.db.get_value", return_value=frappe._dict(type_of_person="X", tabulator_islr=None)):
            with self.assertRaises(frappe.ValidationError):
                si.calculate_withholding_base_amount(inv, "ISLR")


# --------------------------------------------------------------------------- #
# get_verified_invoice
# --------------------------------------------------------------------------- #
class TestGetVerifiedInvoice(FrappeTestCase):

    def test_resolves_by_name_scoped_by_company(self):
        inv = _invoice(name="ACC-SINV-1")
        with patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_doc", return_value=inv) as gd:
            out = si.get_verified_invoice("ACC-SINV-1", "Test Company")
        self.assertIs(out, inv)
        gd.assert_called_once_with("Sales Invoice", "ACC-SINV-1")

    def test_resolves_by_bill_no_fallback(self):
        inv = _invoice(name="ACC-SINV-2")
        with patch("frappe.db.exists", return_value=False), \
                patch("frappe.db.get_value", return_value="ACC-SINV-2"), \
                patch("frappe.get_doc", return_value=inv) as gd:
            si.get_verified_invoice("00012345", "Test Company")
        gd.assert_called_once_with("Sales Invoice", "ACC-SINV-2")

    def test_not_found_raises(self):
        with patch("frappe.db.exists", return_value=False), \
                patch("frappe.db.get_value", return_value=None):
            with self.assertRaises(frappe.ValidationError):
                si.get_verified_invoice("does-not-exist", "Test Company")


# --------------------------------------------------------------------------- #
# handle_voucher_metadata  (ahora propaga registration_date)
# --------------------------------------------------------------------------- #
class TestHandleVoucherMetadata(FrappeTestCase):

    def test_incomplete_fields_raise(self):
        inv = _invoice()
        with self.assertRaises(frappe.ValidationError):
            si.handle_voucher_metadata(inv, "VAT", "12345678901234", None, None, False, False, "2026-07-20")

    def test_vat_existing_asks_overwrite(self):
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        res = si.handle_voucher_metadata(
            inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", False, False, "2026-07-20"
        )
        self.assertEqual(res["status"], "ask_overwrite")

    def test_vat_overwrite_delegates_to_upload(self):
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        with patch.object(si, "upload_voucher_data", return_value={"status": "success"}) as up:
            res = si.handle_voucher_metadata(
                inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", True, False, "2026-07-20"
            )
        self.assertEqual(res["status"], "proceed")
        up.assert_called_once()
        self.assertEqual(up.call_args.kwargs["voucher_number"], "12345678901234")
        self.assertEqual(up.call_args.kwargs["registration_date"], "2026-07-20")

    def test_only_line_keeps_existing_metadata(self):
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        with patch.object(si, "upload_voucher_data") as up:
            res = si.handle_voucher_metadata(
                inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", False, True, "2026-07-20"
            )
        self.assertEqual(res["status"], "proceed")
        up.assert_not_called()

    def test_islr_new_voucher_delegates_to_islr_upload(self):
        inv = _invoice()
        with patch.object(si, "upload_islr_voucher_data", return_value={"status": "success"}) as up:
            res = si.handle_voucher_metadata(
                inv, "ISLR", "CTRL-9", "2026-07-15", "/files/i.pdf", False, False, "2026-07-20"
            )
        self.assertEqual(res["status"], "proceed")
        up.assert_called_once()
        self.assertEqual(up.call_args.kwargs["islr_receipt_number"], "CTRL-9")


# --------------------------------------------------------------------------- #
# create_sales_taxes_row
# --------------------------------------------------------------------------- #
class TestCreateSalesTaxesRow(FrappeTestCase):

    def test_row_is_deduct_withholding(self):
        inv = _invoice(taxes=[object(), object()])  # 2 filas previas → idx 3
        row = _FakeTaxRow()
        with patch("frappe.new_doc", return_value=row):
            out = si.create_sales_taxes_row(
                inv, "VAT Withholding", "2408 - IVA Ret - TC", "VAT", 10.0, 400.0, 75.0
            )
        self.assertIs(out, row)
        self.assertTrue(row.inserted)
        self.assertEqual(row.charge_type, "VAT Withholding")
        self.assertEqual(row.add_deduct_tax, "Deduct")
        self.assertEqual(row.category, "Total")
        self.assertEqual(row.is_tax_withholding_account, 1)
        self.assertEqual(row.dont_recompute_tax, 1)
        self.assertEqual(row.tax_amount, 10.0)
        self.assertEqual(row.base_tax_amount, 400.0)
        self.assertEqual(row.idx, 3)


# --------------------------------------------------------------------------- #
# create_withholding_journal_entry
# --------------------------------------------------------------------------- #
class TestWithholdingJournalEntry(FrappeTestCase):

    def _build(self, inv, amount, base_amount, conversion_rate=1.0,
               company_currency="VEF", invoice_currency="VEF", acct_currency="VEF"):
        je = _FakeJournalEntry()
        with patch.object(si, "_require_withholding_permissions"), \
                patch("frappe.new_doc", return_value=je), \
                patch("frappe.db.get_value", return_value=acct_currency):
            si.create_withholding_journal_entry(
                inv, "VAT", "2408 - IVA Retenido - TC",
                amount, base_amount, conversion_rate,
                "2026-07-15", company_currency, invoice_currency,
            )
        return je

    def test_same_currency_partial_credits_invoice_only(self):
        inv = _invoice(outstanding_amount=1000.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)
        self.assertEqual(len(je.accounts), 2)
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 300.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 300.0, places=2)
        rec = [r for r in je.accounts if r.get("party")]
        self.assertEqual(rec[0].get("reference_name"), inv.name)

    def test_fully_paid_creates_formal_advance(self):
        """Factura pagada → anticipo con is_advance='Yes' (corrección review)."""
        inv = _invoice(outstanding_amount=0.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)
        self.assertEqual(len(je.accounts), 2)
        advance = [r for r in je.accounts if r.get("party") and not r.get("reference_name")]
        self.assertEqual(len(advance), 1)
        self.assertEqual(advance[0].get("is_advance"), "Yes")
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 300.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 300.0, places=2)

    def test_overpayment_splits_invoice_and_formal_advance(self):
        inv = _invoice(outstanding_amount=100.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)
        self.assertEqual(len(je.accounts), 3)
        referenced = [r for r in je.accounts if r.get("reference_name")]
        advance = [r for r in je.accounts if r.get("party") and not r.get("reference_name")]
        self.assertAlmostEqual(referenced[0]["credit"], 100.0, places=2)
        self.assertAlmostEqual(advance[0]["credit"], 200.0, places=2)
        self.assertEqual(advance[0].get("is_advance"), "Yes")

    def test_usd_invoice_company_legs_balance(self):
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=1000.0)
        je = self._build(
            inv, amount=10.0, base_amount=400.0, conversion_rate=40.0,
            company_currency="VEF", invoice_currency="USD", acct_currency="USD",
        )
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 400.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 400.0, places=2)

    def test_usd_outstanding_converted_no_spurious_advance(self):
        """El saldo USD se convierte a Bs antes de comparar: no hay anticipo espurio."""
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=100.0)
        je = self._build(
            inv, amount=10.0, base_amount=400.0, conversion_rate=40.0,
            company_currency="VEF", invoice_currency="USD", acct_currency="USD",
        )
        advance = [r for r in je.accounts if r.get("party") and not r.get("reference_name")]
        self.assertEqual(len(advance), 0, "El saldo USD debe convertirse a Bs; no debe haber anticipo espurio.")


# --------------------------------------------------------------------------- #
# fix_missing_withholding (orquestación)
# --------------------------------------------------------------------------- #
class TestFixMissingWithholding(FrappeTestCase):

    def test_foreign_currency_converts_bs_base_to_invoice_amount(self):
        """base_amount server-side (400 Bs) con tasa 40 → 10 USD en la fila de impuesto."""
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=1000.0)
        inv.precision = lambda *a, **k: 2
        inv.reload = lambda: None
        captured = {}

        def _fake_tax_row(invoice, charge_type, tax_account, wtype, amount, base_amount, rate):
            captured["amount"] = amount
            captured["base_amount"] = base_amount
            return _FakeTaxRow()

        with patch.object(si, "_require_withholding_permissions"), \
                patch.object(si, "get_verified_invoice", return_value=inv), \
                patch.object(si, "validate_withholding_tax_account"), \
                patch.object(si, "handle_voucher_metadata", return_value={"status": "proceed"}), \
                patch.object(si, "calculate_withholding_base_amount", return_value=400.0), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch.object(si, "create_sales_taxes_row", side_effect=_fake_tax_row), \
                patch.object(si, "create_withholding_journal_entry", return_value=_FakeJournalEntry()), \
                patch.object(si, "sync_isp_payment_amounts_if_installed"), \
                patch("frappe.db.set_value"), \
                patch("frappe.get_doc", return_value=MagicMock()):
            out = si.fix_missing_withholding(
                invoice_name="ACC-SINV-TEST-0001",
                withholding_type="VAT",
                tax_account="2408 - IVA Ret - TC",
                company="Test Company",
            )
        self.assertEqual(out["status"], "success")
        self.assertAlmostEqual(captured["amount"], 10.0, places=2)
        self.assertAlmostEqual(captured["base_amount"], 400.0, places=2)

    def test_duplicate_withholding_raises(self):
        existing = frappe._dict(charge_type="VAT Withholding", account_head="2408 - IVA Ret - TC")
        inv = _invoice(taxes=[existing])
        with patch.object(si, "_require_withholding_permissions"), \
                patch.object(si, "get_verified_invoice", return_value=inv), \
                patch.object(si, "validate_withholding_tax_account"), \
                patch.object(si, "handle_voucher_metadata", return_value={"status": "proceed"}), \
                patch("frappe.get_cached_value", return_value="VEF"):
            with self.assertRaises(frappe.ValidationError):
                si.fix_missing_withholding(
                    invoice_name="x", withholding_type="VAT",
                    tax_account="2408 - IVA Ret - TC", company="Test Company",
                )
