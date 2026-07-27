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

import base64
from io import BytesIO

from openpyxl import load_workbook

from l10n_ve.l10n_ve.report.ve_sales_invoices_hq import excel_export as xls
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq import ve_sales_invoices_hq as hq

FILTROS: dict = {
    "company": "ACME",
    "from_date": "2026-07-01",
    "to_date": "2026-07-31",
}


def como_dicts(columns: list, data: list) -> list:
    """Rearma las filas igual que Frappe en el navegador.

    ``execute`` devuelve las filas como lista para no repetir el nombre de cada
    campo en cada una (ver el comentario allí). Este helper hace el mismo mapeo
    posicional que ``prepare_data`` de query_report.js, así que además de
    permitir aserciones legibles verifica que el orden columna↔valor coincida:
    si se descolocara, los tests fallarían.
    """
    fieldnames = [c["fieldname"] for c in columns]
    return [dict(zip(fieldnames, row)) for row in data]


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
            patch.object(hq, "_get_main_branch_map", return_value={"A": "MIR-01"}),
        )

    def test_sin_rollup_no_recorta_filas(self) -> None:
        main = [{"branch": "A"}, {"branch": "B"}]
        parches = self._parchear(main, [{"branch": "C"}], None)
        with parches[0], parches[1], parches[2] as total_row, parches[3], parches[4], parches[5], parches[6]:
            columns, filas, _, _, _ = hq.execute(dict(FILTROS))

        data = como_dicts(columns, filas)

        self.assertEqual(len(data), 3)                      # nada se recorta
        total_row.assert_called_once_with(main)             # totales sobre las del período

    def test_rollup_recorta_filas_y_totales(self) -> None:
        """El total debe calcularse sobre lo RECORTADO, no sobre todo."""
        main = [{"branch": "A"}, {"branch": "B"}, {"branch": "FUERA"}]
        adjustment = [{"branch": "A"}, {"branch": "FUERA"}]
        parches = self._parchear(main, adjustment, {"A", "B"})
        with parches[0], parches[1], parches[2] as total_row, parches[3], parches[4], parches[5], parches[6]:
            columns, filas, _, _, _ = hq.execute({**FILTROS, "branch": "PADRE"})

        data = como_dicts(columns, filas)

        self.assertTrue(all(r["branch"] in {"A", "B"} for r in data))
        self.assertEqual(len(data), 3)                      # 2 del período + 1 de ajuste
        # clave: el total se calcula SOLO con las filas del subárbol
        # (las filas se enriquecen in place, así que se comparan las sucursales)
        filas_del_total = total_row.call_args[0][0]
        self.assertEqual([r["branch"] for r in filas_del_total], ["A", "B"])

    def test_agrega_las_columnas_hq(self) -> None:
        parches = self._parchear([{"branch": "A", "fiscal_series": "MIR-01", "bill_no": "9"}], [], None)
        with parches[0], parches[1], parches[2], parches[3], parches[4], parches[5], parches[6]:
            columns, filas, _, _, _ = hq.execute(dict(FILTROS))

        data = como_dicts(columns, filas)

        self.assertEqual(data[0]["fiscal_document_no"], "MIR-01-9")
        self.assertEqual(data[0]["municipality"], "Plaza")
        self.assertEqual(data[0]["main_branch"], "MIR-01")
        self.assertIn("municipality", [c.get("fieldname") for c in columns])
        self.assertIn("fiscal_document_no", [c.get("fieldname") for c in columns])
        campos = [c.get("fieldname") for c in columns]
        # orden: Sucursal -> Sucursal Principal -> Municipio
        self.assertLess(campos.index("branch"), campos.index("main_branch"))
        self.assertLess(campos.index("main_branch"), campos.index("municipality"))

    def test_valida_filtros_obligatorios(self) -> None:
        for faltante in ("company", "from_date", "to_date"):
            f = dict(FILTROS)
            f.pop(faltante)
            with self.assertRaises(frappe.exceptions.ValidationError):
                hq.execute(f)

    def test_rechaza_rango_invertido(self) -> None:
        with self.assertRaises(frappe.exceptions.ValidationError):
            hq.execute({**FILTROS, "from_date": "2026-07-31", "to_date": "2026-07-01"})

    def test_filas_como_lista_en_orden_de_columnas(self) -> None:
        """El contrato con el navegador: listas mapeadas por posición."""
        parches = self._parchear([{"branch": "A", "fiscal_series": "S", "bill_no": "1"}], [], None)
        with parches[0], parches[1], parches[2], parches[3], parches[4], parches[5], parches[6]:
            columns, filas, _, _, _ = hq.execute(dict(FILTROS))

        self.assertIsInstance(filas[0], list)
        self.assertEqual(len(filas[0]), len(columns))
        # El valor de cada posición corresponde a SU columna, no a otra.
        self.assertEqual(filas[0][[c["fieldname"] for c in columns].index("branch")], "A")


