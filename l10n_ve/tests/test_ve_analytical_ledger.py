# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests del filtrado de asientos anulados en el Mayor Analítico.

Contexto: GL Entry se emite al crearse y la cancelación de un voucher NO cambia el
docstatus, solo pone is_cancelled = 1 (erpnext/accounts/general_ledger.py). En
domina.galanet, de 117.864 asientos hay 0 con docstatus = 2 y 7.812 con
is_cancelled = 1, así que filtrar solo por `docstatus = 1` —como hacía el reporte—
incluía los anulados. El residuo NO netea a cero por cuenta: ~-2,8 MM en Cuentas
por Cobrar Clientes y ~+2,7 MM en Anticipo de Clientes.

Lo que se verifica acá:

1. Por defecto los anulados no se consultan (la SQL lleva is_cancelled = 0).
2. El saldo inicial NUNCA los incluye, ni con la casilla activa: es un
   SUM(debit - credit) y los anulados lo descuadrarían contra el cierre.
3. Con la casilla activa los anulados se listan, quedan marcados y NO mueven el
   saldo corriente ni los totales de la cuenta.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
import frappe.translate

from l10n_ve.l10n_ve.report.ve_analytical_ledger.ve_analytical_ledger import execute

FILTERS = {
    "company": "COMPANY-TEST",
    "from_date": "2026-07-01",
    "to_date": "2026-07-31",
}

ACCOUNT = "1105001 - Cuentas por Cobrar Clientes - Test"


def _entry(gle_id, voucher_no, debit=0.0, credit=0.0, is_cancelled=0):
    return frappe._dict({
        "gle_id": gle_id,
        "posting_date": "2026-07-10",
        "voucher_no": voucher_no,
        "account": ACCOUNT,
        "remarks": "",
        "debit": debit,
        "credit": credit,
        "party": None,
        "party_type": None,
        "is_cancelled": is_cancelled,
    })


class AnalyticalLedgerHarness(unittest.TestCase):
    """Arma execute() sobre frappe.db mockeado: sin site ni datos reales."""

    #: entradas que devuelve la 2da consulta (entries_query)
    entries = []
    #: saldo inicial que devuelve la 1ra consulta (init_query)
    opening = 0.0

    def setUp(self):
        self.queries = []

        def fake_sql(query, values=None, as_dict=False):
            self.queries.append(query)
            if "SUM(debit - credit)" in query:
                return [frappe._dict({"account": ACCOUNT, "balance": self.opening})]
            return list(self.entries)

        def fake_get_all(doctype, **kwargs):
            if doctype == "Account":
                return [frappe._dict({
                    "name": ACCOUNT,
                    "account_number": "1105001",
                    "account_name": "Cuentas por Cobrar Clientes",
                })]
            return []

        # frappe.db es un LocalProxy sobre frappe.local.db: sin site no está bindeado y
        # patch.object(frappe.db, ...) revienta con "object is not bound". Se reemplaza el
        # objeto de abajo, que es lo que el proxy resuelve.
        previous_db = getattr(frappe.local, "db", None)
        frappe.local.db = SimpleNamespace(
            sql=fake_sql,
            get_all=fake_get_all,
            get_value=lambda *args, **kwargs: "J-12345678-9",
        )
        self.addCleanup(setattr, frappe.local, "db", previous_db)

        # El reporte usa _() para las etiquetas. Sin esto el test depende del orden de
        # ejecución del suite: si otro módulo dejó frappe.local.site apuntando a un site
        # inexistente, el cargador de traducciones intenta escribir su log y revienta con
        # FileNotFoundError. Devolver {} deja a _() como identidad, que además hace las
        # aserciones sobre etiquetas deterministas.
        translations_patch = patch.object(frappe.translate, "get_all_translations", return_value={})
        translations_patch.start()
        self.addCleanup(translations_patch.stop)

    def run_report(self, **extra_filters):
        filters = dict(FILTERS)
        filters.update(extra_filters)
        # execute() devuelve (columns, data, message, chart, report_summary)
        return execute(filters)[1]

    @property
    def init_query(self):
        return next(q for q in self.queries if "SUM(debit - credit)" in q)

    @property
    def entries_query(self):
        return next(q for q in self.queries if "SUM(debit - credit)" not in q)

    @staticmethod
    def entry_rows(data):
        """Solo las filas de movimiento: las estructurales llevan flag propio."""
        return [
            r for r in data
            if not (
                r.get("is_header") or r.get("is_opening")
                or r.get("is_total") or r.get("is_spacer")
            )
        ]

    @staticmethod
    def total_row(data):
        return next(r for r in data if r.get("is_total"))


