# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la carga de patches post-DB (l10n_ve.patches.monkey_patches).

Regresión del Error Log "Report Error" / "Failed to send Antigüedad de
Saldos (Vencimiento) Auto Email Report" (builtins.IndexError: list index
out of range): los patches de reportes solo quedaban aplicados en el
proceso de after_install/after_migrate, así que los workers web/RQ
ejecutaban el reporte core de ERPNext sin parchear y el Auto Email Report
fallaba todas las noches.

- ensure_post_db_patches() no hace nada sin conexión a BD (import temprano).
- Con BD disponible aplica los patches exactamente una vez por proceso.
- custom_execute del reporte "Payment Period Based On Invoice Date"
  rellena las filas cortas (sin delay_in_payment) para que ninguna fila
  tenga menos elementos que columnas, que es lo que dispara el IndexError
  en frappe.desk.query_report.normalize_result.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.patches import monkey_patches


class TestEnsurePostDbPatches(unittest.TestCase):
    def setUp(self):
        self._original_flag = monkey_patches._post_db_patches_applied

    def tearDown(self):
        monkey_patches._post_db_patches_applied = self._original_flag

    @patch.object(monkey_patches, "apply_post_db_patches")
    def test_skips_without_db_connection(self, mock_apply):
        """Sin BD (import temprano del paquete) no debe intentar aplicar."""
        monkey_patches._post_db_patches_applied = False

        with patch.object(frappe.local, "db", None, create=True):
            monkey_patches.ensure_post_db_patches()

        mock_apply.assert_not_called()
        self.assertFalse(monkey_patches._post_db_patches_applied)

    @patch.object(monkey_patches, "apply_post_db_patches")
    def test_applies_once_with_db(self, mock_apply):
        """Con BD disponible aplica una sola vez aunque se llame varias veces."""
        monkey_patches._post_db_patches_applied = False

        with patch.object(frappe.local, "db", object(), create=True):
            monkey_patches.ensure_post_db_patches()
            monkey_patches.ensure_post_db_patches()

        mock_apply.assert_called_once()
        self.assertTrue(monkey_patches._post_db_patches_applied)

    @patch.object(monkey_patches, "apply_post_db_patches")
    def test_retries_after_db_becomes_available(self, mock_apply):
        """Si el primer intento fue sin BD, el siguiente hook sí aplica."""
        monkey_patches._post_db_patches_applied = False

        with patch.object(frappe.local, "db", None, create=True):
            monkey_patches.ensure_post_db_patches()
        mock_apply.assert_not_called()

        with patch.object(frappe.local, "db", object(), create=True):
            monkey_patches.ensure_post_db_patches()
        mock_apply.assert_called_once()


class TestPaymentPeriodReportPatch(unittest.TestCase):
    """custom_execute(): las filas cortas del reporte core se rellenan."""

    def test_short_rows_are_padded_to_column_count(self):
        if not getattr(frappe.local, "db", None):
            # El import del reporte core de ERPNext exige BD enlazada
            # (accounts_receivable.py llama frappe.db.type_map al importar);
            # es la misma razón por la que el patch no cargaba sin conexión.
            self.skipTest("Requiere contexto de site (ejecutar con bench run-tests).")

        from l10n_ve.patches.reports import (
            payment_period_based_on_invoice_date as report_patch,
        )

        columns = [
            {"fieldname": f"col_{i}", "label": f"Col {i}"} for i in range(16)
        ]
        # El reporte core omite delay_in_payment cuando la factura
        # referenciada no tiene due_date: fila de 15 elementos vs 16 columnas.
        short_row = ["Payment Entry", "ACC-PAY-0001"] + [None] * 13
        full_row = list(range(16))

        with (
            patch.object(
                report_patch,
                "original_execute",
                return_value=(columns, [short_row, full_row]),
            ),
            # _() requiere contexto de site; irrelevante para este test.
            patch.object(report_patch, "_", side_effect=lambda msg: msg),
        ):
            out_columns, out_data = report_patch.custom_execute({})

        self.assertEqual(len(out_data), 2)
        for row in out_data:
            self.assertEqual(len(row), len(out_columns))


if __name__ == "__main__":
    unittest.main()
