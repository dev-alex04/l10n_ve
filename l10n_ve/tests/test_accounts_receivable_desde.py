# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""«Desde» en Cuentas por Cobrar filtra DOCUMENTOS, no pagos.

Regla fijada por Daniel el 9-sep-2026: «Desde» y «Hasta» eligen los documentos que
originan la cuenta por cobrar por su fecha de contabilización, y el pendiente de cada uno
se calcula con todo lo que lo afecta hasta «Hasta», aunque el pago sea anterior a «Desde».

Antes, el parche recortaba el libro de pagos por ``posting_date >= from_date``: bajo
emitir-al-pagar el cobro precede a la factura, y el reporte de septiembre de 2026 listaba
615 facturas pagadas (Bs 9,96 M) como impagas (medido en producción el 9-sep-2026).

Sin base de datos: se simula el objeto del reporte.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe import _dict

from l10n_ve.patches.reports import accounts_receivable as ar

MOD = "l10n_ve.patches.reports.accounts_receivable"


def setUpModule():
    """`flt(x, 2)` resuelve el redondeo con System Settings; se calienta antes de mockear."""
    frappe.get_system_settings("rounding_method")


def _row(voucher_no, posting_date, invoiced, paid=0.0, credit_note=0.0, voucher_type="Sales Invoice"):
    return _dict(
        voucher_type=voucher_type, voucher_no=voucher_no, posting_date=posting_date,
        invoiced=invoiced, paid=paid, credit_note=credit_note,
        invoiced_in_account_currency=invoiced, paid_in_account_currency=paid,
        credit_note_in_account_currency=credit_note, bill_no="", payment_terms=[],
    )


def _report(rows, **filters):
    base = {"company": "Galanet Solution C.A.", "report_date": "2026-09-30", "based_on_payment_terms": 0,
                "for_revaluation_journals": 0, "group_by_party": 0}
    base.update(filters)
    rep = _dict(filters=_dict(base), voucher_balance={r.voucher_no: r for r in rows},
                currency_precision=2, err_journals=set(), data=[], previous_party=None, total_row_map={})
    rep.append_row = lambda r: rep.data.append(r)
    rep.is_invoice = lambda r: r.voucher_type == "Sales Invoice"
    return rep


def _listed(rep):
    return {r.voucher_no: r.outstanding for r in rep.data}


class TestDesdeFiltraDocumentos(unittest.TestCase):
    def test_the_witness_case_paid_with_an_earlier_advance_is_not_listed(self):
        """ACC-SINV-2026-20416: factura del 1-sep, anticipo del 21-ago y asiento del 1-ago.
        Con el libro completo su pendiente es cero, así que no sale, aunque «Desde» sea 1-sep."""
        rep = _report([_row("ACC-SINV-2026-20416", "2026-09-01", 11974.89, paid=11974.89)],
                      from_date="2026-09-01", to_date="2026-09-30")
        ar.build_data(rep)
        self.assertEqual(_listed(rep), {})

    def test_a_document_in_the_window_keeps_its_real_outstanding(self):
        """El pago anterior a «Desde» ya viene sumado en `paid`: el pendiente es 600, no 1.000."""
        rep = _report([_row("SI-SEP", "2026-09-03", 1000.0, paid=400.0)],
                      from_date="2026-09-01", to_date="2026-09-30")
        ar.build_data(rep)
        self.assertEqual(_listed(rep), {"SI-SEP": 600.0})

    def test_a_document_before_desde_is_left_out_even_if_it_owes(self):
        rep = _report([_row("SI-AGO", "2026-08-15", 500.0), _row("SI-SEP", "2026-09-03", 1000.0, paid=400.0)],
                      from_date="2026-09-01", to_date="2026-09-30")
        ar.build_data(rep)
        self.assertEqual(_listed(rep), {"SI-SEP": 600.0})

    def test_an_unapplied_advance_is_a_document_too(self):
        """El anticipo sin aplicar es una fila negativa: entra o sale por SU fecha."""
        rep = _report([_row("PE-AGO", "2026-08-20", 0.0, paid=300.0, voucher_type="Payment Entry"),
                       _row("PE-SEP", "2026-09-05", 0.0, paid=300.0, voucher_type="Payment Entry")],
                      from_date="2026-09-01", to_date="2026-09-30")
        ar.build_data(rep)
        self.assertEqual(_listed(rep), {"PE-SEP": -300.0})

    def test_without_desde_everything_with_outstanding_is_listed(self):
        rep = _report([_row("SI-AGO", "2026-08-15", 500.0), _row("SI-SEP", "2026-09-03", 1000.0, paid=400.0)],
                      to_date="2026-09-30")
        ar.build_data(rep)
        self.assertEqual(_listed(rep), {"SI-AGO": 500.0, "SI-SEP": 600.0})

    def test_hasta_still_drives_report_date(self):
        rep = _report([], from_date="2026-09-01", to_date="2026-09-15")
        ar.build_data(rep)
        self.assertEqual(str(rep.filters.report_date), "2026-09-15")


class TestTheLedgerIsNoLongerCut(unittest.TestCase):
    def test_prepare_ple_query_does_not_inject_a_date_condition(self):
        seen = {}

        def fake_standard(self):
            self.prepare_conditions()
            seen["filters"] = list(self.qb_selection_filter)
            return "query"

        rep = _dict(filters=_dict(from_date="2026-09-01", to_date="2026-09-30", report_date="2026-09-30"),
                    qb_selection_filter=[], ple=_dict(posting_date=None))
        rep.prepare_conditions = lambda: None
        with patch(f"{MOD}.erpnext_prepare_ple_query", fake_standard):
            self.assertEqual(ar.prepare_ple_query(rep), "query")
        self.assertEqual(seen["filters"], [])
        self.assertEqual(str(rep.filters.report_date), "2026-09-30")

    def test_return_entries_come_from_the_standard_even_with_desde(self):
        rep = _dict(filters=_dict(from_date="2026-09-01", to_date="2026-09-30", report_date="2026-09-30"))
        with patch(f"{MOD}.erpnext_get_return_entries") as standard:
            ar.get_return_entries(rep)
        standard.assert_called_once_with(rep)
