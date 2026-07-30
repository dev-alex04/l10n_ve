# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la exportación a Excel del Reporte HQ.

Cubre las dos cosas que se rompieron al pasar el export a ``ExcelBuilder``:

1. La fila de Totales no incluía las columnas consolidadas del HQ. ``get_total_row``
   es del Libro de Ventas y arma un dict fijo sin ``taxable_amount`` ni ``total_vat``,
   así que las dos columnas que se agregaron "para facilitar la revisión" salían
   vacías justo en los Totales.
2. El nombre de hoja se recortaba a 31 caracteres pero no se limpiaban los caracteres
   que Excel prohíbe (``: \\ / ? * [ ]``), que hacen fallar el guardado.
"""

import unittest

from l10n_ve.l10n_ve.report.sales_book.excel_builder import _sanitize_sheet_title
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.excel_export import _build_summary_data
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq import (
    TAXABLE_BASE_FIELDS,
    VAT_AMOUNT_FIELDS,
    sum_consolidated,
)


def _row(**overrides):
    """Fila del libro con las 12 columnas por alícuota en cero, salvo lo que se pise."""
    row = {field: 0.0 for field in TAXABLE_BASE_FIELDS + VAT_AMOUNT_FIELDS}
    row.update({"grand_total": 0.0, "total_exempt": 0.0, "iva_retained": 0.0,
                "total_igtf": 0.0, "base_amount_igtf": 0.0})
    row.update(overrides)
    return row


class TestSumConsolidated(unittest.TestCase):
    def test_none_and_empty_count_as_zero(self):
        row = _row(base_general_taxpayer=100.0)
        row["base_reduced_taxpayer"] = None
        row["base_additional_taxpayer"] = ""
        self.assertEqual(sum_consolidated(row, TAXABLE_BASE_FIELDS), 100.0)

    def test_sums_every_rate_and_group(self):
        row = _row(**{field: 10.0 for field in TAXABLE_BASE_FIELDS})
        self.assertEqual(sum_consolidated(row, TAXABLE_BASE_FIELDS), 60.0)


class TestBuildSummaryData(unittest.TestCase):
    def test_totals_include_consolidated_columns(self):
        data = [
            _row(base_general_taxpayer=100.0, iva_general_taxpayer=16.0),
            _row(base_reduced_non_taxpayer=200.0, iva_reduced_non_taxpayer=16.0),
        ]
        totals = _build_summary_data(data)
        self.assertEqual(totals["taxable_amount"], 300.0)
        self.assertEqual(totals["total_vat"], 32.0)

    def test_consolidated_totals_match_the_per_rate_totals(self):
        """Los consolidados se derivan de los mismos totales por alícuota, no de otra pasada."""
        data = [_row(base_general_taxpayer=100.0, base_additional_non_taxpayer=50.0,
                     iva_general_taxpayer=16.0)]
        totals = _build_summary_data(data)
        self.assertEqual(totals["taxable_amount"], sum_consolidated(totals, TAXABLE_BASE_FIELDS))
        self.assertEqual(totals["total_vat"], sum_consolidated(totals, VAT_AMOUNT_FIELDS))

    def test_empty_data_returns_empty_totals(self):
        """Sin filas get_total_row devuelve {}: no hay que inventarle claves en cero."""
        self.assertEqual(_build_summary_data([]), {})

    def test_void_rows_do_not_count(self):
        """Las anuladas se listan en cero y no entran en los totales (requisito SENIAT)."""
        data = [
            _row(base_general_taxpayer=100.0, iva_general_taxpayer=16.0),
            _row(base_general_taxpayer=999.0, iva_general_taxpayer=999.0, is_void=1),
        ]
        totals = _build_summary_data(data)
        self.assertEqual(totals["taxable_amount"], 100.0)
        self.assertEqual(totals["total_vat"], 16.0)


class TestSanitizeSheetTitle(unittest.TestCase):
    def test_strips_characters_excel_rejects(self):
        clean = _sanitize_sheet_title("Ventas 2026/07 [HQ]: parte*1?")
        for forbidden in ":\\/?*[]":
            self.assertNotIn(forbidden, clean)

    def test_truncates_to_excel_limit(self):
        self.assertEqual(len(_sanitize_sheet_title("A" * 60)), 31)

    def test_empty_title_falls_back_to_caller_default(self):
        self.assertEqual(_sanitize_sheet_title(None), "")
        self.assertEqual(_sanitize_sheet_title(""), "")


if __name__ == "__main__":
    unittest.main()
