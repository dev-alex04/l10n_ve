# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Tests del patch de backfill bill_no/bill_control hacia tabGL Entry.

Suite 100% unittest + mocks (sin BD ni FrappeTestCase): el módulo solo importa
`frappe` a nivel de top-level, así que se importa sin arrancar el site.
"""

import unittest
from unittest.mock import patch, MagicMock

from l10n_ve.patches.accounts import backfill_gl_entry_bill_fields as bf

_PATH = "l10n_ve.patches.accounts.backfill_gl_entry_bill_fields"


def _inv(name, bill_no=None, bill_control=None):
    """Fila estilo as_dict=True que devuelve el SELECT del backfill."""
    return {"name": name, "bill_no": bill_no, "bill_control": bill_control}


class TestUpdateGlEntriesBatch(unittest.TestCase):
    """_update_gl_entries_batch: armado del UPDATE, alineación de params y rowcount."""

    def _run(self, batch, rowcount=5):
        captured = {}

        def fake_sql(sql, params=None, *a, **kw):
            captured["sql"] = sql
            captured["params"] = params
            return None  # frappe.db.sql(UPDATE) no devuelve filas

        with patch(f"{_PATH}.frappe") as mock_frappe:
            mock_frappe.db.sql.side_effect = fake_sql
            mock_frappe.db._cursor.rowcount = rowcount
            result = bf._update_gl_entries_batch("Sales Invoice", batch)
        return result, captured.get("sql"), captured.get("params")

    def test_rowcount_returned_as_int_no_typeerror(self):
        """Regresión fix 2f7f042: retorna cursor.rowcount (int), no el valor de db.sql."""
        result, _sql, _p = self._run([_inv("SI-1", bill_no="A-1")], rowcount=7)
        self.assertEqual(result, 7)
        # debe poder sumarse sin TypeError (antes el return de db.sql rompía el +=)
        self.assertEqual(0 + result, 7)

    def test_param_alignment_voucher_type_before_names(self):
        """Orden de params = [pares bill_no, pares bill_control, voucher_type, *names]."""
        batch = [
            _inv("SI-1", bill_no="A-1", bill_control="C-1"),
            _inv("SI-2", bill_no="A-2"),
        ]
        _r, sql, params = self._run(batch)
        idx_vt = params.index("Sales Invoice")
        # voucher_type va JUSTO antes de los voucher_names
        self.assertEqual(params[idx_vt + 1:], ["SI-1", "SI-2"])
        # y DESPUÉS de los pares de los CASE (bill_no/bill_control)
        self.assertIn("A-1", params[:idx_vt])
        self.assertIn("C-1", params[:idx_vt])
        # conteo de placeholders %s == número de params
        self.assertEqual(sql.count("%s"), len(params))

    def test_only_bill_no(self):
        _r, sql, params = self._run([_inv("SI-1", bill_no="A-1")])
        self.assertIn("bill_no = CASE", sql)
        self.assertNotIn("bill_control = CASE", sql)
        self.assertEqual(params, ["SI-1", "A-1", "Sales Invoice", "SI-1"])

    def test_only_bill_control(self):
        _r, sql, params = self._run([_inv("SI-1", bill_control="C-1")])
        self.assertIn("bill_control = CASE", sql)
        self.assertNotIn("bill_no = CASE", sql)
        self.assertEqual(params, ["SI-1", "C-1", "Sales Invoice", "SI-1"])

    def test_empty_batch_returns_zero_without_sql(self):
        with patch(f"{_PATH}.frappe") as mock_frappe:
            result = bf._update_gl_entries_batch("Sales Invoice", [])
        self.assertEqual(result, 0)
        mock_frappe.db.sql.assert_not_called()

    def test_all_falsy_values_returns_zero_without_sql(self):
        """Filas sin bill_no ni bill_control: no se arma CASE → 0 sin tocar la BD."""
        batch = [_inv("SI-1"), _inv("SI-2", bill_no="", bill_control="")]
        with patch(f"{_PATH}.frappe") as mock_frappe:
            result = bf._update_gl_entries_batch("Sales Invoice", batch)
        self.assertEqual(result, 0)
        mock_frappe.db.sql.assert_not_called()

    def test_idempotency_guard_in_where(self):
        """El WHERE solo toca filas con bill_no/bill_control vacíos → re-ejecutable."""
        _r, sql, _p = self._run([_inv("SI-1", bill_no="A-1")])
        self.assertIn(
            "(bill_no IS NULL OR bill_no = '' OR bill_control IS NULL OR bill_control = '')",
            sql,
        )
        self.assertIn("is_cancelled = 0", sql)


class TestBackfillVoucherType(unittest.TestCase):
    """_backfill_voucher_type: paginación, frontera de 500, commit por lote y rollback."""

    _SOURCE = {
        "voucher_type": "Sales Invoice",
        "table": "tabSales Invoice",
        "bill_no_field": "bill_no",
        "bill_control_field": "bill_control",
    }

    def _run(self, pages, update_return=None, update_side_effect=None):
        """pages: lista de páginas (cada una list[dict]) que devuelve el SELECT."""
        with patch(f"{_PATH}.frappe") as mock_frappe, \
             patch(f"{_PATH}._update_gl_entries_batch") as mock_update:
            mock_frappe.db.sql.side_effect = pages
            if update_side_effect is not None:
                mock_update.side_effect = update_side_effect
            else:
                mock_update.side_effect = update_return or [len(p) for p in pages if p]
            try:
                total = bf._backfill_voucher_type(self._SOURCE)
                raised = None
            except Exception as e:  # noqa: BLE001
                total, raised = None, e
        return total, mock_frappe, mock_update, raised

    def test_single_page_below_limit(self):
        page = [_inv(f"SI-{i}", bill_no=f"A-{i}") for i in range(300)]
        total, mf, mu, _ = self._run([page], update_return=[300])
        self.assertEqual(total, 300)
        self.assertEqual(mf.db.sql.call_count, 1)      # un solo SELECT
        self.assertEqual(mu.call_count, 1)
        self.assertEqual(mf.db.commit.call_count, 1)   # un commit por lote

    def test_multiple_pages_with_offset(self):
        p1 = [_inv(f"A-{i}", bill_no="x") for i in range(500)]
        p2 = [_inv(f"B-{i}", bill_no="x") for i in range(500)]
        p3 = [_inv(f"C-{i}", bill_no="x") for i in range(120)]
        total, mf, mu, _ = self._run([p1, p2, p3], update_return=[500, 500, 120])
        self.assertEqual(total, 1120)
        self.assertEqual(mf.db.sql.call_count, 3)
        self.assertEqual(mf.db.commit.call_count, 3)
        # OFFSET incrementa en BATCH_SIZE (0, 500, 1000)
        sqls = [c.args[0] for c in mf.db.sql.call_args_list]
        self.assertIn("OFFSET 0", sqls[0])
        self.assertIn("OFFSET 500", sqls[1])
        self.assertIn("OFFSET 1000", sqls[2])

    def test_exact_multiple_of_limit_no_infinite_loop(self):
        """Página de exactamente 500 → corta con la página vacía siguiente, no en bucle."""
        full = [_inv(f"A-{i}", bill_no="x") for i in range(500)]
        total, mf, mu, _ = self._run([full, []], update_return=[500])
        self.assertEqual(total, 500)
        self.assertEqual(mf.db.sql.call_count, 2)   # SELECT lleno + SELECT vacío
        self.assertEqual(mu.call_count, 1)          # solo el lote lleno se actualiza
        self.assertEqual(mf.db.commit.call_count, 1)

    def test_no_invoices(self):
        total, mf, mu, _ = self._run([[]])
        self.assertEqual(total, 0)
        mu.assert_not_called()
        mf.db.commit.assert_not_called()

    def test_rollback_and_reraise_on_error(self):
        page = [_inv("SI-1", bill_no="A-1")]
        total, mf, mu, raised = self._run(
            [page], update_side_effect=RuntimeError("boom")
        )
        self.assertIsInstance(raised, RuntimeError)
        mf.db.rollback.assert_called_once()
        mf.db.commit.assert_not_called()
        _args, kwargs = mf.log_error.call_args
        self.assertEqual(kwargs.get("title"), "Backfill GL Entry Bill Fields Error")


class TestExecute(unittest.TestCase):
    """execute: itera VOUCHER_SOURCES y suma los resultados por source."""

    def test_runs_each_source_and_sums(self):
        with patch(f"{_PATH}.frappe") as mock_frappe, \
             patch(f"{_PATH}._backfill_voucher_type") as mock_bf:
            mock_bf.side_effect = [5, 7, 0, 0, 0, 0]
            bf.execute()
        self.assertEqual(mock_bf.call_count, len(bf.VOUCHER_SOURCES))
        called_types = [c.args[0]["voucher_type"] for c in mock_bf.call_args_list]
        self.assertEqual(
            called_types,
            [
                "Sales Invoice",
                "Purchase Invoice",
                "VE Sales Credit Note",
                "VE Sales Debit Note",
                "VE Purchase Credit Note",
                "VE Purchase Debit Note",
            ],
        )
        # el log final reporta el total acumulado (5 + 7 = 12)
        logged = " ".join(str(c.args[0]) for c in mock_frappe.log.call_args_list)
        self.assertIn("12", logged)


if __name__ == "__main__":
    unittest.main()