class TestDefaultExcludesCancelled(AnalyticalLedgerHarness):
    entries = [_entry("GLE-001", "SINV-001", debit=100.0)]

    def test_entries_query_filters_cancelled(self):
        self.run_report()
        self.assertIn("IFNULL(is_cancelled, 0) = 0", self.entries_query)

    def test_docstatus_is_fixed_to_submitted(self):
        """No se usa docstatus IN (1, 2): en GL Entry el docstatus 2 no existe.

        Se prueba con la casilla ACTIVA porque es el único camino donde aparecía
        la rama muerta; apagada, la consulta ya decía docstatus = 1 igual.
        """
        for include_cancelled in (0, 1):
            with self.subTest(include_cancelled=include_cancelled):
                self.queries = []
                self.run_report(include_cancelled=include_cancelled)
                for query in (self.init_query, self.entries_query):
                    self.assertIn("docstatus = 1", query)
                    self.assertNotIn("docstatus IN", query)

    def test_string_zero_does_not_enable_cancelled(self):
        """Invocado por API el filtro puede llegar como "0"; cint lo trata como apagado."""
        self.run_report(include_cancelled="0")
        self.assertIn("IFNULL(is_cancelled, 0) = 0", self.entries_query)


class TestOpeningBalanceAlwaysExcludesCancelled(AnalyticalLedgerHarness):
    entries = []
    opening = 500.0

    def test_init_query_excludes_cancelled_even_when_included(self):
        self.run_report(include_cancelled=1)
        self.assertIn("IFNULL(is_cancelled, 0) = 0", self.init_query)

    def test_entries_query_does_include_cancelled(self):
        self.run_report(include_cancelled=1)
        self.assertNotIn("is_cancelled", self.entries_query.split("WHERE", 1)[1])


class TestCancelledRowsDoNotMoveBalance(AnalyticalLedgerHarness):
    entries = [
        _entry("GLE-001", "SINV-001", debit=100.0),
        _entry("GLE-002", "SINV-002", debit=999.0, is_cancelled=1),
        _entry("GLE-003", "SINV-003", credit=40.0),
    ]
    opening = 500.0

    def setUp(self):
        super().setUp()
        self.data = self.run_report(include_cancelled=1)

    def test_cancelled_entry_is_listed(self):
        self.assertEqual(len(self.entry_rows(self.data)), 3)

    def test_cancelled_entry_is_marked_in_voucher_no(self):
        cancelled = [r for r in self.entry_rows(self.data) if r.get("is_cancelled")]
        self.assertEqual(len(cancelled), 1)
        self.assertIn("SINV-002", cancelled[0]["voucher_no"])
        self.assertNotEqual(cancelled[0]["voucher_no"], "SINV-002")

    def test_running_balance_skips_cancelled(self):
        # 500 inicial + 100 debe - 40 haber = 560. El anulado de 999 no participa.
        balances = [r["balance"] for r in self.entry_rows(self.data)]
        self.assertEqual(balances, [600.0, 600.0, 560.0])

    def test_account_totals_skip_cancelled(self):
        total = self.total_row(self.data)
        self.assertEqual(total["debit"], 100.0)
        self.assertEqual(total["credit"], 40.0)
        self.assertEqual(total["balance"], 560.0)


if __name__ == "__main__":
    unittest.main()
