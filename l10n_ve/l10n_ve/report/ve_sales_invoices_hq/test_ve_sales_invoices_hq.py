# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Tests del Reporte HQ de facturas de venta.

Blindaje central: el HQ **no puede alterar el cálculo fiscal del Libro de
Ventas**. Solo agrega columnas (documento fiscal, municipio) y el rollup
padre-hijo, y en ese caso los totales deben recalcularse SOBRE LAS FILAS
RECORTADAS con las propias funciones del libro.
"""

import unittest
from unittest.mock import Mock, patch

import frappe

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


def _libro_falso(main, adjustment=None):
    """Doble de `_sales_book_data` que respeta `branches`, como hace el SQL real.

    El recorte por sucursal vive en la consulta (`AND branch IN %(branches)s`) y no
    en memoria: un doble que devolviera todo sin mirar los filtros daria por buenas
    cosas que en produccion no pasan.
    """
    adjustment = adjustment or []

    def _data(filters):
        permitidas = filters.get("branches")
        if permitidas is None:
            return list(main), list(adjustment)
        ok = set(permitidas)
        return (
            [r for r in main if r.get("branch") in ok],
            [r for r in adjustment if r.get("branch") in ok],
        )

    return _data


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
        self.assertIsNone(hq.get_branch_subtree(None))

    @patch("frappe.get_all", return_value=["HOJA"])
    @patch("frappe.db.get_value", return_value=frappe._dict(lft=4, rgt=5))
    def test_hoja_no_hace_rollup(self, _v, _a) -> None:
        # Una sola coincidencia (ella misma) -> conviene el filtro SQL del libro.
        self.assertIsNone(hq.get_branch_subtree("HOJA"))

    @patch("frappe.get_all", return_value=["PADRE", "HIJA"])
    @patch("frappe.db.get_value", return_value=frappe._dict(lft=2, rgt=19))
    def test_grupo_devuelve_subarbol(self, _v, _a) -> None:
        self.assertEqual(hq.get_branch_subtree("PADRE"), {"PADRE", "HIJA"})


class TestExecute(unittest.TestCase):
    """Contrato con el Libro de Ventas."""

    def _parchear(self, main, adjustment, subtree):
        """Parchea las piezas del libro; devuelve los mocks relevantes."""
        return (
            patch.object(hq, "_sales_book_columns", return_value=[{"fieldname": "branch"}]),
            patch.object(hq, "_sales_book_data", side_effect=_libro_falso(main, adjustment)),
            patch.object(hq, "_sales_book_total_row", return_value={"t": 1}),
            patch.object(hq, "_sales_book_report_summary", return_value=[{"label": "Total"}]),
            patch.object(hq, "get_branch_subtree", return_value=subtree),
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


class TestColumnTexts(unittest.TestCase):
    """Etiqueta legible y tooltip de cada encabezado."""

    def test_cuelga_el_tooltip(self) -> None:
        columnas = [{"fieldname": "branch"}, {"fieldname": "grand_total"}]
        hq._humanize_columns(columnas)

        self.assertTrue(all(c["description"] for c in columnas))

    def test_no_pisa_la_etiqueta_del_libro_sin_motivo(self) -> None:
        """Solo las doce de alícuota se reescriben; el resto queda como viene."""
        columnas = [{"fieldname": "branch", "label": "Sucursal"}]
        hq._humanize_columns(columnas)

        self.assertEqual(columnas[0]["label"], "Sucursal")

    def test_no_inventa_nada_para_columnas_desconocidas(self) -> None:
        columnas = [{"fieldname": "columna_que_no_existe"}]
        hq._humanize_columns(columnas)

        self.assertNotIn("description", columnas[0])
        self.assertNotIn("label", columnas[0])

    def test_las_doce_de_alicuota_se_generan(self) -> None:
        """Son la misma frase con dos variables; se generan para que no se
        desincronicen entre sí al retocar la redacción."""
        textos = hq._column_texts()

        for tasa in ("general", "reduced", "additional"):
            for grupo in ("taxpayer", "non_taxpayer"):
                self.assertIn(f"base_{tasa}_{grupo}", textos)
                self.assertIn(f"iva_{tasa}_{grupo}", textos)

        # El criterio del libro es la primera letra del RIF: debe decirlo.
        self.assertIn("V", textos["base_general_non_taxpayer"][1])
        self.assertIn("J", textos["base_general_taxpayer"][1])

    def test_las_etiquetas_no_llevan_abreviaturas(self) -> None:
        """El motivo del cambio: "C. G" no lo descifra nadie fuera de
        contabilidad. Ninguna etiqueta reescrita puede volver a abreviar."""
        columnas = [
            {"fieldname": f"{p}_{tasa}_{grupo}", "label": "vieja"}
            for p in ("base", "iva")
            for tasa in ("general", "reduced", "additional")
            for grupo in ("taxpayer", "non_taxpayer")
        ]
        hq._humanize_columns(columnas)

        for columna in columnas:
            self.assertNotIn("C.", columna["label"])
            self.assertTrue(
                columna["label"].endswith(("General", "Reducida", "Adicional")),
                f"la alícuota debe ir escrita: {columna['label']}",
            )
            self.assertIn("Contribuyente", columna["label"])

    def test_etiquetas_de_los_dos_grupos_se_distinguen(self) -> None:
        """'No Contribuyente' contiene 'Contribuyente': no pueden colisionar."""
        textos = hq._column_texts()

        self.assertEqual(
            textos["base_general_non_taxpayer"][0], "Base Imponible No Contribuyente General"
        )
        self.assertEqual(
            textos["base_general_taxpayer"][0], "Base Imponible Contribuyente General"
        )

    def test_ninguna_descripcion_huerfana(self) -> None:
        """Blindaje contra el typo: una clave que no corresponde a ninguna
        columna no falla en ningún lado, simplemente el tooltip nunca aparece."""
        # Mantener en sincronía con los `fieldname` que inserta `_add_hq_columns`
        # en ve_sales_invoices_hq.py. Si agregás una columna allá y su tooltip en
        # `_column_texts`, sumala acá o este test la reporta como huérfana.
        columnas_reales = {
            "branch", "main_branch", "municipality", "posting_date",
            "customer_tax_id", "customer_name", "customer_type", "fiscal_series",
            "fiscal_document_no", "bill_no", "bill_control", "credit_note_no",
            "debit_note_no", "affected_invoice_number", "transaction_type",
            "grand_total", "ve_fob", "total_exempt", "taxable_amount", "total_vat",
            "iva_retained", "vat_withholding_voucher_number", "withholding_date",
            "vat_withholding_rate", "base_amount_igtf", "igtf_rate", "total_igtf",
        } | {
            f"{p}_{tasa}_{grupo}"
            for p in ("base", "iva")
            for tasa in ("general", "reduced", "additional")
            for grupo in ("taxpayer", "non_taxpayer")
        }
        huerfanas = set(hq._column_texts()) - columnas_reales

        self.assertEqual(huerfanas, set(), f"fieldname inexistente: {huerfanas}")


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
        columns = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertEqual(
            [c["fieldname"] for c in columns], ["branch", "municipality", "con_datos"]
        )

    def test_nunca_oculta_columnas_de_identidad(self) -> None:
        """Municipio está vacío en 26 de 28 sucursales: aun así debe quedarse."""
        filas = [{"branch": "A", "municipality": "", "con_datos": 1.0}]
        columns = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertIn("municipality", [c["fieldname"] for c in columns])

    def test_sin_filas_no_oculta_nada(self) -> None:
        """Con cero filas 'todo vacío' es cierto y se llevaría todas por delante."""
        columns = hq._drop_empty_numeric_columns(self.COLUMNAS, [])

        self.assertEqual(columns, self.COLUMNAS)

    def test_no_toca_las_columnas_si_todas_tienen_datos(self) -> None:
        filas = [{"branch": "A", "con_datos": 1.0, "en_cero": 2.0, "sin_valor": 3.0}]
        columns = hq._drop_empty_numeric_columns(self.COLUMNAS, filas)

        self.assertEqual(columns, self.COLUMNAS)

    def test_el_mensaje_no_menciona_las_ocultas(self) -> None:
        """Se sacó el aviso a pedido: la descripción quedó demasiado larga y la
        lista de columnas en cero no le dice nada a quien lee el reporte."""
        mensaje = hq._build_report_message("", None, "")

        self.assertNotIn("ocultaron", mensaje)
        self.assertNotIn("sin datos en este período", mensaje)


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
            patch.object(hq, "_sales_book_data", side_effect=_libro_falso(main)),
            patch.object(hq, "_sales_book_total_row", return_value={"t": 1}),
            patch.object(hq, "_sales_book_report_summary", return_value=[]),
            patch.object(hq, "get_branch_subtree", side_effect=subtree_side_effect),
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
    """Exportación a Excel: el endpoint encola; el libro lo arma ExcelBuilder
    (cubierto en l10n_ve/tests/test_hq_excel_export.py)."""

    def test_nombre_de_archivo_con_el_rango(self) -> None:
        nombre = xls._build_filename({"from_date": "2026-02-01", "to_date": "2026-07-31"})
        self.assertEqual(nombre, "Facturas_Venta_HQ_20260201_20260731.xlsx")

    def test_nombre_sin_fechas_no_revienta(self) -> None:
        self.assertTrue(xls._build_filename({}).endswith(".xlsx"))

    def test_exige_el_rol_del_reporte(self) -> None:
        """El endpoint es invocable por si solo: sin el chequeo, cualquiera
        podria bajarse la facturacion completa saltandose el rol."""
        with patch("frappe.only_for", side_effect=frappe.PermissionError) as guard:
            with self.assertRaises(frappe.PermissionError):
                xls.download_hq_excel({})
        guard.assert_called_once()

    def test_sin_company_no_encola(self) -> None:
        """El JS lo valida, pero el endpoint acepta filtros arbitrarios: sin company
        seria un get_doc("Company", None) con traceback en vez de mensaje."""
        with patch("frappe.only_for"), patch("frappe.enqueue") as cola:
            with self.assertRaises(frappe.ValidationError):
                xls.download_hq_excel({"from_date": "2026-07-01"})
        cola.assert_not_called()

    def test_encola_el_job_con_timeout_explicito(self) -> None:
        """El Excel se genera en background. El timeout va explicito a proposito:
        sin el, RQ mata el job con el default de la cola, y el caso real proyectado
        a 30.000 filas ronda los 45s de pura generacion."""
        with patch("frappe.only_for"), patch("frappe.enqueue") as cola:
            res = xls.download_hq_excel({"company": "ACME", "from_date": "2026-07-01",
                                         "to_date": "2026-07-31"})

        self.assertEqual(res["type"], "queued")
        self.assertEqual(res["filename"], "Facturas_Venta_HQ_20260701_20260731.xlsx")
        cola.assert_called_once()
        kwargs = cola.call_args.kwargs
        self.assertEqual(kwargs["queue"], "long")
        self.assertEqual(kwargs["timeout"], 1800)
        self.assertEqual(kwargs["filters"]["company"], "ACME")


if __name__ == "__main__":
    unittest.main()


class TestMunicipalityFilter(unittest.TestCase):
    """Filtro de municipio: herencia por arbol, interseccion y empuje al SQL."""

    # Arbol de prueba: PADRE tiene municipio, HIJO no --hereda--, OTRA tiene otro.
    MAPA = {"PADRE": "muni-a", "HIJO": "muni-a", "OTRA": "muni-b", "SIN": ""}

    def test_hereda_el_municipio_del_padre(self) -> None:
        """Una sucursal sin municipio propio cuenta como la de su ancestro."""
        with patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA):
            self.assertEqual(
                hq._get_branches_by_municipality("muni-a"), {"PADRE", "HIJO"}
            )

    def test_no_arrastra_sucursales_de_otro_municipio(self) -> None:
        with patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA):
            self.assertEqual(hq._get_branches_by_municipality("muni-b"), {"OTRA"})

    def test_municipio_sin_sucursales_da_conjunto_vacio(self) -> None:
        with patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA):
            self.assertEqual(hq._get_branches_by_municipality("muni-z"), set())

    def test_sin_municipio_devuelve_vacio(self) -> None:
        self.assertEqual(hq._get_branches_by_municipality(""), set())
        self.assertEqual(hq._get_branches_by_municipality(None), set())

    def test_el_conjunto_se_empuja_al_sql_y_no_se_filtra_en_memoria(self) -> None:
        """El libro tiene que recibir `branches`; si no, se trae el periodo entero."""
        capturado: dict = {}

        def fake_data(filters):
            capturado.update(filters)
            return [], []

        with (
            patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA),
            patch.object(hq, "_sales_book_data", side_effect=fake_data),
            patch.object(hq, "_get_main_branch_map", return_value={}),
            patch.object(hq, "_validate_filters", return_value=None),
        ):
            hq.get_hq_data({"municipality": "muni-a"})

        self.assertEqual(capturado.get("branches"), ["HIJO", "PADRE"])
        self.assertNotIn("municipality", capturado)

    def test_municipio_sin_sucursales_no_consulta_el_libro(self) -> None:
        """Conjunto vacio = cero filas. Si consultara, devolveria TODAS."""
        with (
            patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA),
            patch.object(hq, "_sales_book_data") as libro,
            patch.object(hq, "_get_main_branch_map", return_value={}),
            patch.object(hq, "_validate_filters", return_value=None),
        ):
            resultado = hq.get_hq_data({"municipality": "muni-z"})

        libro.assert_not_called()
        self.assertEqual(resultado["main_data"], [])
        self.assertEqual(resultado["allowed_count"], 0)

    def test_interseccion_con_el_filtro_de_sucursal(self) -> None:
        """Municipio + sucursal = interseccion, no union."""
        capturado: dict = {}

        def fake_data(filters):
            capturado.update(filters)
            return [], []

        with (
            patch.object(hq, "_get_branch_municipality_map", return_value=self.MAPA),
            patch.object(hq, "get_branch_subtree", return_value={"PADRE", "OTRA"}),
            patch.object(hq, "_sales_book_data", side_effect=fake_data),
            patch.object(hq, "_get_main_branch_map", return_value={}),
            patch.object(hq, "_validate_filters", return_value=None),
        ):
            hq.get_hq_data({"branch": "PADRE", "municipality": "muni-a"})

        self.assertEqual(capturado.get("branches"), ["PADRE"])

    def test_el_mensaje_avisa_cuando_no_matcheo_ninguna(self) -> None:
        with (
            patch.object(hq.frappe, "get_meta", return_value=Mock(get_title_field=lambda: "municipality")),
            patch.object(hq.frappe.db, "get_value", return_value="Plaza"),
        ):
            msg = hq._build_report_message("", None, "", "muni-z", 0)
        self.assertIn("Plaza", msg)
        self.assertIn("Ninguna sucursal", msg)

    def test_el_mensaje_dice_cuantas_matchearon(self) -> None:
        with (
            patch.object(hq.frappe, "get_meta", return_value=Mock(get_title_field=lambda: "municipality")),
            patch.object(hq.frappe.db, "get_value", return_value="Plaza"),
        ):
            msg = hq._build_report_message("", None, "", "muni-a", 2)
        self.assertIn("Plaza", msg)
        self.assertIn("2", msg)


class TestResolveBranchScope(unittest.TestCase):
    """El cruce de ``branch`` con ``main_branch``, ahora compartido con el Libro.

    Vive en ``sales_book`` porque los dos reportes lo necesitan: el HQ ya lo tenía y el
    Libro devolvía CERO filas al filtrar por una sucursal grupo.
    """

    def _scope(self, branch, main, arbol):
        from l10n_ve.l10n_ve.report.sales_book import sales_book

        with patch.object(sales_book, "get_branch_subtree",
                          side_effect=lambda b: arbol.get(b)):
            return sales_book.resolve_branch_scope(branch, main)

    #: G es grupo (hijas H1, H2); L y M son hojas -> ``None``, el atajo de igualdad.
    ARBOL = {"G": {"G", "H1", "H2"}, "L": None, "M": None, "P": {"P", "L"}}

    def test_sin_filtros_no_acota(self):
        self.assertIsNone(self._scope(None, None, self.ARBOL))

    def test_hoja_sola_deja_la_igualdad_simple(self):
        """``None`` es el atajo para que el plan use ``branch_index``."""
        self.assertIsNone(self._scope("L", None, self.ARBOL))

    def test_grupo_solo_devuelve_su_subarbol(self):
        self.assertEqual(self._scope("G", None, self.ARBOL), {"G", "H1", "H2"})

    def test_principal_sola_devuelve_su_subarbol(self):
        self.assertEqual(self._scope(None, "P", self.ARBOL), {"P", "L"})

    def test_una_HOJA_de_la_principal_NO_se_pierde(self):
        """El bug que traía el HQ: la hoja desaparecía y quedaba solo la principal.

        ``get_branch_subtree`` devuelve ``None`` para una hoja, y ese ``None`` se leía
        como «sin filtro de sucursal». Medido antes del arreglo: pedir una hoja ajena a
        la principal devolvía 1.227 filas donde correspondían cero.
        """
        self.assertEqual(self._scope("L", "P", self.ARBOL), {"L"})

    def test_una_hoja_AJENA_a_la_principal_no_devuelve_nada(self):
        """Cero filas, no todas: la intersección es vacía y hay que respetarla."""
        self.assertEqual(self._scope("M", "P", self.ARBOL), set())

    def test_grupo_ajeno_a_la_principal_tampoco(self):
        self.assertEqual(self._scope("G", "P", self.ARBOL), set())


class TestElLibroResuelveSusFiltros(unittest.TestCase):
    """``get_sales_data`` acota por conjunto sin que el llamador tenga que resolverlo.

    Se leen las decisiones en el fuente en vez de ejecutar la función: simular
    ``frappe.db.sql`` entero rompe la carga de otros doctypes que ``get_sales_data``
    toca de paso, y el test terminaba probando el mock. El comportamiento contra la
    base ya quedó medido a mano sobre los siete casos del árbol real.
    """

    def _fuente(self):
        import inspect

        from l10n_ve.l10n_ve.report.sales_book import sales_book

        f = inspect.getsource(sales_book.get_sales_data)
        return f[f.index("branch: str = filters.get"):f.index("--- Datos del período")]

    def test_resuelve_el_scope_cuando_el_llamador_no_lo_dio(self):
        """El HQ pasa ``branches`` ya resuelto; el Libro tiene que resolverlo solo."""
        f = self._fuente()
        self.assertIn('if not filters.get("branches"):', f)
        self.assertIn("resolve_branch_scope(branch", f)
        self.assertIn('filters.get("main_branch")', f)

    def test_un_conjunto_vacio_NO_se_lee_como_sin_filtro(self):
        """``branches=[]`` es falsy unas líneas más abajo: devolvería TODO.

        Se fuerza un centinela imposible para que devuelva cero, que es la respuesta
        correcta cuando ninguna sucursal matchea.
        """
        f = self._fuente()
        self.assertIn('["__ninguna__"]', f)

    def test_la_hoja_conserva_la_igualdad_simple(self):
        """El ``elif branch`` tiene que seguir vivo: usa ``branch_index``."""
        import inspect

        from l10n_ve.l10n_ve.report.sales_book import sales_book

        f = inspect.getsource(sales_book.get_sales_data)
        self.assertIn("AND siv.branch = %(branch)s", f)
        self.assertIn("AND siv.branch IN %(branches)s", f)
