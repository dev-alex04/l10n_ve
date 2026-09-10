# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""El filtro «Sucursal VE» de Cuentas por Cobrar decide por el documento de ORIGEN.

Una fila del reporte es el documento que origina la cuenta por cobrar, y su pendiente
suma todo lo que apunta a él en el libro de pagos. El filtro anterior miraba la sucursal
de cada movimiento y buscaba la de la factura en una clave que ERPNext no devuelve
(``against_voucher`` en vez de ``against_voucher_no``). Como ``Journal Entry`` no tiene
sucursal en la cabecera, se caían todos los asientos: ACC-SINV-2026-32308 (SOFTELINET,
DC-01), saldada por un asiento de diferencial cambiario de Bs 45, salía debiendo esos
Bs 45 al filtrar por DC-01 y no salía sin filtro (reportado el 10-sep-2026).

Sin base de datos: se simulan ``frappe.get_meta`` y ``frappe.get_all``.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe import _dict

from l10n_ve.patches.reports import receivable_payable as rp

# Journal Entry no está: su sucursal vive en las filas, no en la cabecera.
_WITH_BRANCH_FIELD = {"Sales Invoice", "Payment Entry", "VE Sales Credit Note", "Purchase Invoice"}

_BRANCH_OF = {
    ("Sales Invoice", "SI-DC01"): "DC-01",
    ("Sales Invoice", "SI-MIR05"): "MIR-05",
    ("Payment Entry", "PE-DC01"): "DC-01",
    ("Payment Entry", "PE-MIR05"): "MIR-05",
    ("Payment Entry", "ADV-DC01"): "DC-01",
    ("Payment Entry", "ADV-SO-DC01"): "DC-01",
    # Anticipo del conector de Bancaribe: nace sin sucursal a propósito.
    ("Payment Entry", "ADV-NONE"): "",
    ("VE Sales Credit Note", "NC-DC01"): "DC-01",
    ("Purchase Invoice", "PI-DC01"): "DC-01",
}


class _Meta:
    def __init__(self, doctype):
        self.doctype = doctype

    def has_field(self, fieldname):
        return fieldname == "branch" and self.doctype in _WITH_BRANCH_FIELD


def _get_meta(doctype):
    if doctype == "Retired Doctype":
        raise frappe.DoesNotExistError(doctype)
    return _Meta(doctype)


def _get_all(doctype, filters=None, fields=None):
    names = filters["name"][1]
    return [_dict(name=n, branch=_BRANCH_OF[(doctype, n)]) for n in names if (doctype, n) in _BRANCH_OF]


def _ple(voucher_type, voucher_no, against_type, against_no, amount):
    return _dict(
        voucher_type=voucher_type,
        voucher_no=voucher_no,
        against_voucher_type=against_type,
        against_voucher_no=against_no,
        amount=amount,
    )


def _own(doctype, name, amount):
    """El movimiento del propio documento: la factura, su retención o el anticipo sin aplicar."""
    return _ple(doctype, name, doctype, name, amount)