class TestDropEmptyNumericColumns(unittest.TestCase):
    """Solo se ocultan columnas numéricas y solo si el período las trae vacías."""

    COLUMNAS: list = [
        {"fieldname": "branch", "label": "Sucursal", "fieldtype": "Data"},
        {"fieldname": "municipality", "label": "Municipio", "fieldtype": "Data"},
        {"fieldname": "con_datos", "label": "Con datos", "fieldtype": "Currency"},
        {"fieldname": "en_cero", "label": "En cero", "fieldtype": "Currency"},
        {"fieldname": "sin_valor", "label": "Sin valor", "fieldtype": "Percent"},
    ]

    def test_oculta_las_numericas_vacias(self) -> None:
        filas = [
            {"branch": "A", "municipality": "Plaza", "con_datos": 10.0, "en_cero": 0.0},
            {"branch": "B", "municipality": "Plaza", "con_datos": 5.0, "en_cero": 0},
        ]
        columns, ocultas = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertEqual(ocultas, ["En cero", "Sin valor"])
        self.assertEqual(
            [c["fieldname"] for c in columns], ["branch", "municipality", "con_datos"]
        )

    def test_nunca_oculta_columnas_de_identidad(self) -> None:
        """Municipio está vacío en 26 de 28 sucursales: aun así debe quedarse."""
        filas = [{"branch": "A", "municipality": "", "con_datos": 1.0}]
        columns, ocultas = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertIn("municipality", [c["fieldname"] for c in columns])
        self.assertNotIn("Municipio", ocultas)

    def test_sin_filas_no_oculta_nada(self) -> None:
        """Con cero filas 'todo vacío' es cierto y se llevaría todas por delante."""
        columns, ocultas = hq._drop_empty_numeric_columns(self.COLUMNAS, [])

        self.assertEqual(columns, self.COLUMNAS)
        self.assertEqual(ocultas, [])

    def test_no_toca_las_columnas_si_todas_tienen_datos(self) -> None:
        filas = [{"branch": "A", "con_datos": 1.0, "en_cero": 2.0, "sin_valor": 3.0}]
        columns, ocultas = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertEqual(columns, self.COLUMNAS)
        self.assertEqual(ocultas, [])

    def test_el_mensaje_avisa_de_las_ocultas(self) -> None:
        mensaje = hq._build_report_message("", None, "", ["En cero", "Sin valor"])

        self.assertIn("2 columnas sin datos", mensaje)
        self.assertIn("En cero, Sin valor", mensaje)
        self.assertIn("Excel", mensaje)  # dice dónde sí están


ARBOL: list = [
    frappe._dict(name="RAIZ", parent_ve_branch=None),
    frappe._dict(name="MIR-01", parent_ve_branch="RAIZ"),
    frappe._dict(name="GUARENAS", parent_ve_branch="MIR-01"),
    frappe._dict(name="ARMANDO", parent_ve_branch="GUARENAS"),
    frappe._dict(name="ARA-02", parent_ve_branch="RAIZ"),
]


