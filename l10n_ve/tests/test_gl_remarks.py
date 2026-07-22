# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la venezolanización de las descripciones (remarks) del Mayor.

Cubre los builders por documento (Sales Invoice, Purchase Invoice, Payment
Entry) y el despachador del hook regional update_gl_dict_with_regional_fields:
inyección del remark en gl_dict, cacheo por documento, respeto de la nota
manual y no-op para tipos no soportados.

fmt_money/formatdate se mockean para que las aserciones no dependan del
formato de número/fecha del site.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.overrides import gl_remarks


def _doc(**kwargs):
    """Doc falso con .get() y .flags (como un documento Frappe real)."""
    kwargs.setdefault("flags", frappe._dict())
    return frappe._dict(kwargs)


@patch.object(gl_remarks, "formatdate", lambda value, fmt=None: str(value))
@patch.object(gl_remarks, "fmt_money", lambda amount, currency=None: f"{currency} {float(amount):.2f}")
class TestGLRemarksVE(unittest.TestCase):
    # --- Sales Invoice ---------------------------------------------------

    def test_sales_invoice_basic(self):
        doc = _doc(
            doctype="Sales Invoice", customer="CUST-1", customer_name="ACME C.A.",
            tax_id="J-12345678-9", bill_no="00012345", bill_control="00067890",
            grand_total=1000, currency="VEF", is_return=0, remarks="",
        )
        result = gl_remarks._sales_invoice_remarks(doc)
        self.assertIn("Venta a ACME C.A. (RIF J-12345678-9)", result)
        self.assertIn("Doc. fiscal 00012345, control 00067890", result)
        self.assertIn("por VEF 1000.00", result)

    def test_sales_invoice_ignores_system_remarks(self):
        # En SI, remarks lo usa TFHKA (JSON), no es nota de usuario: se venezolaniza igual.
        doc = _doc(
            doctype="Sales Invoice", customer_name="ACME", tax_id="J-1",
            grand_total=10, currency="VEF", is_return=0,
            remarks='{"resultado": {"serie": "ARA-02"}}',
        )
        result = gl_remarks._sales_invoice_remarks(doc)
        self.assertTrue(result.startswith("Venta a ACME"))

    def test_sales_invoice_return(self):
        doc = _doc(
            doctype="Sales Invoice", customer_name="ACME", tax_id="J-1",
            grand_total=50, currency="USD", is_return=1, remarks="",
        )
        result = gl_remarks._sales_invoice_remarks(doc)
        self.assertTrue(result.startswith("Devolución en venta a ACME (RIF J-1)"))

    def test_sales_invoice_without_fiscal_numbers(self):
        doc = _doc(
            doctype="Sales Invoice", customer_name="ACME", grand_total=10,
            currency="VEF", is_return=0, remarks="",
        )
        result = gl_remarks._sales_invoice_remarks(doc)
        self.assertIn("Venta a ACME", result)
        self.assertNotIn("Doc. fiscal", result)
        self.assertNotIn("control", result)

    # --- Purchase Invoice ------------------------------------------------

    def test_purchase_invoice_basic(self):
        doc = _doc(
            doctype="Purchase Invoice", supplier="SUP-1", supplier_name="Proveedora S.A.",
            tax_id="J-99", bill_no="A-500", bill_control="C-77",
            grand_total=2500, currency="VEF", is_return=0, remarks="",
        )
        result = gl_remarks._purchase_invoice_remarks(doc)
        self.assertIn("Compra a Proveedora S.A. (RIF J-99)", result)
        self.assertIn("Factura A-500, control C-77", result)
        self.assertIn("por VEF 2500.00", result)

    def test_purchase_invoice_ignores_system_remarks(self):
        # En PI, remarks es el auto-string "Against Supplier Invoice ..." del core.
        doc = _doc(
            doctype="Purchase Invoice", supplier_name="Prov", tax_id="J-9",
            grand_total=20, currency="VEF", is_return=0,
            remarks="Against Supplier Invoice A-500",
        )
        result = gl_remarks._purchase_invoice_remarks(doc)
        self.assertTrue(result.startswith("Compra a Prov"))

    # --- Payment Entry ---------------------------------------------------

    def test_payment_entry_receive(self):
        doc = _doc(
            doctype="Payment Entry", payment_type="Receive", party="CUST-1",
            party_name="Cliente Uno", paid_amount=300, paid_from_account_currency="VEF",
            mode_of_payment="Transferencia", reference_no="0011", reference_date="2026-07-01",
            custom_remarks=0,
        )
        result = gl_remarks._payment_entry_remarks(doc)
        self.assertIn("Cobro a Cliente Uno", result)
        self.assertIn("por VEF 300.00", result)
        self.assertIn("vía Transferencia", result)
        self.assertIn("Ref. 0011 del 2026-07-01", result)

    def test_payment_entry_pay_uses_received_amount_and_payable_currency(self):
        doc = _doc(
            doctype="Payment Entry", payment_type="Pay", party_name="Proveedor Dos",
            paid_amount=999, received_amount=100, paid_to_account_currency="USD",
            custom_remarks=0,
        )
        result = gl_remarks._payment_entry_remarks(doc)
        self.assertIn("Pago a Proveedor Dos", result)
        self.assertIn("por USD 100.00", result)
        self.assertNotIn("999", result)

    def test_payment_entry_internal_transfer(self):
        doc = _doc(
            doctype="Payment Entry", payment_type="Internal Transfer",
            paid_amount=1000, paid_from_account_currency="VEF",
            paid_from="Banco A", paid_to="Banco B", custom_remarks=0,
        )
        result = gl_remarks._payment_entry_remarks(doc)
        self.assertIn("Transferencia interna de Banco A a Banco B", result)
        self.assertIn("por VEF 1000.00", result)

    def test_payment_entry_custom_remarks_is_respected(self):
        doc = _doc(doctype="Payment Entry", payment_type="Receive", custom_remarks=1)
        self.assertIsNone(gl_remarks._payment_entry_remarks(doc))

    # --- Notas fiscales VE -----------------------------------------------

    def test_ve_sales_credit_note(self):
        doc = _doc(
            doctype="VE Sales Credit Note", customer_name="ACME", tax_id="J-1",
            bill_no="NC-001", bill_control="C-1", grand_total=80, currency="VEF",
            return_against="ACC-SINV-2026-00009",
        )
        result = gl_remarks.build_remarks_for("VE Sales Credit Note", doc)
        self.assertTrue(result.startswith("Nota de crédito de venta a ACME (RIF J-1)"))
        self.assertIn("Doc. fiscal NC-001, control C-1", result)
        self.assertIn("afecta ACC-SINV-2026-00009", result)

    def test_ve_sales_debit_note(self):
        doc = _doc(doctype="VE Sales Debit Note", customer_name="ACME", grand_total=5, currency="VEF")
        result = gl_remarks.build_remarks_for("VE Sales Debit Note", doc)
        self.assertTrue(result.startswith("Nota de débito de venta a ACME"))

    def test_ve_purchase_credit_note(self):
        doc = _doc(
            doctype="VE Purchase Credit Note", supplier_name="Prov", tax_id="J-9",
            grand_total=40, currency="VEF",
        )
        result = gl_remarks.build_remarks_for("VE Purchase Credit Note", doc)
        self.assertTrue(result.startswith("Nota de crédito de compra a Prov (RIF J-9)"))

    def test_ve_purchase_debit_note(self):
        doc = _doc(doctype="VE Purchase Debit Note", supplier_name="Prov", grand_total=7, currency="VEF")
        result = gl_remarks.build_remarks_for("VE Purchase Debit Note", doc)
        self.assertTrue(result.startswith("Nota de débito de compra a Prov"))

    # --- refresh_gl_remarks (post-certificación HKA) ---------------------

    def test_refresh_gl_remarks_builds_and_updates(self):
        from unittest.mock import MagicMock

        row = frappe._dict(
            customer_name="ACME", tax_id="J-1", bill_no="F-9", bill_control="C-9",
            grand_total=10, currency="VEF", is_return=0,
        )
        captured = {}
        fake_db = MagicMock()
        fake_db.get_value.return_value = row
        fake_db.sql.side_effect = lambda query, params: captured.update(query=query, params=params)

        with patch.object(gl_remarks, "frappe") as fake_frappe:
            fake_frappe.db = fake_db
            gl_remarks.refresh_gl_remarks("Sales Invoice", "ACC-SINV-2026-00001")

        self.assertTrue(fake_db.get_value.called)
        self.assertIn("UPDATE `tabGL Entry`", captured["query"])
        self.assertIn("is_cancelled = 0", captured["query"])
        # el remark calculado es el primer y el último parámetro
        self.assertTrue(captured["params"][0].startswith("Venta a ACME"))
        self.assertEqual(captured["params"][-1], captured["params"][0])

    def test_refresh_gl_remarks_skips_unsupported_doctype(self):
        from unittest.mock import MagicMock

        fake_db = MagicMock()
        with patch.object(gl_remarks, "frappe") as fake_frappe:
            fake_frappe.db = fake_db
            gl_remarks.refresh_gl_remarks("Journal Entry", "ACC-JV-1")
        self.assertFalse(fake_db.get_value.called)
        self.assertFalse(fake_db.sql.called)

    # --- Despachador (hook regional) -------------------------------------

    def test_dispatcher_sets_remarks_on_gl_dict(self):
        doc = _doc(
            doctype="Sales Invoice", customer_name="ACME", tax_id="J-1",
            grand_total=10, currency="VEF", is_return=0, remarks="",
        )
        gl_dict = frappe._dict()
        gl_remarks.update_gl_dict_with_regional_fields(doc, gl_dict)
        self.assertTrue(gl_dict["remarks"].startswith("Venta a ACME"))
        self.assertEqual(doc.flags._ve_gl_remarks, gl_dict["remarks"])

    def test_dispatcher_caches_per_document(self):
        doc = _doc(
            doctype="Sales Invoice", customer_name="ACME", grand_total=10,
            currency="VEF", is_return=0, remarks="",
        )
        first = frappe._dict()
        gl_remarks.update_gl_dict_with_regional_fields(doc, first)

        # Cambiar el doc no debe recomputar: el hook usa el valor cacheado.
        doc.customer_name = "OTRO"
        second = frappe._dict()
        gl_remarks.update_gl_dict_with_regional_fields(doc, second)
        self.assertEqual(second["remarks"], first["remarks"])
        self.assertIn("ACME", second["remarks"])

    def test_dispatcher_respects_payment_entry_custom_remarks(self):
        # custom_remarks=1: el usuario redactó su nota; no se pisa.
        doc = _doc(doctype="Payment Entry", payment_type="Receive", custom_remarks=1)
        gl_dict = frappe._dict(remarks="Nota manual del usuario")
        gl_remarks.update_gl_dict_with_regional_fields(doc, gl_dict)
        self.assertEqual(gl_dict["remarks"], "Nota manual del usuario")

    def test_dispatcher_noop_for_unsupported_doctype(self):
        doc = _doc(doctype="Journal Entry")
        gl_dict = frappe._dict(remarks="original")
        gl_remarks.update_gl_dict_with_regional_fields(doc, gl_dict)
        self.assertEqual(gl_dict["remarks"], "original")

    def test_dispatcher_handles_ve_note(self):
        doc = _doc(
            doctype="VE Sales Credit Note", customer_name="ACME", tax_id="J-1",
            grand_total=5, currency="VEF", return_against="ACC-SINV-9",
        )
        gl_dict = frappe._dict()
        gl_remarks.update_gl_dict_with_regional_fields(doc, gl_dict)
        self.assertTrue(gl_dict["remarks"].startswith("Nota de crédito de venta a ACME"))
        self.assertIn("afecta ACC-SINV-9", gl_dict["remarks"])


if __name__ == "__main__":
    unittest.main()
