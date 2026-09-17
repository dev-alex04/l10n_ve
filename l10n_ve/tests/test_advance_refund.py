# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Botón «Reembolsar»: el reembolso de un anticipo queda aplicado al anticipo.

Caso que lo motivó (producción, 07-09-2026): GRUPO VITALIS pagó en el portal la factura de
septiembre con 62.898,04 de saldo a favor que ya se le habían devuelto por transferencia.
El reembolso se había registrado como un «Pago» suelto a la cuenta de anticipos, y la
Conciliación de Pagos no ofrece ese pago para emparejarlo con el cobro cuando el anticipo
vive en una cuenta sin tipo: el cobro siguió ofreciendo el anticipo como disponible.

Los tests de las filas no tocan la base. Los de punta a punta corren contra el sitio, sobre
un cobro y un pago reales con saldo sin aplicar, dentro de una transacción que se revierte;
se saltan si el sitio no tiene uno.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from l10n_ve.overrides.advance_refund import (
    REFUND_DIRECTION,
    _refund_dimensions,
    build_refund_rows,
    create_advance_refund,
)


class TestRefundJournalRows(unittest.TestCase):
    def test_a_customer_refund_takes_money_out_of_the_bank(self):
        party, bank = build_refund_rows("out", 100.0, "Customer", "C1", "CXC", "BANCO")
        self.assertEqual(party["debit_in_account_currency"], 100.0)
        self.assertNotIn("credit_in_account_currency", party)
        self.assertEqual(bank["credit_in_account_currency"], 100.0)
        self.assertNotIn("debit_in_account_currency", bank)
        self.assertEqual(
            (party["account"], party["party_type"], party["party"]),
            ("CXC", "Customer", "C1"),
        )
        self.assertNotIn("party", bank)

    def test_a_supplier_refund_brings_money_into_the_bank(self):
        party, bank = build_refund_rows("in", 100.0, "Supplier", "P1", "CXP", "BANCO")
        self.assertEqual(party["credit_in_account_currency"], 100.0)
        self.assertNotIn("debit_in_account_currency", party)
        self.assertEqual(bank["debit_in_account_currency"], 100.0)
        self.assertNotIn("credit_in_account_currency", bank)
        self.assertEqual(
            (party["account"], party["party_type"], party["party"]),
            ("CXP", "Supplier", "P1"),
        )

    def test_the_party_row_carries_no_reference(self):
        """Con referencia al pago, el saldo del asiento quedaría contra ese pago y la
        conciliación no ofrecería el asiento como documento."""
        for direction in ("in", "out"):
            for row in build_refund_rows(direction, 1.0, "Customer", "C1", "A", "B"):
                self.assertNotIn("reference_type", row)
                self.assertNotIn("reference_name", row)

    def test_branch_and_cost_center_go_in_both_rows(self):
        rows = build_refund_rows(
            "out",
            1.0,
            "Customer",
            "C1",
            "A",
            "B",
            {"cost_center": "DC-01", "branch": "DC-01"},
        )
        for row in rows:
            self.assertEqual((row["cost_center"], row["branch"]), ("DC-01", "DC-01"))

    def test_an_unknown_direction_builds_no_rows(self):
        with self.assertRaises(ValueError):
            build_refund_rows("otro", 1.0, "Customer", "C1", "A", "B")

    def test_only_customer_receipts_and_supplier_payments(self):
        self.assertEqual(
            REFUND_DIRECTION,
            {("Customer", "Receive"): "out", ("Supplier", "Pay"): "in"},
        )


class TestRefundDimensions(unittest.TestCase):
    """De dónde salen la sucursal y el centro de costo de las filas del asiento."""

    def test_dimensions_come_from_the_payment_when_it_has_them(self):
        pe = frappe._dict(branch="MIR-04", cost_center="MIR-04", references=[])
        with (
            patch.object(frappe.local.db, "has_column", return_value=True),
            patch.object(frappe.local.db, "get_value") as get_value,
        ):
            self.assertEqual(
                _refund_dimensions(pe), {"cost_center": "MIR-04", "branch": "MIR-04"}
            )
            get_value.assert_not_called()

    def test_without_a_branch_it_looks_in_the_invoice_it_settles(self):
        """En Galanet hay 96 cobros y pagos validados sin sucursal ni centro de costo."""
        pe = frappe._dict(
            branch=None,
            cost_center=None,
            references=[
                frappe._dict(reference_doctype="Journal Entry", reference_name="JV-1"),
                frappe._dict(reference_doctype="Sales Invoice", reference_name="SI-1"),
            ],
        )
        valores = {
            ("Sales Invoice", "SI-1", "branch"): "DC-01",
            ("VE Branch", "DC-01", "cost_center"): "DC-01",
        }
        with (
            patch.object(frappe.local.db, "has_column", return_value=True),
            patch.object(
                frappe.local.db,
                "get_value",
                side_effect=lambda doctype, name, campo: valores[
                    (doctype, name, campo)
                ],
            ),
        ):
            self.assertEqual(
                _refund_dimensions(pe), {"cost_center": "DC-01", "branch": "DC-01"}
            )

    def test_it_does_not_invent_dimensions_it_cannot_find(self):
        pe = frappe._dict(branch=None, cost_center=None, references=[])
        with (
            patch.object(frappe.local.db, "has_column", return_value=True),
            patch.object(frappe.local.db, "get_value", return_value=None),
        ):
            self.assertEqual(_refund_dimensions(pe), {})