class TestMainBranchMap(unittest.TestCase):
    """Sucursal Principal = el ancestro que cuelga directo de la raíz."""

    @patch("frappe.get_all", return_value=ARBOL)
    def test_nieta_sube_hasta_el_nivel_1(self, _a) -> None:
        # ARMANDO -> GUARENAS -> MIR-01 -> RAIZ  =>  MIR-01
        self.assertEqual(hq._get_main_branch_map()["ARMANDO"], "MIR-01")

    @patch("frappe.get_all", return_value=ARBOL)
    def test_hija_directa_se_apunta_a_si_misma(self, _a) -> None:
        m = hq._get_main_branch_map()
        self.assertEqual(m["ARA-02"], "ARA-02")
        self.assertEqual(m["MIR-01"], "MIR-01")

    @patch("frappe.get_all", return_value=ARBOL)
    def test_la_raiz_se_apunta_a_si_misma(self, _a) -> None:
        # así la columna nunca queda vacía
        self.assertEqual(hq._get_main_branch_map()["RAIZ"], "RAIZ")

    @patch("frappe.get_all", return_value=[
        frappe._dict(name="A", parent_ve_branch="B"),
        frappe._dict(name="B", parent_ve_branch="A"),
    ])
    def test_arbol_con_ciclo_no_cuelga(self, _a) -> None:
        # defensivo: un árbol corrupto no debe colgar el reporte
        self.assertEqual(hq._get_main_branch_map()["A"], "A")


class TestMainBranchFilter(unittest.TestCase):
    """Filtro 'Sucursal Principal': equivale al subárbol de esa sucursal."""

    def _parchear(self, main, subtree_side_effect):
        return (
            patch.object(hq, "_sales_book_columns", return_value=[{"fieldname": "branch"}]),
            patch.object(hq, "_sales_book_data", return_value=(main, [])),
            patch.object(hq, "_sales_book_total_row", return_value={"t": 1}),
            patch.object(hq, "_sales_book_report_summary", return_value=[]),
            patch.object(hq, "_get_branch_subtree", side_effect=subtree_side_effect),
            patch.object(hq, "_get_municipality_by_branch", return_value={}),
            patch.object(hq, "_get_main_branch_map", return_value={}),
        )

    def test_filtra_por_el_subarbol_de_la_principal(self) -> None:
        main = [{"branch": "HIJA"}, {"branch": "NIETA"}, {"branch": "AJENA"}]
        # sin filtro de sucursal -> None; para la principal -> su subárbol
        pa = self._parchear(main, [None, {"MIR-01", "HIJA", "NIETA"}])
        with pa[0], pa[1], pa[2] as total_row, pa[3], pa[4], pa[5], pa[6]:
            columns, filas, _, _, _ = hq.execute({**FILTROS, "main_branch": "MIR-01"})

        data = como_dicts(columns, filas)

        self.assertEqual([r["branch"] for r in data], ["HIJA", "NIETA"])
        # y los totales solo con lo que quedó
        self.assertEqual([r["branch"] for r in total_row.call_args[0][0]], ["HIJA", "NIETA"])

    def test_se_intersecta_con_el_filtro_de_sucursal(self) -> None:
        """Principal MIR-01 + sucursal de otro árbol => sin resultados."""
        main = [{"branch": "HIJA"}, {"branch": "AJENA"}]
        # subárbol de la sucursal pedida, y luego el de la principal
        pa = self._parchear(main, [{"AJENA", "OTRA"}, {"MIR-01", "HIJA"}])
        with pa[0], pa[1], pa[2], pa[3], pa[4], pa[5], pa[6]:
            columns, filas, _, _, _ = hq.execute({**FILTROS, "branch": "DC-02", "main_branch": "MIR-01"})

        data = como_dicts(columns, filas)

        self.assertEqual(data, [])

    def test_principal_sin_hijas_se_filtra_a_si_misma(self) -> None:
        """ARA-02 y compañía no tienen descendientes: subtree devuelve None."""
        main = [{"branch": "ARA-02"}, {"branch": "OTRA"}]
        pa = self._parchear(main, [None, None])
        with pa[0], pa[1], pa[2], pa[3], pa[4], pa[5], pa[6]:
            columns, filas, _, _, _ = hq.execute({**FILTROS, "main_branch": "ARA-02"})

        data = como_dicts(columns, filas)

        self.assertEqual([r["branch"] for r in data], ["ARA-02"])

    def test_el_libro_no_recibe_el_filtro_propio(self) -> None:
        """'main_branch' no existe en sales_book: no debe llegarle."""
        pa = self._parchear([], [None, {"X"}])
        with pa[0], pa[1] as datos, pa[2], pa[3], pa[4], pa[5], pa[6]:
            hq.execute({**FILTROS, "main_branch": "MIR-01"})

        self.assertNotIn("main_branch", datos.call_args[0][0])


