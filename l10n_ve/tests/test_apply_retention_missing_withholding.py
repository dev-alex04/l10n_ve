# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la aplicación retroactiva de retenciones IVA/ISLR sobre facturas ya
aprobadas (``l10n_ve.overrides.sales_invoice``).

Cubre la lógica determinista del endpoint ``fix_missing_withholding`` y sus
ayudantes:

- ``get_verified_invoice``: resolución por name / bill_no y validación de docstatus.
- ``handle_voucher_metadata``: campos incompletos, ask_overwrite, only_line, alta.
- ``create_sales_taxes_row``: fila "Deduct" de retención bien formada.
- ``create_withholding_journal_entry``: cuadre del asiento y ramas
  pagada / parcial / sobrepago (misma moneda) + multimoneda USD.
- ``fix_missing_withholding``: conversión Bs→moneda de factura, monto no positivo,
  y guardia de duplicados.

Son tests unitarios con mocks: NO tocan la base de datos (se parchean
``frappe.new_doc`` / ``frappe.db.*`` / los ayudantes), de modo que validan la
aritmética y el flujo sin depender de datos del sitio. Requieren un sitio solo
porque ``FrappeTestCase`` abre una transacción; ninguna aserción lee de la BD.

NOTA: ``_require_isp_finance_role`` se prueba solo en su forma estable (denegar a
un usuario sin roles); la lista concreta de roles ISP está señalada en el review
como acople a corregir (l10n_ve → domina_isp), así que no se fija aquí.
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
    """Factura mínima (frappe._dict) con los atributos que leen las funciones."""
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
# create_withholding_journal_entry
# --------------------------------------------------------------------------- #
class TestWithholdingJournalEntry(FrappeTestCase):
    """Cuadre del asiento y ramas de imputación pagada / parcial / sobrepago."""

    def _build(self, inv, amount, base_amount, conversion_rate=1.0,
               company_currency="VEF", invoice_currency="VEF", acct_currency="VEF"):
        je = _FakeJournalEntry()
        with patch("frappe.new_doc", return_value=je), \
                patch("frappe.db.get_value", return_value=acct_currency):
            si.create_withholding_journal_entry(
                inv, "VAT", "2408 - IVA Retenido - TC",
                amount, base_amount, conversion_rate,
                "2026-07-15", company_currency, invoice_currency,
            )
        return je

    def test_same_currency_partial_credits_invoice_only(self):
        """Saldo pendiente > retención → todo el crédito referencia la factura."""
        inv = _invoice(outstanding_amount=1000.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)

        self.assertEqual(len(je.accounts), 2)
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 300.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 300.0, places=2)
        rec = [r for r in je.accounts if r.get("party")]
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0].get("reference_name"), inv.name)

    def test_fully_paid_routes_to_unreferenced_advance(self):
        """Factura pagada → el crédito va a un anticipo SIN referencia a la factura."""
        inv = _invoice(outstanding_amount=0.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)

        self.assertEqual(len(je.accounts), 2)
        rec = [r for r in je.accounts if r.get("party")]
        self.assertEqual(len(rec), 1)
        # Documenta el comportamiento del review #4: el saldo a favor no ata la
        # factura (ni marca is_advance). El equipo contable confirmó que la
        # factura pagada debe quedar como saldo a favor, pero la traza correcta
        # exige referencia/anticipo formal.
        self.assertIsNone(rec[0].get("reference_name"))
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 300.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 300.0, places=2)

    def test_overpayment_splits_invoice_and_advance(self):
        """Retención > saldo → parte imputada a la factura + resto a anticipo."""
        inv = _invoice(outstanding_amount=100.0)
        je = self._build(inv, amount=300.0, base_amount=300.0)

        self.assertEqual(len(je.accounts), 3)
        referenced = [r for r in je.accounts if r.get("reference_name")]
        advance = [r for r in je.accounts if r.get("party") and not r.get("reference_name")]
        self.assertEqual(len(referenced), 1)
        self.assertEqual(len(advance), 1)
        self.assertAlmostEqual(referenced[0]["credit"], 100.0, places=2)
        self.assertAlmostEqual(advance[0]["credit"], 200.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 300.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 300.0, places=2)

    def test_usd_invoice_company_legs_balance(self):
        """Factura USD: en moneda de compañía (Bs) el asiento siempre cuadra."""
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=1000.0)
        je = self._build(
            inv, amount=10.0, base_amount=400.0, conversion_rate=40.0,
            company_currency="VEF", invoice_currency="USD", acct_currency="USD",
        )
        self.assertAlmostEqual(_sum(je.accounts, "debit"), 400.0, places=2)
        self.assertAlmostEqual(_sum(je.accounts, "credit"), 400.0, places=2)
        # La pata de impuesto lleva el importe en moneda de cuenta (USD) y el Bs.
        tax_row = je.accounts[0]
        self.assertAlmostEqual(tax_row["debit_in_account_currency"], 10.0, places=2)
        self.assertAlmostEqual(tax_row["debit"], 400.0, places=2)

    def test_usd_outstanding_is_mistaken_for_bs_bug_ref_12(self):
        """DOCUMENTA EL BUG #12 del review.

        ``outstanding_amount`` de una factura USD está en USD, pero
        ``create_withholding_journal_entry`` lo compara contra el crédito en Bs.

        Escenario: factura USD, tasa 40 Bs/USD, retención 400 Bs (= 10 USD),
        saldo pendiente = 100 USD. Como 10 USD < 100 USD, la retención debería
        imputarse ÍNTEGRA a la factura y NO generar saldo a favor.

        El código, en cambio, trata ``outstanding = 100`` como 100 Bs y, al ser
        400 Bs > 100, parte el crédito y crea un anticipo espurio de 300 Bs.

        Cuando se corrija #12 (comparar el saldo en moneda de cuenta), este test
        fallará: actualícelo a "sin fila de anticipo".
        """
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=100.0)
        je = self._build(
            inv, amount=10.0, base_amount=400.0, conversion_rate=40.0,
            company_currency="VEF", invoice_currency="USD", acct_currency="USD",
        )
        advance = [r for r in je.accounts if r.get("party") and not r.get("reference_name")]
        self.assertEqual(
            len(advance), 1,
            "Si #12 fue corregido no debería haber anticipo espurio; actualice el test.",
        )
        self.assertAlmostEqual(advance[0]["credit"], 300.0, places=2)