class _AgainstTheSite:
    """Corre contra el sitio y revierte todo al terminar cada test."""

    party_type: str
    payment_type: str

    def setUp(self):
        self.pe = self._find_advance()
        if not self.pe:
            self.skipTest(
                f"el sitio no tiene un {self.payment_type} de {self.party_type} con saldo sin aplicar"
            )
        patcher = patch.object(frappe.local.db, "commit")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(frappe.db.rollback)

    def _find_advance(self):
        cash_field = "paid_to" if self.payment_type == "Receive" else "paid_from"
        # `party_account_currency` no es columna: ERPNext la calcula al cargar el pago.
        currency_field = (
            "paid_from_account_currency"
            if self.payment_type == "Receive"
            else "paid_to_account_currency"
        )
        rows = frappe.db.sql(
            f"""SELECT pe.name
            FROM `tabPayment Entry` pe
            JOIN `tabAccount` a ON a.name = pe.{cash_field}
            JOIN `tabCompany` c ON c.name = pe.company
            WHERE pe.docstatus = 1 AND pe.party_type = %s AND pe.payment_type = %s
              AND pe.unallocated_amount >= 2
              AND a.account_type IN ('Bank', 'Cash')
              AND a.account_currency = pe.{currency_field}
              AND pe.{currency_field} = c.default_currency
            ORDER BY pe.posting_date DESC
            LIMIT 1""",
            (self.party_type, self.payment_type),
        )
        return frappe.get_doc("Payment Entry", rows[0][0]) if rows else None

    def _cash_account(self) -> str:
        return self.pe.paid_to if self.payment_type == "Receive" else self.pe.paid_from

    def _refund(self, amount: float, account: str | None = None) -> dict:
        posting_date = max(getdate(nowdate()), getdate(self.pe.posting_date))
        return create_advance_refund(
            self.pe.name,
            amount,
            account or self._cash_account(),
            str(posting_date),
            reference_no="PRUEBA1234",
        )

    def _party_balance(self) -> float:
        return flt(
            frappe.db.sql(
                """SELECT SUM(debit) - SUM(credit) FROM `tabGL Entry`
                WHERE party_type = %s AND party = %s AND is_cancelled = 0""",
                (self.pe.party_type, self.pe.party),
            )[0][0],
            2,
        )

    def test_the_advance_drops_by_the_refunded_amount(self):
        before = flt(self.pe.unallocated_amount, 2)
        result = self._refund(1.0)
        after = flt(
            frappe.db.get_value("Payment Entry", self.pe.name, "unallocated_amount"), 2
        )
        self.assertEqual(after, flt(before - 1.0, 2))
        self.assertEqual(
            frappe.db.get_value("Journal Entry", result["journal_entry"], "docstatus"),
            1,
        )

    def test_the_entry_is_applied_and_the_balance_moves_by_the_refund(self):
        """El asiento no queda con saldo propio, y el saldo del tercero cambia exactamente en lo
        que se devolvió: al cliente le baja el saldo a favor; al proveedor, el anticipo."""
        before = self._party_balance()
        result = self._refund(1.0)
        outstanding = frappe.db.sql(
            """SELECT SUM(amount) FROM `tabPayment Ledger Entry`
            WHERE against_voucher_no = %s AND delinked = 0""",
            result["journal_entry"],
        )[0][0]
        self.assertEqual(flt(outstanding, 2), 0.0)
        change = 1.0 if self.party_type == "Customer" else -1.0
        self.assertEqual(self._party_balance(), flt(before + change, 2))

    def test_it_refuses_to_refund_more_than_the_unapplied_amount(self):
        with self.assertRaises(frappe.ValidationError):
            self._refund(flt(self.pe.unallocated_amount) + 1)

    def test_it_refuses_a_future_posting_date(self):
        """El techo es hoy o la fecha del pago, lo que sea mayor: hay pagos cargados con
        fecha futura por error y su reembolso tiene que poder registrarse igual."""
        techo = max(getdate(nowdate()), getdate(self.pe.posting_date))
        with self.assertRaises(frappe.ValidationError):
            create_advance_refund(
                self.pe.name,
                1.0,
                self._cash_account(),
                str(add_days(techo, 1)),
                reference_no="PRUEBA1234",
            )

    def test_the_account_must_be_bank_or_cash(self):
        with self.assertRaises(frappe.ValidationError):
            self._refund(1.0, account=self.pe.party_account)


class TestCustomerRefund(_AgainstTheSite, unittest.TestCase):
    party_type = "Customer"
    payment_type = "Receive"


class TestSupplierRefund(_AgainstTheSite, unittest.TestCase):
    party_type = "Supplier"
    payment_type = "Pay"