class TestReportMessage(unittest.TestCase):
    """La descripción que se pinta sobre el reporte (bajo los filtros)."""

    def test_describe_el_reporte(self) -> None:
        msg = hq._build_report_message("", None)
        self.assertIn("Libro de Ventas", msg)
        self.assertIn("MIR-01-4779", msg)       # ejemplo del formato SERIE-NUMERO

    def test_indica_la_consolidacion_por_principal(self) -> None:
        msg = hq._build_report_message("", None, "MIR-01")
        self.assertIn("sucursal principal", msg)
        self.assertIn("MIR-01", msg)

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


class TestExcelExport(unittest.TestCase):
    """Exportación a Excel: en memoria, sin tocar disco."""

    def test_nombre_de_archivo_con_el_rango(self) -> None:
        nombre = xls._build_filename({"from_date": "2026-02-01", "to_date": "2026-07-31"})
        self.assertEqual(nombre, "Facturas_Venta_HQ_20260201_20260731.xlsx")

    def test_nombre_sin_fechas_no_revienta(self) -> None:
        self.assertTrue(xls._build_filename({}).endswith(".xlsx"))

    def test_ancho_auto_no_rompe(self) -> None:
        """Las columnas del libro traen width='auto' (string), no un número."""
        self.assertEqual(xls._as_number("auto"), 0.0)
        self.assertEqual(xls._as_number(None), 0.0)
        self.assertEqual(xls._as_number(120), 120.0)

    def test_exige_el_rol_del_reporte(self) -> None:
        """El endpoint es invocable por si solo: sin el chequeo, cualquiera
        podria bajarse la facturacion completa saltandose el rol."""
        with patch("frappe.only_for", side_effect=frappe.PermissionError) as guard:
            with self.assertRaises(frappe.PermissionError):
                xls.download_hq_excel({})
        guard.assert_called_once()

    def test_genera_en_memoria_y_no_escribe_en_disco(self) -> None:
        columnas = [{"fieldname": "branch", "label": "Sucursal", "fieldtype": "Data", "width": "auto"}]
        filas = [{"branch": "MIR-01"}, {"branch": "DC-02"}]
        # Se parchea get_hq_data y no execute: el Excel sale del núcleo a
        # propósito, para llevar SIEMPRE las columnas completas del libro.
        with patch("frappe.only_for"), patch.object(
            xls, "get_hq_data",
            return_value={"columns": columnas, "main_data": filas, "adjustment_data": [],
                          "report_summary": [{"label": "Total", "value": 1}]},
        ):
            res = xls.download_hq_excel({"from_date": "2026-07-01", "to_date": "2026-07-31"})

        self.assertEqual(res["type"], "download")
        # base64 valido y con firma de xlsx (PK: es un zip)
        crudo = base64.b64decode(res["filecontent"])
        self.assertTrue(crudo.startswith(b"PK"))

        libro = load_workbook(BytesIO(crudo))
        self.assertEqual(libro.sheetnames, [xls.SHEET_DATA, xls.SHEET_SUMMARY])
        hoja = libro[xls.SHEET_DATA]
        self.assertEqual(hoja["A1"].value, "Sucursal")
        self.assertEqual([c[0].value for c in hoja.iter_rows(min_row=2)], ["MIR-01", "DC-02"])
        self.assertEqual(hoja.freeze_panes, "A2")   # encabezado fijo al hacer scroll

    def test_sin_resumen_no_agrega_la_hoja(self) -> None:
        with patch("frappe.only_for"), patch.object(
            xls, "get_hq_data",
            return_value={"columns": [{"fieldname": "branch", "label": "S"}], "main_data": [],
                          "adjustment_data": [], "report_summary": []},
        ):
            res = xls.download_hq_excel({})
        libro = load_workbook(BytesIO(base64.b64decode(res["filecontent"])))
        self.assertEqual(libro.sheetnames, [xls.SHEET_DATA])


if __name__ == "__main__":
    unittest.main()
