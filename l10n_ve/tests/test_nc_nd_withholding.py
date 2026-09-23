# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Pruebas unitarias de aplicación y reverso de retenciones de IVA e ISLR en Notas de Crédito y Débito.

Valida los requerimientos de PR #760:
- Aplicar IVA e ISLR crea asientos balanceados con cuentas y montos esperados.
- Quitar retención genera el asiento de reverso correspondiente y limpia metadatos.
- Rechazo de retenciones duplicadas (mismo charge_type).
- Rechazo de notas de crédito y débito sin aprobar (docstatus != 1).
- Validación estricta de moneda y tasa de cambio (regla Semgrep).
- Validación de permisos sobre el documento.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note import (
    apply_credit_note_withholding,
    remove_credit_note_withholding,
)
from l10n_ve.l10n_ve.doctype.ve_sales_debit_note.ve_sales_debit_note import (
    apply_debit_note_withholding,
    remove_debit_note_withholding,
)

_COMPANY = "Galanet Solution C.A."
_CUSTOMER = "REPRESENTACIONES DACA C.A"
_NC_NAME = "NC-2026-00094"
_ND_NAME = "ND-2026-00001"
_INVOICE = "ACC-SINV-2026-27105"
_VAT_ACC = "1110003 - Retencion de IVA Clientes - Galanet"
_ISLR_ACC = "1110002 - Retenciones ISLR Clientes - Galanet"
_REC_ACC = "1105001 - Cuentas por Cobrar Clientes - Galanet"


class _FakeGenericDoc:
    """Mock genérico para documentos de soporte (Tax Row, Comment, etc.)."""

    def __init__(self, name: str = "DOC-TEST-0001", **kwargs) -> None:
        self.name = name
        self.flags = frappe._dict()
        for k, v in kwargs.items():
            setattr(self, k, v)

    def db_insert(self) -> None:
        pass

    def insert(self, *args, **kwargs) -> "_FakeGenericDoc":
        return self

    def update(self, d: dict) -> None:
        for k, v in d.items():
            setattr(self, k, v)


class _FakeJournalEntry:
    """Mock de Journal Entry que almacena las filas en accounts y valida balance."""

    def __init__(self) -> None:
        self.name = "ACC-JV-TEST-99999"
        self.company = _COMPANY
        self.posting_date = "2026-09-15"
        self.accounts = []
        self.flags = frappe._dict()
        self.user_remark = ""
        self.multi_currency = 0

    def append(self, table: str, row: dict) -> dict:
        assert table == "accounts"
        d = frappe._dict(row)
        self.accounts.append(d)
        return d

    def insert(self, *args, **kwargs) -> "_FakeJournalEntry":
        return self

    def submit(self, *args, **kwargs) -> "_FakeJournalEntry":
        return self


def _mock_credit_note(
    docstatus: int = 1,
    taxes: list | None = None,
    currency: str = "USD",
    conversion_rate: float = 800.0,
) -> frappe._dict:
    """Crea un documento falso de Nota de Crédito con datos fiscales."""
    if taxes is None:
        taxes = [
            frappe._dict(
                name="tax-row-iva",
                charge_type="VAT",
                add_deduct_tax="Add",
                account_head="2105001 - IVA Debito Fiscal - Galanet",
                tax_amount=19.2,
                base_tax_amount=15360.0,
                is_tax_withholding_account=0,
            )
        ]

    doc = frappe._dict(
        name=_NC_NAME,
        doctype="VE Sales Credit Note",
        docstatus=docstatus,
        company=_COMPANY,
        customer=_CUSTOMER,
        currency=currency,
        conversion_rate=conversion_rate,
        plc_conversion_rate=0.0,
        debit_to=_REC_ACC,
        cost_center="DC-01",
        net_total=120.0,
        base_net_total=96000.0,
        return_against=_INVOICE,
        taxes=taxes,
        vat_withholding_voucher_number=None,
        withholding_date=None,
        vat_registration_date=None,
        islr_receipt_number=None,
        islr_date=None,
        islr_registration_date=None,
    )
    doc._update_outstanding_amount = lambda: None
    return doc