# --------------------------------------------------------------------------- #
# get_verified_invoice
# --------------------------------------------------------------------------- #
class TestGetVerifiedInvoice(FrappeTestCase):

    def test_resolves_by_name(self):
        inv = _invoice(name="ACC-SINV-1")
        with patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_doc", return_value=inv) as gd:
            out = si.get_verified_invoice("ACC-SINV-1")
        self.assertIs(out, inv)
        gd.assert_called_once_with("Sales Invoice", "ACC-SINV-1")

    def test_resolves_by_bill_no_fallback(self):
        inv = _invoice(name="ACC-SINV-2")
        with patch("frappe.db.exists", return_value=False), \
                patch("frappe.db.get_value", return_value="ACC-SINV-2"), \
                patch("frappe.get_doc", return_value=inv) as gd:
            si.get_verified_invoice("00012345")
        gd.assert_called_once_with("Sales Invoice", "ACC-SINV-2")

    def test_not_found_raises(self):
        with patch("frappe.db.exists", return_value=False), \
                patch("frappe.db.get_value", return_value=None):
            with self.assertRaises(frappe.ValidationError):
                si.get_verified_invoice("does-not-exist")

    def test_draft_invoice_raises(self):
        inv = _invoice(name="ACC-SINV-3", docstatus=0)
        with patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_doc", return_value=inv):
            with self.assertRaises(frappe.ValidationError):
                si.get_verified_invoice("ACC-SINV-3")


