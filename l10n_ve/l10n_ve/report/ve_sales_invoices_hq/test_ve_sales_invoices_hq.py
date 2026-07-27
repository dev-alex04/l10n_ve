# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Tests del Reporte HQ de facturas de venta.

Blindaje central: el HQ **no puede alterar el cálculo fiscal del Libro de
Ventas**. Solo agrega columnas (documento fiscal, municipio) y el rollup
padre-hijo, y en ese caso los totales deben recalcularse SOBRE LAS FILAS
RECORTADAS con las propias funciones del libro.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.l10n_ve.report.ve_sales_invoices_hq import ve_sales_invoices_hq as hq

FILTROS: dict = {
    "company": "ACME",
    "from_date": "2026-07-01",
    "to_date": "2026-07-31",
}


class TestFormatFiscalDocumentNo(unittest.TestCase):
    """Serie + número concatenados (lo que contabilidad pegaba a mano)."""

    def test_concatena_serie_y_numero(self) -> None:
        self.assertEqual(hq._format_fiscal_document_no("MIR-01", "4779"), "MIR-01-4779")

    def test_solo_serie(self) -> None:
        self.assertEqual(hq._format_fiscal_document_no("MIR-01", None), "MIR-01")

    def test_solo_numero(self) -> None:
        self.assertEqual(hq._format_fiscal_document_no("", "4779"), "4779")

    def test_sin_datos(self) -> None:
        self.assertEqual(hq._format_fiscal_document_no(None, None), "")

    def test_ignora_espacios(self) -> None:
        self.assertEqual(hq._format_fiscal_document_no(" MIR-01 ", " 4779 "), "MIR-01-4779")


class TestInsertColumnAfter(unittest.TestCase):
    def test_inserta_despues_de_la_columna(self) -> None:
        cols = [{"fieldname": "a"}, {"fieldname": "b"}]
        hq._insert_column_after(cols, "a", {"fieldname": "nueva"})
        self.assertEqual([c["fieldname"] for c in cols], ["a", "nueva", "b"])

    def test_agrega_al_final_si_no_existe(self) -> None:
        cols = [{"fieldname": "a"}]
        hq._insert_column_after(cols, "inexistente", {"fieldname": "nueva"})
        self.assertEqual([c["fieldname"] for c in cols], ["a", "nueva"])


class TestBranchSubtree(unittest.TestCase):
    """El rollup solo aplica a sucursales con descendientes."""

    def test_sin_sucursal_no_hay_rollup(self) -> None:
        self.assertIsNone(hq._get_branch_subtree(None))

    @patch("frappe.get_all", return_value=["HOJA"])
    @patch("frappe.db.get_value", return_value=frappe._dict(lft=4, rgt=5))
    def test_hoja_no_hace_rollup(self, _v, _a) -> None:
        # Una sola coincidencia (ella misma) -> conviene el filtro SQL del libro.
        self.assertIsNone(hq._get_branch_subtree("HOJA"))

    @patch("frappe.get_all", return_value=["PADRE", "HIJA"])
    @patch("frappe.db.get_value", return_value=frappe._dict(lft=2, rgt=19))
    def test_grupo_devuelve_subarbol(self, _v, _a) -> None:
        self.assertEqual(hq._get_branch_subtree("PADRE"), {"PADRE", "HIJA"})