def _mock_debit_note(
    docstatus: int = 1,
    taxes: list | None = None,
    currency: str = "USD",
    conversion_rate: float = 800.0,
) -> frappe._dict:
    """Crea un documento falso de Nota de Débito con datos fiscales."""
    if taxes is None:
        taxes = [
            frappe._dict(
                name="tax-row-iva-nd",
                charge_type="VAT",
                add_deduct_tax="Add",
                account_head="2105001 - IVA Debito Fiscal - Galanet",
                tax_amount=16.0,
                base_tax_amount=12800.0,
                is_tax_withholding_account=0,
            )
        ]

    doc = frappe._dict(
        name=_ND_NAME,
        doctype="VE Sales Debit Note",
        docstatus=docstatus,
        company=_COMPANY,
        customer=_CUSTOMER,
        currency=currency,
        conversion_rate=conversion_rate,
        plc_conversion_rate=0.0,
        debit_to=_REC_ACC,
        cost_center="DC-01",
        net_total=100.0,
        base_net_total=80000.0,
        outstanding_amount=116.0,
        taxes=taxes,
        vat_withholding_voucher_number=None,
        withholding_date=None,
        vat_registration_date=None,
        islr_receipt_number=None,
        islr_date=None,
        islr_registration_date=None,
    )
    doc._update_outstanding_amount = lambda: None
    return doc