# --------------------------------------------------------------------------- #
# handle_voucher_metadata
# --------------------------------------------------------------------------- #
class TestHandleVoucherMetadata(FrappeTestCase):

    def test_incomplete_fields_raise(self):
        """Algún campo del comprobante presente pero no todos → error."""
        inv = _invoice()
        with self.assertRaises(frappe.ValidationError):
            si.handle_voucher_metadata(
                inv, "VAT", "12345678901234", None, None, False, False
            )

    def test_vat_existing_asks_overwrite(self):
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        res = si.handle_voucher_metadata(
            inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", False, False
        )
        self.assertEqual(res["status"], "ask_overwrite")

    def test_vat_overwrite_updates_real_date_field(self):
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        with patch.object(si, "update_invoice_metadata") as upd:
            res = si.handle_voucher_metadata(
                inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", True, False
            )
        self.assertEqual(res["status"], "proceed")
        upd.assert_called_once()
        data = upd.call_args[0][1]
        self.assertEqual(data["vat_withholding_voucher_number"], "12345678901234")
        # Campo real de fecha IVA: withholding_date (no vat_withholding_date).
        self.assertEqual(data["withholding_date"], "2026-07-15")
        self.assertEqual(data["voucher_image"], "/files/x.pdf")

    def test_only_line_keeps_existing_metadata(self):
        """only_line=True con comprobante existente → ni pregunta ni actualiza."""
        inv = _invoice(vat_withholding_voucher_number="OLD-123")
        with patch.object(si, "update_invoice_metadata") as upd:
            res = si.handle_voucher_metadata(
                inv, "VAT", "12345678901234", "2026-07-15", "/files/x.pdf", False, True
            )
        self.assertEqual(res["status"], "proceed")
        upd.assert_not_called()

    def test_islr_new_voucher_updates_islr_date_field(self):
        inv = _invoice()
        with patch.object(si, "update_invoice_metadata") as upd:
            res = si.handle_voucher_metadata(
                inv, "ISLR", "CTRL-9", "2026-07-15", "/files/i.pdf", False, False
            )
        self.assertEqual(res["status"], "proceed")
        data = upd.call_args[0][1]
        # Campo real de fecha ISLR: islr_date (no islr_withholding_date).
        self.assertIn("islr_date", data)
        self.assertEqual(data["islr_receipt_number"], "CTRL-9")
        self.assertEqual(data["voucher_image_islr"], "/files/i.pdf")


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
        self.assertEqual(row.account_head, "2408 - IVA Ret - TC")


# --------------------------------------------------------------------------- #
# fix_missing_withholding (orquestación)
# --------------------------------------------------------------------------- #
class TestFixMissingWithholding(FrappeTestCase):

    def test_foreign_currency_converts_bs_base_to_invoice_amount(self):
        """400 Bs con tasa 40 → 10 USD en la fila de impuesto (base sigue en Bs)."""
        inv = _invoice(currency="USD", conversion_rate=40.0, outstanding_amount=1000.0)
        inv.precision = lambda *a, **k: 2
        inv.reload = lambda: None
        captured = {}

        def _fake_tax_row(invoice, charge_type, tax_account, wtype, amount, base_amount, rate):
            captured["amount"] = amount
            captured["base_amount"] = base_amount
            return _FakeTaxRow()

        with patch.object(si, "_require_isp_finance_role"), \
                patch.object(si, "get_verified_invoice", return_value=inv), \
                patch.object(si, "handle_voucher_metadata", return_value={"status": "proceed"}), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch.object(si, "create_sales_taxes_row", side_effect=_fake_tax_row), \
                patch.object(si, "create_withholding_journal_entry", return_value=_FakeJournalEntry()), \
                patch("frappe.db.set_value"), \
                patch("frappe.get_doc", return_value=MagicMock()), \
                patch("frappe.log_error"):
            out = si.fix_missing_withholding(
                invoice_name="ACC-SINV-TEST-0001",
                withholding_type="VAT",
                tax_account="2408 - IVA Ret - TC",
                amount=400.0,  # Bs
            )
        self.assertEqual(out["status"], "success")
        self.assertAlmostEqual(captured["amount"], 10.0, places=2)
        self.assertAlmostEqual(captured["base_amount"], 400.0, places=2)

    def test_non_positive_amount_raises(self):
        inv = _invoice()
        with patch.object(si, "_require_isp_finance_role"), \
                patch.object(si, "get_verified_invoice", return_value=inv):
            with self.assertRaises(frappe.ValidationError):
                si.fix_missing_withholding(
                    invoice_name="x", withholding_type="VAT", tax_account="acc", amount=0
                )

    def test_duplicate_withholding_raises(self):
        existing = frappe._dict(charge_type="VAT Withholding", account_head="2408 - IVA Ret - TC")
        inv = _invoice(taxes=[existing])
        with patch.object(si, "_require_isp_finance_role"), \
                patch.object(si, "get_verified_invoice", return_value=inv), \
                patch.object(si, "handle_voucher_metadata", return_value={"status": "proceed"}):
            with self.assertRaises(frappe.ValidationError):
                si.fix_missing_withholding(
                    invoice_name="x", withholding_type="VAT",
                    tax_account="2408 - IVA Ret - TC", amount=400.0,
                )


# --------------------------------------------------------------------------- #
# _require_isp_finance_role (forma estable)
# --------------------------------------------------------------------------- #
class TestRequireFinanceRole(FrappeTestCase):

    def test_user_without_authorized_role_denied(self):
        with patch("frappe.get_roles", return_value=["Guest"]):
            with self.assertRaises(frappe.PermissionError):
                si._require_isp_finance_role()