class TestFilterByOriginBranch(unittest.TestCase):
    def setUp(self):
        for target, fake in (("frappe.get_meta", _get_meta), ("frappe.get_all", _get_all)):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _filter(self, ples, branch):
        return rp.filter_ple_by_ve_branch(ples, branch)

    def test_the_witness_case_exchange_journal_settles_the_invoice(self):
        """ACC-SINV-2026-32308: el asiento cambiario no tiene sucursal, pero apunta a la
        factura de DC-01, así que cuenta. Con él el pendiente es cero, igual que sin filtro."""
        ples = [
            _own("Sales Invoice", "SI-DC01", 73322.17),
            _own("Sales Invoice", "SI-DC01", -7585.05),
            _own("Sales Invoice", "SI-DC01", -1264.18),
            _ple("Payment Entry", "PE-DC01", "Sales Invoice", "SI-DC01", -64427.94),
            _ple("Journal Entry", "JV-EXCHANGE", "Sales Invoice", "SI-DC01", -45.00),
        ]

        kept = self._filter(ples, "DC-01")

        self.assertEqual(kept, ples)
        self.assertAlmostEqual(sum(p.amount for p in kept), 0.0, places=2)

    def test_a_payment_from_another_branch_counts_for_the_invoice(self):
        ples = [
            _own("Sales Invoice", "SI-DC01", 100.0),
            _ple("Payment Entry", "PE-MIR05", "Sales Invoice", "SI-DC01", -100.0),
        ]

        self.assertEqual(self._filter(ples, "DC-01"), ples)
        self.assertEqual(self._filter(ples, "MIR-05"), [])

    def test_a_payment_applied_to_another_branch_does_not_become_an_advance(self):
        """Un cobro de DC-01 aplicado a una factura de MIR-05 no entra en DC-01. Antes entraba
        sin su factura, ERPNext lo imputaba al propio cobro y salía como anticipo negativo."""
        ples = [
            _own("Sales Invoice", "SI-MIR05", 100.0),
            _ple("Payment Entry", "PE-DC01", "Sales Invoice", "SI-MIR05", -100.0),
        ]

        self.assertEqual(self._filter(ples, "DC-01"), [])
        self.assertEqual(self._filter(ples, "MIR-05"), ples)

    def test_an_unapplied_advance_follows_its_own_branch(self):
        ples = [_own("Payment Entry", "ADV-DC01", -250.0)]

        self.assertEqual(self._filter(ples, "DC-01"), ples)
        self.assertEqual(self._filter(ples, "MIR-05"), [])

    def test_an_origin_without_branch_belongs_to_no_branch(self):
        """El anticipo de Bancaribe y el asiento como documento de origen solo salen sin filtro."""
        ples = [_own("Payment Entry", "ADV-NONE", -500.0), _own("Journal Entry", "JV-OPENING", 300.0)]

        self.assertEqual(self._filter(ples, "DC-01"), [])

    def test_a_credit_note_follows_the_invoice_it_affects(self):
        ples = [
            _own("Sales Invoice", "SI-DC01", 100.0),
            _ple("VE Sales Credit Note", "NC-DC01", "Sales Invoice", "SI-DC01", -100.0),
        ]

        self.assertEqual(self._filter(ples, "DC-01"), ples)

    def test_the_payable_side_uses_the_same_rule(self):
        """Cuentas por Pagar comparte la función: el asiento contra la factura de compra cuenta."""
        ples = [
            _own("Purchase Invoice", "PI-DC01", -80.0),
            _ple("Journal Entry", "JV-EXCHANGE", "Purchase Invoice", "PI-DC01", 80.0),
        ]

        self.assertEqual(self._filter(ples, "DC-01"), ples)

    def test_every_movement_lands_in_exactly_one_branch(self):
        """Filtrar por cada sucursal reparte el libro sin repetir ni perder movimientos, salvo
        los de documentos de origen sin sucursal, que no son de ninguna."""
        ples = [
            _own("Sales Invoice", "SI-DC01", 100.0),
            _own("Sales Invoice", "SI-MIR05", 70.0),
            _ple("Payment Entry", "PE-DC01", "Sales Invoice", "SI-MIR05", -70.0),
            _ple("Payment Entry", "PE-MIR05", "Sales Invoice", "SI-DC01", -60.0),
            _ple("Journal Entry", "JV-EXCHANGE", "Sales Invoice", "SI-DC01", -40.0),
            _own("Payment Entry", "ADV-DC01", -250.0),
            _ple("Payment Entry", "ADV-SO-DC01", "Sales Order", "SO-1", -300.0),
            _own("Payment Entry", "ADV-NONE", -500.0),
        ]

        placed = [id(p) for branch in ("DC-01", "MIR-05") for p in self._filter(ples, branch)]

        self.assertEqual(len(placed), len(set(placed)))
        self.assertEqual(len(placed), len(ples) - 1)

    def test_an_advance_against_a_sales_order_follows_the_payment(self):
        """La Orden de Venta no tiene movimientos propios en el libro: ERPNext muestra el anticipo
        como fila del cobro, así que decide la sucursal del cobro. Si decidiera la Orden, que no
        tiene sucursal, el anticipo desaparecería de todos los filtros."""
        ples = [_ple("Payment Entry", "ADV-SO-DC01", "Sales Order", "SO-1", -300.0)]

        self.assertEqual(self._filter(ples, "DC-01"), ples)
        self.assertEqual(self._filter(ples, "MIR-05"), [])

    def test_a_payment_against_an_opening_journal_stays_with_the_journal(self):
        """El asiento de apertura tiene fila propia y no tiene sucursal: su cobro va con él. Antes el
        cobro de DC-01 entraba solo y salía como anticipo negativo."""
        ples = [
            _own("Journal Entry", "JV-OPENING", 300.0),
            _ple("Payment Entry", "PE-DC01", "Journal Entry", "JV-OPENING", -300.0),
        ]

        self.assertEqual(self._filter(ples, "DC-01"), [])

    def test_a_retired_doctype_is_skipped_not_fatal(self):
        ples = [_own("Retired Doctype", "OLD-1", 10.0), _own("Sales Invoice", "SI-DC01", 5.0)]

        self.assertEqual(self._filter(ples, "DC-01"), [ples[1]])

    def test_other_lookup_errors_are_not_swallowed(self):
        """Tragar el error descartaba filas en silencio: un pendiente equivocado con cara de correcto."""
        with patch("frappe.get_all", side_effect=RuntimeError("db down")), self.assertRaises(RuntimeError):
            self._filter([_own("Sales Invoice", "SI-DC01", 5.0)], "DC-01")

    def test_an_empty_ledger_returns_empty(self):
        self.assertEqual(self._filter([], "DC-01"), [])