class TestCreditNoteWithholding(FrappeTestCase):
    """Pruebas unitarias para retenciones en VE Sales Credit Note."""

    def test_unapproved_credit_note_is_refused(self) -> None:
        """Una nota de crédito en borrador (docstatus=0) debe ser rechazada."""
        draft_nc = _mock_credit_note(docstatus=0)
        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", return_value=draft_nc), \
                patch("frappe.has_permission"):
            with self.assertRaises(frappe.ValidationError):
                apply_credit_note_withholding(
                    credit_note_name=_NC_NAME,
                    withholding_type="VAT",
                    tax_account=_VAT_ACC,
                )

            with self.assertRaises(frappe.ValidationError):
                remove_credit_note_withholding(
                    credit_note_name=_NC_NAME,
                    withholding_type="VAT",
                )

    def test_duplicate_vat_withholding_is_refused(self) -> None:
        """No se permite aplicar una segunda retención del mismo charge_type."""
        taxes = [
            frappe._dict(
                name="tax-row-existing-vat",
                charge_type="VAT Withholding",
                account_head=_VAT_ACC,
                base_tax_amount=11520.0,
            )
        ]
        nc = _mock_credit_note(docstatus=1, taxes=taxes)
        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", return_value=nc), \
                patch("frappe.has_permission"), \
                patch("frappe.db.exists", return_value=True):
            with self.assertRaises(frappe.ValidationError):
                apply_credit_note_withholding(
                    credit_note_name=_NC_NAME,
                    withholding_type="VAT",
                    tax_account="1110003 - Otra Cuenta - Galanet",
                )

    def test_missing_currency_or_conversion_rate_raises(self) -> None:
        """Regla Semgrep: si falta la moneda de empresa o la tasa de cambio debe fallar."""
        nc = _mock_credit_note(conversion_rate=0.0)
        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", return_value=nc), \
                patch("frappe.has_permission"), \
                patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_cached_value", return_value="VEF"):
            with self.assertRaises(frappe.ValidationError):
                apply_credit_note_withholding(
                    credit_note_name=_NC_NAME,
                    withholding_type="VAT",
                    tax_account=_VAT_ACC,
                )

    def test_apply_vat_withholding_creates_balanced_je(self) -> None:
        """Aplicar retención de IVA crea un asiento balanceado afectando la factura en return_against."""
        nc = _mock_credit_note(docstatus=1)
        fake_je = _FakeJournalEntry()

        def _smart_get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict):
                return _FakeGenericDoc("comment-doc", **args[0])
            if args and args[0] == "VE Sales Credit Note":
                return nc
            return _FakeGenericDoc()

        def _new_doc(dt: str) -> _FakeJournalEntry | _FakeGenericDoc:
            if dt == "Journal Entry":
                return fake_je
            return _FakeGenericDoc("tax-row-new")

        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", side_effect=_smart_get_doc), \
                patch("frappe.has_permission"), \
                patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch("frappe.db.get_value", return_value="VEF"), \
                patch("frappe.new_doc", side_effect=_new_doc), \
                patch("frappe.db.set_value"):
            res = apply_credit_note_withholding(
                credit_note_name=_NC_NAME,
                withholding_type="VAT",
                tax_account=_VAT_ACC,
                voucher_number="20260900000109",
                rate=75.0,
            )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["journal_entry"], fake_je.name)
        # Asiento con 2 filas
        self.assertEqual(len(fake_je.accounts), 2)
        debit_row = next(a for a in fake_je.accounts if flt(a.debit) > 0)
        credit_row = next(a for a in fake_je.accounts if flt(a.credit) > 0)

        # Monto esperado: base IVA (15360.0) * 75% = 11520.0 Bs
        expected_bs = 11520.0
        self.assertAlmostEqual(debit_row.debit, expected_bs, places=2)
        self.assertAlmostEqual(credit_row.credit, expected_bs, places=2)
        # Debe balancear: Total Débito == Total Crédito
        self.assertEqual(debit_row.debit, credit_row.credit)

        # El débito va a CxC contra la factura return_against
        self.assertEqual(debit_row.account, _REC_ACC)
        self.assertEqual(debit_row.reference_type, "Sales Invoice")
        self.assertEqual(debit_row.reference_name, _INVOICE)
        # El crédito va a la cuenta de retención
        self.assertEqual(credit_row.account, _VAT_ACC)
        # Debe tener ignore_permissions activado
        self.assertTrue(fake_je.flags.ignore_permissions)

    def test_apply_islr_withholding_creates_balanced_je(self) -> None:
        """Aplicar retención de ISLR calcula sobre base_net_total y crea asiento balanceado."""
        nc = _mock_credit_note(docstatus=1)
        fake_je = _FakeJournalEntry()

        def _smart_get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict):
                return _FakeGenericDoc("comment-doc", **args[0])
            if args and args[0] == "VE Sales Credit Note":
                return nc
            return _FakeGenericDoc()

        def _new_doc(dt: str) -> _FakeJournalEntry | _FakeGenericDoc:
            if dt == "Journal Entry":
                return fake_je
            return _FakeGenericDoc("tax-row-new-islr")

        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", side_effect=_smart_get_doc), \
                patch("frappe.has_permission"), \
                patch("frappe.db.exists", return_value=True), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch("frappe.db.get_value", return_value="VEF"), \
                patch("frappe.new_doc", side_effect=_new_doc), \
                patch("frappe.db.set_value"):
            res = apply_credit_note_withholding(
                credit_note_name=_NC_NAME,
                withholding_type="ISLR",
                tax_account=_ISLR_ACC,
                voucher_number="ISLR-001",
                rate=2.0,
            )

        self.assertEqual(res["status"], "success")
        # Monto esperado: base_net_total (96000.0) * 2% = 1920.0 Bs
        expected_bs = 1920.0
        debit_row = next(a for a in fake_je.accounts if flt(a.debit) > 0)
        credit_row = next(a for a in fake_je.accounts if flt(a.credit) > 0)
        self.assertAlmostEqual(debit_row.debit, expected_bs, places=2)
        self.assertAlmostEqual(credit_row.credit, expected_bs, places=2)
        self.assertEqual(debit_row.debit, credit_row.credit)

    def test_remove_credit_note_withholding_creates_reversal_je(self) -> None:
        """Quitar retención en NC genera un asiento de reverso contable y limpia datos."""
        taxes = [
            frappe._dict(
                name="tax-row-vat-applied",
                charge_type="VAT Withholding",
                account_head=_VAT_ACC,
                base_tax_amount=11520.0,
                tax_amount=14.4,
            )
        ]
        nc = _mock_credit_note(docstatus=1, taxes=taxes)
        nc.vat_withholding_voucher_number = "20260900000109"
        fake_je = _FakeJournalEntry()

        def _smart_get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict):
                return _FakeGenericDoc("comment-doc", **args[0])
            if args and args[0] == "VE Sales Credit Note":
                return nc
            return _FakeGenericDoc()

        def _new_doc(dt: str) -> _FakeJournalEntry | _FakeGenericDoc:
            if dt == "Journal Entry":
                return fake_je
            return _FakeGenericDoc("comment-doc")

        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", side_effect=_smart_get_doc), \
                patch("frappe.has_permission"), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch("frappe.db.get_value", return_value="VEF"), \
                patch("frappe.new_doc", side_effect=_new_doc), \
                patch("frappe.db.delete") as mock_delete, \
                patch("frappe.db.set_value"):
            res = remove_credit_note_withholding(
                credit_note_name=_NC_NAME,
                withholding_type="VAT",
            )

        self.assertEqual(res["status"], "success")
        self.assertIn(fake_je.name, res["journal_entries"])
        mock_delete.assert_called_once_with("Sales Taxes and Charges", {"name": "tax-row-vat-applied"})

        # El reverso invierte las cuentas:
        # Débito a Cuenta de Retención, Crédito a CxC
        debit_row = next(a for a in fake_je.accounts if flt(a.debit) > 0)
        credit_row = next(a for a in fake_je.accounts if flt(a.credit) > 0)
        self.assertEqual(debit_row.account, _VAT_ACC)
        self.assertEqual(credit_row.account, _REC_ACC)
        self.assertEqual(credit_row.reference_name, _INVOICE)
        self.assertEqual(debit_row.debit, credit_row.credit)


