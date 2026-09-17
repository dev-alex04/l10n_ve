# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Detección de reembolsos que quedaron sin enlazar con el cobro que devolvieron.

Lo que se prueba sin tocar la base es la clasificación: cuándo un descuadre se puede corregir
solo, cuándo hay que revisarlo a mano y por qué. Contra el sitio se prueba que el diagnóstico
corra y que solo informe la dirección que importa (los cobros ofreciendo de más).
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import flt

from l10n_ve.overrides.advance_refund_audit import (
    _allocation_to_undo,
    _build_case,
    _close_refund_receipt,
    _not_a_refund,
    scan,
)


class TestWhetherItIsReallyARefund(unittest.TestCase):
    def test_without_a_bank_movement_it_is_not_a_refund(self):
        motivo = _not_a_refund("ACC-PAY-1", [])
        self.assertIn("ningún movimiento del banco", motivo)

    def test_against_a_deposit_it_is_not_either(self):
        motivo = _not_a_refund(
            "ACC-PAY-1", [frappe._dict(name="ACC-BTN-1", deposit=100.0, withdrawal=0.0)]
        )
        self.assertIn("DEPÓSITO", motivo)
        self.assertIn("ACC-BTN-1", motivo)

    def test_with_a_withdrawal_it_is_a_refund(self):
        self.assertIsNone(
            _not_a_refund(
                "ACC-PAY-1",
                [frappe._dict(name="ACC-BTN-1", deposit=0.0, withdrawal=100.0)],
            )
        )


class TestCaseClassification(unittest.TestCase):
    """`_build_case` decide si el caso se corrige solo o hay que mirarlo."""

    key = ("Empresa", "CLIENTE", "2104001 - Anticipo")

    def _case(self, refunds, offered, ledger, undo=None):
        with (
            patch(
                "l10n_ve.overrides.advance_refund_audit._refunds", return_value=refunds
            ),
            patch(
                "l10n_ve.overrides.advance_refund_audit._allocation_to_undo",
                return_value=undo,
            ),
        ):
            return _build_case(self.key, offered, ledger)

    def test_without_a_refund_that_explains_it_the_case_is_reviewed(self):
        case = self._case([], 100.0, 0.0)
        self.assertIn("No se encontró el reembolso", case.problem)

    def test_a_refund_that_does_not_explain_the_gap_is_reviewed(self):
        """Otros movimientos en la cuenta de anticipos: no se toca hasta entender cuáles."""
        case = self._case(
            [frappe._dict(name="JV-1", amount=40.0, problem=None)], 100.0, 0.0
        )
        self.assertIn("otros movimientos", case.problem)

    def test_the_phantom_credit_fixes_itself(self):
        """El saldo devuelto sigue entero en los cobros: basta el asiento de enlace."""
        case = self._case(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)], 150.0, 50.0
        )
        self.assertIsNone(case.problem)
        self.assertIsNone(case.undo)
        self.assertEqual(flt(case.difference, 2), 100.0)

    def test_the_hidden_debt_needs_an_application_undone(self):
        undo = {
            "applications": [
                {
                    "payment_entry": "ACC-PAY-1",
                    "sales_invoice": "ACC-SINV-1",
                    "amount": 60.0,
                }
            ],
            "invoice": "ACC-SINV-1",
            "undone": 60.0,
            "surplus": 0.0,
        }
        case = self._case(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)],
            40.0,
            -60.0,
            undo=undo,
        )
        self.assertIsNone(case.problem)
        self.assertEqual(case.undo, undo)

    def test_when_no_application_is_enough_the_case_is_reviewed(self):
        case = self._case(
            [frappe._dict(name="JV-1", amount=100.0, problem=None)],
            40.0,
            -60.0,
            undo=None,
        )
        self.assertIn("que alcance", case.problem)

    def test_the_refund_problem_wins(self):
        """Si el «Pago» está contra un depósito, no se corrige aunque las cuentas cuadren."""
        refund = frappe._dict(
            name="ACC-PAY-1", amount=100.0, problem="está conciliado con un DEPÓSITO"
        )
        case = self._case([refund], 150.0, 50.0)
        self.assertIn("DEPÓSITO", case.problem)


