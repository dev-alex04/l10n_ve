import frappe
from frappe import _
from io import BytesIO
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
import base64

from l10n_ve.l10n_ve.report.sales_book.sales_book import (
    get_columns, get_total_row, prepare_excel_export, build_excel_filename,
)


#: Caracteres que Excel no acepta en el nombre de una hoja.
_FORBIDDEN_SHEET_CHARS: str = r":\/?*[]"


def _sanitize_sheet_title(title) -> str:
    """Nombre de hoja válido: sin caracteres prohibidos y de 31 caracteres como máximo."""
    if not title:
        return ""
    clean = "".join(" " if char in _FORBIDDEN_SHEET_CHARS else char for char in str(title))
    return clean.strip()[:31]


class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria con formato profesional,
    replicando la misma estética del Libro de Compras.
    """

    def __init__(self, title, columns, main_data, adjustment_data, summary_data,
                 company_data, from_date, to_date):
        self.title = title
        self.columns = columns
        self.main_data = main_data
        self.adjustment_data = adjustment_data
        self.summary_data = summary_data
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        # Excel corta los nombres de hoja en 31 caracteres y rechaza : \ / ? * [ ]
        self.sheet.title = _sanitize_sheet_title(self.title) or "Libro de Ventas"

        self.default_font = Font(name='Calibri', size=8)
        self.header_font = Font(name='Calibri', size=8, bold=True)
        self.header_font_white = Font(name='Calibri', size=8, bold=True, color="FFFFFF")
        self.total_font = Font(name='Calibri', size=8, bold=True)
        self.title_font = Font(name='Calibri', size=14, bold=True, color="1E293B")
        self.meta_title_font = Font(name='Calibri', size=8, bold=True, color="475569")
        self.meta_value_font = Font(name='Calibri', size=8, color="1E293B")

        self.thin_border = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0"),
        )
        self.header_border = Border(
            left=Side(style="thin", color="475569"),
            right=Side(style="thin", color="475569"),
            top=Side(style="thin", color="475569"),
            bottom=Side(style="medium", color="1E293B"),
        )
        self.total_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="medium", color="1E293B"),
            bottom=Side(style="double", color="1E293B"),
        )

        self.header_fill_primary = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        self.header_fill_secondary = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        self.sub_header_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        self.zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        self.total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        self.alert_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid")

        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'
        self.int_format = '0'

        self.data = self.main_data

    def _get_col_index(self, fieldname: str) -> int:
        for i, col in enumerate(self.columns):
            if col.get("fieldname") == fieldname:
                return i + 1
        return 0

    def _add_report_header(self) -> int:
        ws = self.sheet

        ws.row_dimensions[2].height = 30
        title_cell = ws.cell(row=2, column=2, value=self.title or _("LIBRO DE VENTAS FISCAL"))
        title_font = Font(name="Calibri", size=16, bold=True, color="1E293B")
        title_cell.font = title_font
        title_cell.alignment = Alignment(vertical="center")

        meta_label_font = Font(name="Calibri", size=9, bold=True, color="475569")
        meta_value_font = Font(name="Calibri", size=9, color="1E293B")
        card_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        start_row = 4
        end_row = 8
        start_col = 2
        end_col = 14

        for r in range(start_row, end_row + 1):
            ws.row_dimensions[r].height = 20
            for c in range(start_col, end_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.fill = card_fill
                left_side = Side(style="thin", color="CBD5E1") if c == start_col else None
                right_side = Side(style="thin", color="CBD5E1") if c == end_col else None
                top_side = Side(style="thin", color="CBD5E1") if r == start_row else None
                bottom_side = Side(style="thin", color="CBD5E1") if r == end_row else None
                cell.border = Border(left=left_side, right=right_side, top=top_side, bottom=bottom_side)

        lbl_company = ws.cell(row=5, column=2, value=_("Nombre o Razón Social:"))
        lbl_company.font = meta_label_font
        lbl_company.alignment = Alignment(horizontal="right", vertical="center")

        val_company = ws.cell(row=5, column=4, value=self.company_data.get("company_name", ""))
        val_company.font = Font(name="Calibri", size=9, bold=True, color="1E293B")
        val_company.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=4, end_row=5, end_column=8)

        lbl_rif = ws.cell(row=5, column=10, value=_("RIF de la Empresa:"))
        lbl_rif.font = meta_label_font
        lbl_rif.alignment = Alignment(horizontal="right", vertical="center")

        val_rif = ws.cell(row=5, column=12, value=self.company_data.get("tax_id", ""))
        val_rif.font = meta_value_font
        val_rif.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=12, end_row=5, end_column=14)

        lbl_dir = ws.cell(row=6, column=2, value=_("Dirección Fiscal:"))
        lbl_dir.font = meta_label_font
        lbl_dir.alignment = Alignment(horizontal="right", vertical="center")

        val_address = ws.cell(row=6, column=4, value=self.company_data.get("address", ""))
        val_address.font = meta_value_font
        val_address.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=6, start_column=4, end_row=6, end_column=8)

        lbl_contrib = ws.cell(row=6, column=10, value=_("Contribuyente:"))
        lbl_contrib.font = meta_label_font
        lbl_contrib.alignment = Alignment(horizontal="right", vertical="center")

        taxpayer_type = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("ORDINARIO")
        val_contrib = ws.cell(row=6, column=12, value=taxpayer_type)
        val_contrib.font = meta_value_font
        val_contrib.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=6, start_column=12, end_row=6, end_column=14)

        lbl_period = ws.cell(row=7, column=2, value=_("Período Fiscal:"))
        lbl_period.font = meta_label_font
        lbl_period.alignment = Alignment(horizontal="right", vertical="center")

        period_str = "{0} - {1}".format(
            self.from_date.strftime("%d/%m/%Y"),
            self.to_date.strftime("%d/%m/%Y"),
        )
        val_period = ws.cell(row=7, column=4, value=period_str)
        val_period.font = meta_value_font
        val_period.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=7, start_column=4, end_row=7, end_column=8)

        return 11

    def _build_multi_level_headers(self, start_row: int) -> int:
        ws = self.sheet
        current_row = start_row

        non_tp = self._get_col_index("base_reduced_non_taxpayer")
        tp = self._get_col_index("base_reduced_taxpayer")
        ret = self._get_col_index("iva_retained")
        igtf = self._get_col_index("base_amount_igtf")

        header_levels = [
            [
                {"text": _("Ventas a No Contribuyentes"), "start_col": non_tp, "span": 6},
                {"text": _("Ventas a Contribuyentes"), "start_col": tp, "span": 6},
            ],
            [
                {"text": _("Tasa Reducida 8%"), "start_col": non_tp, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": non_tp + 2, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": non_tp + 4, "span": 2},
                {"text": _("Tasa Reducida 8%"), "start_col": tp, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": tp + 2, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": tp + 4, "span": 2},
                {"text": _("Retención"), "start_col": ret, "span": 4},
                {"text": _("IGTF"), "start_col": igtf, "span": 3},
            ]
        ]

        for level_idx, level_headers in enumerate(header_levels):
            fill = self.header_fill_primary if level_idx == 0 else self.header_fill_secondary
            for header_info in level_headers:
                span = header_info["span"]
                start_col = header_info["start_col"]
                for c_offset in range(span):
                    cell = ws.cell(row=current_row, column=start_col + c_offset)
                    cell.fill = fill
                    cell.border = self.header_border
                cell = ws.cell(row=current_row, column=start_col, value=header_info["text"])
                cell.font = self.header_font_white
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                if span > 1:
                    ws.merge_cells(
                        start_row=current_row,
                        start_column=start_col,
                        end_row=current_row,
                        end_column=start_col + span - 1,
                    )
            current_row += 1

        main_table_headers = [col.get("label") for col in self.columns]
        column_widths_config = {
            "Nr Oper.": 5, "Sucursal": 8, "Fecha": 10, "RIF del Cliente": 14,
            "Nombre del Cliente": 22, "Tipo de Persona": 5, "Serie Fiscal": 8,
            "Nro. de Factura": 12, "Nro. de Control": 12,
            "Nro. Nota de Credito": 12, "Nro. Nota de Debito": 12,
            "Facturas afectadas": 12, "Tipo de Transaccion": 7,
            "Total Incl. IVA": 14,
        }

        for i, header in enumerate(main_table_headers):
            col_index = i + 1
            col_letter = get_column_letter(col_index)
            ws.column_dimensions[col_letter].width = column_widths_config.get(header, 10)
            cell = ws.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font_white
            cell.fill = self.header_fill_primary
            cell.border = self.header_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.row_dimensions[current_row].height = 28

        return current_row

    def _write_data_rows(self, start_row: int) -> int:
        ws = self.sheet
        row_index = start_row + 1
        for i, row_data in enumerate(self.data):
            fill = self.zebra_fill if i % 2 == 0 else None
            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)
                cell = ws.cell(row=row_index, column=col_index, value=cell_value)
                cell.font = self.default_font
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                if isinstance(cell_value, (int, float)):
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    cell.number_format = self.int_format if fieldname == "sequence_number" else self.numeric_format
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            ws.row_dimensions[row_index].height = 18
            row_index += 1
        return row_index

    def _write_totals_row(self, start_row: int) -> int:
        ws = self.sheet
        # summary_data ya ES get_total_row(main_data) en los dos llamadores, así que
        # recalcularlo era una segunda pasada sobre 10.000+ filas para el mismo dict. Y
        # usarlo permite que un reporte agregue totales de columnas propias: el HQ suma
        # ahí taxable_amount y total_vat, que get_total_row() no conoce porque es del
        # Libro de Ventas y saldrían vacíos justo en la fila de Totales.
        totals = self.summary_data or get_total_row(self.data)
        total_row_index = start_row + 1

        for col_index in range(1, len(self.columns) + 1):
            cell = ws.cell(row=total_row_index, column=col_index)
            cell.font = self.total_font
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_label_cell = ws.cell(row=total_row_index, column=1, value=_("Totales"))
        total_label_cell.font = self.total_font
        total_label_cell.border = self.total_border
        total_label_cell.fill = self.total_fill

        for col_index, col in enumerate(self.columns, start=1):
            fieldname = col.get("fieldname")
            if fieldname in totals:
                total_value = totals.get(fieldname)
                total_cell = ws.cell(row=total_row_index, column=col_index, value=total_value)
                total_cell.font = self.total_font
                total_cell.border = self.total_border
                total_cell.fill = self.total_fill
                total_cell.number_format = self.numeric_format
                total_cell.alignment = Alignment(horizontal="right", vertical="center")

        ws.row_dimensions[total_row_index].height = 20
        return total_row_index

    def _build_main_table(self, start_row: int) -> int:
        self.data = self.main_data
        headers_last_row = self._build_multi_level_headers(start_row)
        data_last_row = self._write_data_rows(headers_last_row)
        totals_last_row = self._write_totals_row(data_last_row)

        # Con 10.000+ filas, revisar la tabla sin encabezado fijo ni autofiltro es
        # impracticable: al hacer scroll se pierde qué columna es cuál. El autofiltro se
        # ancla en la fila de encabezados reales (la última del bloque multinivel) y NO
        # abarca la fila de Totales, para que filtrar no la esconda ni la ordene.
        self.sheet.freeze_panes = f"A{headers_last_row + 1}"
        if self.columns and data_last_row > headers_last_row:
            self.sheet.auto_filter.ref = "A{0}:{1}{2}".format(
                headers_last_row, get_column_letter(len(self.columns)), data_last_row - 1
            )

        return totals_last_row

    def _build_adjustments_table(self, start_row: int) -> int:
        if not self.adjustment_data:
            return start_row

        current_row = start_row + 2
        title_cell = self.sheet.cell(row=current_row, column=1,
                                      value=_("Ajustes de Períodos Anteriores (Retenciones)"))
        title_cell.font = Font(size=12, bold=True)
        current_row += 2

        self.data = self.adjustment_data
        headers_last_row = self._build_multi_level_headers(current_row)
        data_last_row = self._write_data_rows(headers_last_row)
        totals_last_row = self._write_totals_row(data_last_row)
        return totals_last_row

    def _build_summary_table(self, start_row: int) -> int:
        ws = self.sheet
        if not self.summary_data:
            return start_row

        current_row = start_row + 2
        summary_start_col = 13

        summary_headers = [
            {"text": _("RESUMEN"), "start_col": summary_start_col, "span": 5, "align": "center"},
            {"text": _("Base Imponible"), "start_col": summary_start_col + 5, "span": 1, "align": "center"},
            {"text": _("Débito Fiscal"), "start_col": summary_start_col + 6, "span": 1, "align": "center"},
            {"text": _("Retención"), "start_col": summary_start_col + 7, "span": 1, "align": "center"},
        ]

        for header_info in summary_headers:
            span = header_info["span"]
            start_col = header_info["start_col"]
            for c_offset in range(span):
                cell = ws.cell(row=current_row, column=start_col + c_offset)
                cell.fill = self.header_fill_primary
                cell.border = self.header_border
            cell = ws.cell(row=current_row, column=start_col, value=header_info["text"])
            cell.font = self.header_font_white
            cell.alignment = Alignment(horizontal=header_info["align"], vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(start_col)].width = 12
            if span > 1:
                ws.merge_cells(
                    start_row=current_row,
                    start_column=start_col,
                    end_row=current_row,
                    end_column=start_col + span - 1,
                )
        ws.row_dimensions[current_row].height = 24

        current_row += 1

        summary_rows = [
            {"concept": _("De las Ventas Internas NO Gravadas"),
             "base": self.summary_data.get("total_exempt", 0), "iva": 0, "retention": 0},
            {"concept": _("Ventas de exportación"),
             "base": 0, "iva": 0, "retention": 0},
            {"concept": _("Alícuota General"),
             "base": (self.summary_data.get("base_general_taxpayer", 0)
                      + self.summary_data.get("base_general_non_taxpayer", 0)),
             "iva": (self.summary_data.get("iva_general_taxpayer", 0)
                     + self.summary_data.get("iva_general_non_taxpayer", 0)),
             "retention": self.summary_data.get("iva_retained_general", 0)},
            {"concept": _("Alícuota General + Adicional"),
             "base": (self.summary_data.get("base_additional_taxpayer", 0)
                      + self.summary_data.get("base_additional_non_taxpayer", 0)),
             "iva": (self.summary_data.get("iva_additional_taxpayer", 0)
                     + self.summary_data.get("iva_additional_non_taxpayer", 0)),
             "retention": self.summary_data.get("iva_retained_additional", 0)},
            {"concept": _("Alícuota Reducida"),
             "base": (self.summary_data.get("base_reduced_taxpayer", 0)
                      + self.summary_data.get("base_reduced_non_taxpayer", 0)),
             "iva": (self.summary_data.get("iva_reduced_taxpayer", 0)
                     + self.summary_data.get("iva_reduced_non_taxpayer", 0)),
             "retention": self.summary_data.get("iva_retained_reduced", 0)},
        ]

        for i, row_data in enumerate(summary_rows):
            fill = self.zebra_fill if i % 2 == 0 else None
            for c_offset in range(5):
                cell = ws.cell(row=current_row, column=summary_start_col + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
            concept_cell = ws.cell(row=current_row, column=summary_start_col, value=row_data["concept"])
            concept_cell.font = self.default_font
            ws.merge_cells(start_row=current_row, start_column=summary_start_col,
                           end_row=current_row, end_column=summary_start_col + 4)

            for j, key in enumerate(["base", "iva", "retention"], start=1):
                cell = ws.cell(row=current_row, column=summary_start_col + 5 - 1 + j, value=row_data[key])
                cell.font = self.default_font
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                cell.number_format = self.numeric_format
                cell.alignment = Alignment(horizontal="right", vertical="center")

            ws.row_dimensions[current_row].height = 18
            current_row += 1

        total_base = sum(row["base"] for row in summary_rows)
        total_iva = sum(row["iva"] for row in summary_rows)
        total_retention = sum(row["retention"] for row in summary_rows)

        for c_idx in range(summary_start_col, summary_start_col + 8):
            cell = ws.cell(row=current_row, column=c_idx)
            cell.font = self.total_font
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_label_cell = ws.cell(row=current_row, column=summary_start_col, value=_("Total"))
        total_label_cell.font = self.total_font
        ws.merge_cells(start_row=current_row, start_column=summary_start_col,
                       end_row=current_row, end_column=summary_start_col + 4)

        for j, val in enumerate([total_base, total_iva, total_retention], start=1):
            cell = ws.cell(row=current_row, column=summary_start_col + 5 - 1 + j, value=val)
            cell.font = self.total_font
            cell.number_format = self.numeric_format
            cell.alignment = Alignment(horizontal="right", vertical="center")

        ws.row_dimensions[current_row].height = 20
        return ws.max_row

    def build(self):
        try:
            original_summary_data = self.summary_data

            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)
            last_row_summary = self._build_summary_table(last_row_main_table)
            self._build_adjustments_table(last_row_summary)

            file_stream = BytesIO()
            self.summary_data = original_summary_data
            self.workbook.save(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            frappe.throw(_("Ocurrió un error al construir el archivo de Excel: {0}").format(e))


@frappe.whitelist()
def create_excel_file(report_name, filters=None, **kwargs):
    """Genera el archivo de Excel con formato detallado."""
    if not filters:
        filters = kwargs.get("filters_json")

    try:
        ctx = prepare_excel_export(filters)
        columns = get_columns()
        columns.insert(0, {"label": "Nr Oper.", "fieldname": "sequence_number", "width": 20})

        title = _("Libro de Ventas")

        builder = ExcelBuilder(
            title,
            columns,
            ctx["main_data"],
            ctx["adjustment_data"],
            ctx["summary_data"],
            ctx["company_data"],
            ctx["from_date"],
            ctx["to_date"],
        )
        excel_content = builder.build()

        base64_content = base64.b64encode(excel_content.getvalue()).decode('utf-8')

        return {
            "type": "download",
            "filename": build_excel_filename(
                ctx["company_doc"].company_name, ctx["from_date"], ctx["to_date"]
            ),
            "filecontent": base64_content,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en create_excel_file")
        frappe.throw(_("Ocurrió un error al generar el archivo de Excel: {0}").format(e))