class TestExecute(unittest.TestCase):
    """Contrato con el Libro de Ventas."""

    def _parchear(self, main, adjustment, subtree):
        """Parchea las piezas del libro; devuelve los mocks relevantes."""
        return (
            patch.object(hq, "_sales_book_columns", return_value=[{"fieldname": "branch"}]),
            patch.object(hq, "_sales_book_data", return_value=(main, adjustment)),
            patch.object(hq, "_sales_book_total_row", return_value={"t": 1}),
            patch.object(hq, "_sales_book_report_summary", return_value=[{"label": "Total"}]),
            patch.object(hq, "_get_branch_subtree", return_value=subtree),
            patch.object(hq, "_get_municipality_by_branch", return_value={"A": "Plaza"}),
        )

    def test_sin_rollup_no_recorta_filas(self) -> None:
        main = [{"branch": "A"}, {"branch": "B"}]
        parches = self._parchear(main, [{"branch": "C"}], None)
        with parches[0], parches[1], parches[2] as total_row, parches[3], parches[4], parches[5]:
            _, data, _, _, _ = hq.execute(dict(FILTROS))

        self.assertEqual(len(data), 3)                      # nada se recorta
        total_row.assert_called_once_with(main)             # totales sobre las del período

    def test_rollup_recorta_filas_y_totales(self) -> None:
        """El total debe calcularse sobre lo RECORTADO, no sobre todo."""
        main = [{"branch": "A"}, {"branch": "B"}, {"branch": "FUERA"}]
        adjustment = [{"branch": "A"}, {"branch": "FUERA"}]
        parches = self._parchear(main, adjustment, {"A", "B"})
        with parches[0], parches[1], parches[2] as total_row, parches[3], parches[4], parches[5]:
            _, data, _, _, _ = hq.execute({**FILTROS, "branch": "PADRE"})

        self.assertTrue(all(r["branch"] in {"A", "B"} for r in data))
        self.assertEqual(len(data), 3)                      # 2 del período + 1 de ajuste
        # clave: el total se calcula SOLO con las filas del subárbol
        # (las filas se enriquecen in place, así que se comparan las sucursales)
        filas_del_total = total_row.call_args[0][0]
        self.assertEqual([r["branch"] for r in filas_del_total], ["A", "B"])

    def test_agrega_las_columnas_hq(self) -> None:
        parches = self._parchear([{"branch": "A", "fiscal_series": "MIR-01", "bill_no": "9"}], [], None)
        with parches[0], parches[1], parches[2], parches[3], parches[4], parches[5]:
            columns, data, _, _, _ = hq.execute(dict(FILTROS))

        self.assertEqual(data[0]["fiscal_document_no"], "MIR-01-9")
        self.assertEqual(data[0]["municipality"], "Plaza")
        self.assertIn("municipality", [c.get("fieldname") for c in columns])
        self.assertIn("fiscal_document_no", [c.get("fieldname") for c in columns])

    def test_valida_filtros_obligatorios(self) -> None:
        for faltante in ("company", "from_date", "to_date"):
            f = dict(FILTROS)
            f.pop(faltante)
            with self.assertRaises(frappe.exceptions.ValidationError):
                hq.execute(f)

    def test_rechaza_rango_invertido(self) -> None:
        with self.assertRaises(frappe.exceptions.ValidationError):
            hq.execute({**FILTROS, "from_date": "2026-07-31", "to_date": "2026-07-01"})


class TestReportMessage(unittest.TestCase):
    """La descripción que se pinta sobre el reporte (bajo los filtros)."""

    def test_describe_el_reporte(self) -> None:
        msg = hq._build_report_message("", None)
        self.assertIn("Libro de Ventas", msg)
        self.assertIn("MIR-01-4779", msg)       # ejemplo del formato SERIE-NUMERO

    def test_sin_rollup_no_lista_sucursales(self) -> None:
        self.assertNotIn("Mostrando", hq._build_report_message("HOJA", None))

    def test_con_rollup_hace_visible_el_subarbol(self) -> None:
        """Sin esto el usuario ve más filas de las que espera y no sabe por qué."""
        msg = hq._build_report_message("PADRE", {"PADRE", "HIJA_A", "HIJA_B"})
        self.assertIn("PADRE", msg)
        self.assertIn("HIJA_A", msg)
        self.assertIn("HIJA_B", msg)
        self.assertIn("2", msg)                 # cuenta solo las dependientes
        # la propia sucursal no se lista como dependiente de sí misma
        self.assertNotIn("PADRE,", msg)


if __name__ == "__main__":
    unittest.main()