class TestScanAgainstTheSite(unittest.TestCase):
    def setUp(self):
        self.company = frappe.db.get_value("Company", {}, "name")
        if not self.company:
            self.skipTest("el sitio no tiene empresas")

    def test_it_returns_cases_with_the_expected_shape(self):
        for case in scan(company=self.company):
            self.assertEqual(
                set(case) >= {"party", "offered", "ledger", "difference", "refunds"},
                True,
            )
            self.assertGreater(flt(case["difference"], 2), 0.0)

    def test_it_only_reports_when_payments_offer_more_than_the_ledger(self):
        """Al revés son los ajustes por diferencia en cambio, que no son un reembolso."""
        for case in scan(company=self.company):
            self.assertGreater(flt(case["offered"], 2), flt(case["ledger"], 2))

    def test_the_tolerance_discards_the_cents(self):
        amplio = scan(company=self.company, tolerance=0.01)
        acotado = scan(company=self.company, tolerance=1000.0)
        self.assertLessEqual(len(acotado), len(amplio))


class TestRefundReceipt(unittest.TestCase):
    """Que el recibo del reembolso deje de mostrar su monto como saldo a favor.

    Aurelys lo reportó el 16-sep-2026, con ZAPATERIA GASOLINA EXTRA ya corregido: «el cliente
    está saldado pero el recibo sigue saliendo con el monto». La contabilidad estaba bien; lo
    que no se enteraba era el documento.
    """

    def _close(self, refund: dict, receipt: dict, already_linked: bool = False):
        """Corre el cierre con la base simulada y devuelve (fila escrita, campos del recibo)."""
        row = MagicMock()
        with (
            patch.object(frappe.db, "get_value", return_value=frappe._dict(receipt)),
            patch.object(frappe.db, "exists", return_value=already_linked),
            patch.object(frappe.db, "count", return_value=0),
            patch.object(frappe, "new_doc", return_value=row),
            patch.object(frappe.db, "set_value") as set_value,
        ):
            _close_refund_receipt(refund, "ACC-JV-2026-35430", 232565.54)
        written = row.update.call_args[0][0] if row.update.call_args else None
        fields = set_value.call_args[0][2] if set_value.call_args else None
        return written, fields

    def test_the_receipt_ends_linked_and_with_no_credit_left(self):
        written, fields = self._close(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 232565.54,
                "total_allocated_amount": 0.0,
                "base_total_allocated_amount": 0.0,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertEqual(written["reference_doctype"], "Journal Entry")
        self.assertEqual(written["reference_name"], "ACC-JV-2026-35430")
        self.assertEqual(written["allocated_amount"], 232565.54)
        self.assertEqual(fields["unallocated_amount"], 0.0)
        self.assertEqual(fields["total_allocated_amount"], 232565.54)

    def test_it_never_allocates_more_than_what_was_unallocated(self):
        """Si el recibo ya tenía parte aplicada, solo se cierra lo que quedaba libre."""
        written, fields = self._close(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 100.0,
                "total_allocated_amount": 50.0,
                "base_total_allocated_amount": 50.0,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertEqual(written["allocated_amount"], 100.0)
        self.assertEqual(fields["total_allocated_amount"], 150.0)
        self.assertEqual(fields["unallocated_amount"], 0.0)

    def test_a_journal_booked_refund_has_no_receipt_to_close(self):
        with patch.object(frappe.db, "get_value") as consulta:
            _close_refund_receipt(
                {"doctype": "Journal Entry", "name": "ACC-JV-2026-30001"},
                "ACC-JV-2026-35430",
                100.0,
            )
        consulta.assert_not_called()

    def test_an_already_linked_receipt_is_not_written_twice(self):
        """El script se puede volver a correr sin duplicar la fila."""
        written, fields = self._close(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 232565.54,
                "total_allocated_amount": 0.0,
                "base_total_allocated_amount": 0.0,
                "target_exchange_rate": 1.0,
            },
            already_linked=True,
        )
        self.assertIsNone(written)
        self.assertIsNone(fields)

    def test_a_receipt_with_nothing_free_is_left_alone(self):
        written, fields = self._close(
            {"doctype": "Payment Entry", "name": "ACC-PAY-2026-21786-1"},
            {
                "unallocated_amount": 0.0,
                "total_allocated_amount": 232565.54,
                "base_total_allocated_amount": 232565.54,
                "target_exchange_rate": 1.0,
            },
        )
        self.assertIsNone(written)
        self.assertIsNone(fields)


class TestTiedApplications(unittest.TestCase):
    """Cuando dos aplicaciones encajan igual de bien, no se elige al azar.

    Quedarse con la primera es elegir a suertes de qué factura se saca la deuda, y nada lo
    atraparía: `_verify` compara el agregado del cliente contra el mayor, no la factura que se
    tocó. Elegir mal deja la factura buena mostrando deuda y la que sí se pagó con la plata
    devuelta marcada «Pagada»: el mismo problema que esto viene a resolver.
    """

    def _application(
        self, invoice: str, amount: float, payment: str = "ACC-PAY-1"
    ) -> dict:
        return frappe._dict(payment_entry=payment, sales_invoice=invoice, amount=amount)

    def _choose(self, applications: list, missing: float = 100.0) -> tuple:
        case = frappe._dict(difference=missing, offered=0.0, tied_invoices=None)
        with patch(
            "l10n_ve.overrides.advance_refund_audit._applications_after_refund",
            return_value=applications,
        ):
            return _allocation_to_undo(case), case

    def test_two_exact_applications_on_different_invoices_go_to_review(self):
        chosen, case = self._choose(
            [
                self._application("ACC-SINV-A", 100.0),
                self._application("ACC-SINV-B", 100.0),
            ]
        )
        self.assertIsNone(chosen)
        self.assertEqual(case.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_a_tie_within_the_same_invoice_is_not_ambiguous(self):
        """Da igual cuál se deshaga: el resultado en esa factura es el mismo."""
        chosen, case = self._choose(
            [
                self._application("ACC-SINV-A", 100.0, "ACC-PAY-1"),
                self._application("ACC-SINV-A", 100.0, "ACC-PAY-2"),
            ]
        )
        self.assertEqual(chosen["invoice"], "ACC-SINV-A")
        self.assertIsNone(case.tied_invoices)

    def test_two_combinations_on_different_invoices_go_to_review(self):
        chosen, case = self._choose(
            [
                self._application("ACC-SINV-A", 60.0),
                self._application("ACC-SINV-A", 40.0),
                self._application("ACC-SINV-B", 70.0),
                self._application("ACC-SINV-B", 30.0),
            ]
        )
        self.assertIsNone(chosen)
        self.assertEqual(case.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_a_tie_on_the_biggest_application_also_goes_to_review(self):
        chosen, case = self._choose(
            [
                self._application("ACC-SINV-A", 150.0),
                self._application("ACC-SINV-B", 150.0),
            ]
        )
        self.assertIsNone(chosen)
        self.assertEqual(case.tied_invoices, ["ACC-SINV-A", "ACC-SINV-B"])

    def test_without_a_tie_the_choice_stays_the_same(self):
        """Lo que ya se corregía no cambia: los 19 casos de Galanet no tienen empates."""
        chosen, case = self._choose(
            [
                self._application("ACC-SINV-A", 150.0),
                self._application("ACC-SINV-B", 260.0),
            ]
        )
        self.assertEqual(chosen["invoice"], "ACC-SINV-A")
        self.assertEqual(flt(chosen["undone"], 2), 150.0)
        self.assertEqual(flt(chosen["surplus"], 2), 50.0)
        self.assertIsNone(case.tied_invoices)

    def test_the_ambiguous_case_says_why_it_needs_a_look(self):
        """El motivo no puede ser «no hay ninguna que alcance»: hay dos, y ese es el problema."""
        with (
            patch(
                "l10n_ve.overrides.advance_refund_audit._refunds",
                return_value=[
                    frappe._dict(name="ACC-PAY-1", amount=100.0, problem=None)
                ],
            ),
            patch(
                "l10n_ve.overrides.advance_refund_audit._applications_after_refund",
                return_value=[
                    self._application("ACC-SINV-A", 60.0),
                    self._application("ACC-SINV-B", 60.0),
                ],
            ),
        ):
            case = _build_case(
                ("Empresa", "CLIENTE", "2104001 - Anticipo"), 40.0, -60.0
            )
        self.assertIsNone(case.undo)
        self.assertIn("facturas distintas", case.problem)
        self.assertIn("ACC-SINV-A", case.problem)
        self.assertIn("ACC-SINV-B", case.problem)
