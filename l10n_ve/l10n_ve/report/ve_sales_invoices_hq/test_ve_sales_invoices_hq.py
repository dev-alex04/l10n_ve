# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Blindaje del reporte HQ (Fase 1): garantizar que es un passthrough puro del
Libro de Ventas y que NO altera su salida fiscal.

En la Fase 2 (columnas) este test evoluciona a comparar TOTALES: se permitirán
columnas extra, pero el ``report_summary`` / total del HQ debe seguir siendo
idéntico al del ``sales_book`` para los mismos filtros.
"""

import unittest
from unittest.mock import patch

from l10n_ve.l10n_ve.report.ve_sales_invoices_hq import ve_sales_invoices_hq as hq


class TestVESalesInvoicesHQ(unittest.TestCase):
    def test_execute_is_passthrough_of_sales_book(self):
        """El wrapper debe devolver, sin alterar, lo que produce sales_book."""
        sentinel = (
            [{"fieldname": "x"}],                  # columns
            [{"x": 1}, {"x": 2}],                  # data
            None,                                  # message
            None,                                  # chart
            [{"label": "Total", "value": 42}],     # report_summary (total del libro)
        )
        filters = {
            "company": "ACME",
            "from_date": "2026-07-01",
            "to_date": "2026-07-31",
        }

        with patch.object(hq, "_sales_book_execute", return_value=sentinel) as mocked:
            result = hq.execute(filters)

        # Reusa el cálculo del libro (una sola verdad fiscal) y no lo modifica.
        mocked.assert_called_once_with(filters)
        self.assertEqual(result, sentinel)


if __name__ == "__main__":
    unittest.main()