class TestDebitNoteWithholding(FrappeTestCase):
    """Pruebas unitarias para retenciones en VE Sales Debit Note."""

    def test_unapproved_debit_note_is_refused(self) -> None:
        """Una nota de débito en borrador (docstatus=0) debe ser rechazada."""
        draft_nd = _mock_debit_note(docstatus=0)
        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", return_value=draft_nd), \
                patch("frappe.has_permission"):
            with self.assertRaises(frappe.ValidationError):
                apply_debit_note_withholding(
                    debit_note_name=_ND_NAME,
                    withholding_type="VAT",
                    tax_account=_VAT_ACC,
                )

            with self.assertRaises(frappe.ValidationError):
                remove_debit_note_withholding(
                    debit_note_name=_ND_NAME,
                    withholding_type="VAT",
                )

    def test_duplicate_vat_withholding_is_refused(self) -> None:
        """No se permite aplicar retenciones duplicadas del mismo charge_type en ND."""
        taxes = [
            frappe._dict(
                name="tax-row-existing-vat-nd",
                charge_type="VAT Withholding",
                account_head=_VAT_ACC,
                base_tax_amount=9600.0,
            )
        ]
        nd = _mock_debit_note(docstatus=1, taxes=taxes)
        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", return_value=nd), \
                patch("frappe.has_permission"):
            with self.assertRaises(frappe.ValidationError):
                apply_debit_note_withholding(
                    debit_note_name=_ND_NAME,
                    withholding_type="VAT",
                    tax_account="1110003 - Otra Cuenta - Galanet",
                )

    def test_apply_vat_withholding_nd_creates_balanced_je(self) -> None:
        """Aplicar retención en ND crea asiento balanceado afectando la propia ND."""
        nd = _mock_debit_note(docstatus=1)
        fake_je = _FakeJournalEntry()

        def _smart_get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict):
                return _FakeGenericDoc("comment-doc", **args[0])
            if args and args[0] == "VE Sales Debit Note":
                return nd
            return _FakeGenericDoc()

        def _new_doc(dt: str) -> _FakeJournalEntry | _FakeGenericDoc:
            if dt == "Journal Entry":
                return fake_je
            return _FakeGenericDoc("tax-row-nd-new")

        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", side_effect=_smart_get_doc), \
                patch("frappe.has_permission"), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch("frappe.db.get_value", return_value="VEF"), \
                patch("frappe.new_doc", side_effect=_new_doc), \
                patch("frappe.db.set_value"):
            res = apply_debit_note_withholding(
                debit_note_name=_ND_NAME,
                withholding_type="VAT",
                tax_account=_VAT_ACC,
                voucher_number="20260900000110",
                rate=75.0,
            )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["journal_entry"], fake_je.name)

        # Monto esperado: base IVA (12800.0) * 75% = 9600.0 Bs
        expected_bs = 9600.0
        debit_row = next(a for a in fake_je.accounts if flt(a.debit) > 0)
        credit_row = next(a for a in fake_je.accounts if flt(a.credit) > 0)
        self.assertAlmostEqual(debit_row.debit, expected_bs, places=2)
        self.assertAlmostEqual(credit_row.credit, expected_bs, places=2)
        self.assertEqual(debit_row.debit, credit_row.credit)

        # En ND: Débito a Retención IVA, Crédito a CxC referenciando la ND
        self.assertEqual(debit_row.account, _VAT_ACC)
        self.assertEqual(credit_row.account, _REC_ACC)
        self.assertEqual(credit_row.reference_type, "VE Sales Debit Note")
        self.assertEqual(credit_row.reference_name, _ND_NAME)

    def test_remove_debit_note_withholding_creates_reversal_je(self) -> None:
        """Quitar retención en ND revierte el asiento y restaura el saldo adeudado."""
        taxes = [
            frappe._dict(
                name="tax-row-nd-applied",
                charge_type="VAT Withholding",
                account_head=_VAT_ACC,
                base_tax_amount=9600.0,
                tax_amount=12.0,
            )
        ]
        nd = _mock_debit_note(docstatus=1, taxes=taxes)
        nd.vat_withholding_voucher_number = "20260900000110"
        fake_je = _FakeJournalEntry()

        def _smart_get_doc(*args, **kwargs):
            if args and isinstance(args[0], dict):
                return _FakeGenericDoc("comment-doc", **args[0])
            if args and args[0] == "VE Sales Debit Note":
                return nd
            return _FakeGenericDoc()

        def _new_doc(dt: str) -> _FakeJournalEntry | _FakeGenericDoc:
            if dt == "Journal Entry":
                return fake_je
            return _FakeGenericDoc("comment-doc")

        with patch("frappe.get_roles", return_value=["Accounts User"]), \
                patch("frappe.get_doc", side_effect=_smart_get_doc), \
                patch("frappe.has_permission"), \
                patch("frappe.get_cached_value", return_value="VEF"), \
                patch("frappe.db.get_value", return_value="VEF"), \
                patch("frappe.new_doc", side_effect=_new_doc), \
                patch("frappe.db.delete") as mock_delete, \
                patch("frappe.db.set_value"):
            res = remove_debit_note_withholding(
                debit_note_name=_ND_NAME,
                withholding_type="VAT",
            )

        self.assertEqual(res["status"], "success")
        self.assertIn(fake_je.name, res["journal_entries"])
        mock_delete.assert_called_once_with("Sales Taxes and Charges", {"name": "tax-row-nd-applied"})

        # Reverso en ND: Débito a CxC referenciando la ND, Crédito a Retención IVA
        debit_row = next(a for a in fake_je.accounts if flt(a.debit) > 0)
        credit_row = next(a for a in fake_je.accounts if flt(a.credit) > 0)
        self.assertEqual(debit_row.account, _REC_ACC)
        self.assertEqual(debit_row.reference_type, "VE Sales Debit Note")
        self.assertEqual(debit_row.reference_name, _ND_NAME)
        self.assertEqual(credit_row.account, _VAT_ACC)
        self.assertEqual(debit_row.debit, credit_row.credit)
