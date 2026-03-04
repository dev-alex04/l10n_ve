import frappe
from frappe import _
import json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
import base64

from l10n_ve.l10n_ve.report.sales_book.sales_book import get_columns, get_sales_data, get_total_row

class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria con formato profesional.
    """
    def __init__(self, title, columns, main_data, adjustment_data, summary_data, company_data, from_date, to_date):
        self.title = title
        self.columns = columns

        # Separar los datos para las tablas
        self.main_data = main_data
        self.adjustment_data = adjustment_data

        self.summary_data = summary_data
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Reporte"

        # Definimos los estilos comunes
        self.default_font = Font(name='Calibri', size=8)
        self.header_font = Font(name='Calibri', size=8, bold=True)
        self.data_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'
        self.int_format = '0'


    def _add_report_header(self):
        """
        Agrega el encabezado con los datos de la compañía en un formato estructurado de 2x2.
        """
        current_row = 1

        self.sheet.cell(row=current_row, column=1, value=_("Libro de Ventas Fiscal")).font = Font(size=14, bold=True)

        current_row += 2

        self.sheet.column_dimensions[get_column_letter(1)].width = 30
        self.sheet.column_dimensions[get_column_letter(2)].width = 40
        self.sheet.column_dimensions[get_column_letter(3)].width = 30
        self.sheet.column_dimensions[get_column_letter(4)].width = 40
        self.sheet.column_dimensions[get_column_letter(8)].width = 30
        self.sheet.column_dimensions[get_column_letter(9)].width = 40

        title_font = Font(bold=True)

        self.sheet.cell(row=current_row, column=1, value=_("Nombre o Razón Social:")).font = title_font
        self.sheet.cell(row=current_row, column=12, value=_("Número de Registro de Información Fiscal (RIF):")).font = title_font

        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=self.company_data.get("company_name"))
        self.sheet.cell(row=current_row, column=12, value=self.company_data.get("tax_id"))

        current_row += 2

        is_special_taxpayer_text = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("NO ESPECIAL")

        self.sheet.cell(row=current_row, column=1, value=_("Dirección:")).font = title_font
        self.sheet.cell(row=current_row, column=12, value=_("Tipo de Contribuyente:")).font = title_font

        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=self.company_data.get("address"))
        self.sheet.cell(row=current_row, column=12, value=is_special_taxpayer_text)

        current_row += 2

        # Período Fiscal
        self.sheet.cell(row=current_row, column=1, value=_("Período Fiscal:")).font = title_font
        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=f"{self.from_date.strftime('%d/%m/%Y')} - {self.to_date.strftime('%d/%m/%Y')}")

        return current_row + 2

    def _build_multi_level_headers(self, start_row: int) -> int:
        """
        Construye los encabezados de varios niveles para la tabla principal.
        """
        current_row = start_row

        # Configuración declarativa de los encabezados de varios niveles
        header_levels = [
            # Nivel 2
            [
                {"text": _("Ventas a No Contribuyentes"), "start_col": 17, "span": 6},
                {"text": _("Ventas a Contribuyentes"), "start_col": 23, "span": 6},
            ],
            # Nivel 3
            [
                {"text": _("Tasa Reducida 8%"), "start_col": 17, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": 19, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": 21, "span": 2},
                {"text": _("Tasa Reducida 8%"), "start_col": 23, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": 25, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": 27, "span": 2},
                {"text": _("Retención"), "start_col": 29, "span": 4},
                {"text": _("IGTF"), "start_col": 33, "span": 3},
            ]
        ]

        for level_headers in header_levels:
            for header_info in level_headers:
                cell = self.sheet.cell(row=current_row, column=header_info["start_col"], value=header_info["text"])
                cell.font = self.header_font
                cell.border = self.data_border
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

                if header_info["span"] > 1:
                    self.sheet.merge_cells(
                        start_row=current_row,
                        start_column=header_info["start_col"],
                        end_row=current_row,
                        end_column=header_info["start_col"] + header_info["span"] - 1
                    )
            current_row += 1

        # --- Encabezados principales de la tabla (Nivel 4) ---
        main_table_headers = [col.get("label") for col in self.columns]

        column_widths_config = {
            "Nr Oper.": 5, "Tipo de Persona": 5, "RIF del Cliente": 12,
            "Nro. de Control": 12, "Nro. Factura": 12, "Fecha": 10,
            "Nro. de Maquina Fiscal": 10, "Nro. Nota de Credito": 12, "Nro. Nota de Debito": 12
        }

        for i, header in enumerate(main_table_headers):
            col_index = i + 1
            col_letter = get_column_letter(col_index)

            self.sheet.column_dimensions[col_letter].width = column_widths_config.get(header, 10)

            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            self.sheet.row_dimensions[current_row].height = 40

        return current_row

    def _write_data_rows(self, start_row):
        """
        Escribe las filas de datos en la tabla principal y ajusta dinámicamente el ancho de las columnas.
        """
        current_row = start_row
        column_widths = {get_column_letter(i + 1): self.sheet.column_dimensions[get_column_letter(i + 1)].width or 10 for i in range(len(self.columns))}

        row_index = current_row + 1
        for row_data in self.data:
            row_alignment_text = Alignment(horizontal="left", vertical="center", wrap_text=True)
            row_alignment_number = Alignment(horizontal="right", vertical="center")

            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)

                cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                cell.font = self.default_font
                cell.border = self.data_border

                if isinstance(cell_value, (int, float)):
                    if fieldname == "sequence_number":
                        cell.number_format = self.int_format
                    else:
                        cell.number_format = self.numeric_format

                    cell.alignment = row_alignment_number
                else:
                    cell.alignment = row_alignment_text

                col_letter = get_column_letter(col_index)
                cell_length = len(str(cell_value)) if cell_value is not None else 0
                current_width = column_widths.get(col_letter, 0)

                if col_index <= 14:
                    max_text_width = 30 if fieldname == "company_name" else 15
                    column_widths[col_letter] = min(max(current_width, cell_length + 2), max_text_width)
                elif cell_length > 0:
                    column_widths[col_letter] = min(max(current_width, cell_length + 1), 12)

            row_index += 1

        for col, width in column_widths.items():
            self.sheet.column_dimensions[col].width = width

        return self.sheet.max_row

    def _write_totals_row(self, start_row):
        """
        Escribe la fila de totales al final de la tabla principal.
        """
        totals = get_total_row(self.data)
        current_row_for_totals = self.sheet.max_row + 2

        for col_index, col in enumerate(self.columns, start=1):
            fieldname = col.get("fieldname")
            cell_value = totals.get(fieldname)

            cell = self.sheet.cell(row=current_row_for_totals, column=col_index, value=cell_value)
            cell.font = self.header_font
            cell.border = self.data_border

            if isinstance(cell_value, (int, float)):
                cell.number_format = self.numeric_format
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.alignment = self.data_alignment

        self.sheet.merge_cells(start_row=current_row_for_totals,
                               start_column=1,
                               end_row=current_row_for_totals,
                               end_column=2)

        return self.sheet.max_row

    def _build_main_table(self, start_row):
        """
        Construye la tabla principal con todos los datos y encabezados,
        usando anchos compactos y SEPARANDO LA FILA DE TOTALES.
        """
        self.data = self.main_data

        headers_last_row = self._build_multi_level_headers(start_row)
        data_last_row = self._write_data_rows(headers_last_row)
        self._write_totals_row(data_last_row)
        return self.sheet.max_row

    def _build_adjustments_table(self, start_row: int) -> int:
        """Construye una tabla separada para las transacciones de ajuste."""
        if not self.adjustment_data:
            return start_row

        current_row = start_row + 2

        title_cell = self.sheet.cell(row=current_row,
                                     column=1,
                                     value=_("Ajustes de Períodos Anteriores (Retenciones)"))
        title_cell.font = Font(size=12, bold=True)
        current_row += 2

        self.data = self.adjustment_data

        headers_last_row = self._build_multi_level_headers(current_row)
        data_last_row = self._write_data_rows(headers_last_row)
        self._write_totals_row(data_last_row)

        return self.sheet.max_row

    def _build_summary_table(self, start_row):
        current_row = start_row + 2

        thin_border_style = Side(style="thin")

        summary_start_col = 10

        self.sheet.cell(row=current_row,
                        column=summary_start_col,
                        value=_("Resumen de Totales")).font = Font(bold=True, size=12)

        summary_row_index = current_row + 1
        summary_headers = [_("Concepto"), _("Base Imponible"),
                           _("Débito Fiscal"), _("Retención")]

        concept_header_cell = self.sheet.cell(row=summary_row_index,
                                              column=summary_start_col,
                                              value=summary_headers[0])

        concept_header_cell.font = self.header_font
        concept_header_cell.border = Border(top=thin_border_style,
                                             bottom=thin_border_style,
                                             left=thin_border_style)

        self.sheet.merge_cells(
            start_row=summary_row_index, start_column=summary_start_col,
            end_row=summary_row_index, end_column=summary_start_col + 4
        )

        for col_index, header_text in enumerate(summary_headers[1:], start=summary_start_col + 5):
            cell = self.sheet.cell(row=summary_row_index, column=col_index, value=header_text)
            cell.font = self.header_font
            border = Border(top=thin_border_style, bottom=thin_border_style)

            if col_index == summary_start_col + 6:
                border.right = thin_border_style

            cell.border = border

        self.sheet.column_dimensions[get_column_letter(summary_start_col)].width = 10
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 1)].width = 10
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 2)].width = 10
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 3)].width = 10
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 4)].width = 10
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 5)].width = 11
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 6)].width = 11
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 7)].width = 11

        summary_row_index += 1

        # Configuración declarativa para las filas del resumen
        summary_data_rows = [
            {
                "concepto": _("De las Ventas Internas NO Gravadas"),
                "base": self.summary_data.get("total_exempt", 0),
                "iva": 0,
                "retencion": 0
            },
            {
                "concepto": _("Ventas de exportación"),
                "base": 0, "iva": 0, "retencion": 0
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota General"),
                "base": self.summary_data.get("base_general_taxpayer", 0)
                + self.summary_data.get("base_general_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_general_taxpayer", 0)
                + self.summary_data.get("iva_general_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_general", 0)
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota General + Adicional"),
                "base": self.summary_data.get("base_additional_taxpayer", 0)
                + self.summary_data.get("base_additional_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_additional_taxpayer", 0)
                + self.summary_data.get("iva_additional_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_additional", 0)
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota Reducida"),
                "base": self.summary_data.get("base_reduced_taxpayer", 0)
                + self.summary_data.get("base_reduced_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_reduced_taxpayer", 0)
                + self.summary_data.get("iva_reduced_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_reduced", 0)
            }
        ]

        for i, row_data in enumerate(summary_data_rows):
            is_last_row = (i == len(summary_data_rows) - 1)
            bottom_border_style = thin_border_style if is_last_row else Side(style=None)

            concept_cell = self.sheet.cell(row=summary_row_index,
                                           column=summary_start_col,
                                           value=row_data.get("concepto"))

            concept_cell.font = self.default_font
            concept_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            concept_cell.border = Border(left=thin_border_style, bottom=bottom_border_style)
            self.sheet.merge_cells(
                start_row=summary_row_index, start_column=summary_start_col,
                end_row=summary_row_index, end_column=summary_start_col + 4
            )

            base_cell = self.sheet.cell(row=summary_row_index, column=summary_start_col + 5, value=row_data.get("base"))
            base_cell.font = self.default_font
            base_cell.number_format = self.numeric_format
            base_cell.border = Border(bottom=bottom_border_style)

            iva_cell = self.sheet.cell(row=summary_row_index, column=summary_start_col + 6, value=row_data.get("iva"))
            iva_cell.font = self.default_font
            iva_cell.number_format = self.numeric_format
            iva_cell.border = Border(bottom=bottom_border_style)

            retention_cell = self.sheet.cell(row=summary_row_index,
                                             column=summary_start_col + 7,
                                             value=row_data.get("retencion"))

            retention_cell.font = self.default_font
            retention_cell.number_format = self.numeric_format
            retention_cell.border = Border(right=thin_border_style, bottom=bottom_border_style)

            summary_row_index += 1

        current_row = self.sheet.max_row + 1

        total_base = sum(row.get("base") for row in summary_data_rows)
        total_iva = sum(row.get("iva") for row in summary_data_rows)
        total_retencion = sum(row.get("retencion") for row in summary_data_rows)

        # Fila de totales del resumen
        total_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=_("Totales"))
        total_cell.font = self.header_font
        total_cell.border = self.data_border
        self.sheet.merge_cells(
            start_row=current_row, start_column=summary_start_col,
            end_row=current_row, end_column=summary_start_col + 4
        )

        base_total_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=total_base)
        base_total_cell.font = self.header_font
        base_total_cell.number_format = self.numeric_format
        base_total_cell.border = self.data_border

        iva_total_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=total_iva)
        iva_total_cell.font = self.header_font
        iva_total_cell.number_format = self.numeric_format
        iva_total_cell.border = self.data_border

        retention_total_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=total_retencion)
        retention_total_cell.font = self.header_font
        retention_total_cell.number_format = self.numeric_format
        retention_total_cell.border = self.data_border

        return self.sheet.max_row

    def build(self):
        """
        Construye el libro de Excel orquestando los métodos de construcción.
        """
        try:
            # Restaurar los totales originales para la tabla de resumen principal
            original_summary_data = self.summary_data

            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)
            last_row_summary = self._build_summary_table(last_row_main_table)
            self._build_adjustments_table(last_row_summary)

            file_stream = BytesIO()
            self.summary_data = original_summary_data # Restaurar por si acaso
            self.workbook.save(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            frappe.throw(_("Ocurrió un error al construir el archivo de Excel: {0}").format(e))

@frappe.whitelist()
def create_excel_file(report_name, filters=None, **kwargs):
    """
    Genera el archivo de Excel directamente y lo guarda.
    """
    if not filters:
        filters = kwargs.get("filters_json")

    if isinstance(filters, str):
        filters = json.loads(filters)

    try:
        columns = get_columns()
        main_data, adjustment_data = get_sales_data(filters)

        counter_column = {
            "label": "Nr Oper.",
            "fieldname": "sequence_number",
            "width": 20
        }
        columns.insert(0, counter_column)

        # Numerar ambas listas de datos
        all_data_for_numbering = main_data + adjustment_data
        for i, row in enumerate(all_data_for_numbering):
            row["sequence_number"] = i + 1

        if not main_data and not adjustment_data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

        # El resumen principal se basa ÚNICAMENTE en los datos del período. Los ajustes se manejan por separado.
        summary_data = get_total_row(main_data)

        company_doc = frappe.get_doc("Company", filters.get("company"))
        address_name = company_doc.get("custom_company_primary_address")
        company_address = frappe.db.get_value("Address", address_name, "address_line1") if address_name else _("Dirección no disponible")

        company_data = {
            "company_name": company_doc.company_name,
            "tax_id": company_doc.tax_id,
            "is_special_taxpayer": company_doc.is_special_taxpayer,
            "address": company_address
        }

        from_date = frappe.utils.getdate(filters.get("from_date"))
        to_date = frappe.utils.getdate(filters.get("to_date"))

        title = _("Libro de Ventas")

        builder = ExcelBuilder(
            title,
            columns,
            main_data,
            adjustment_data,
            summary_data,
            company_data,
            from_date,
            to_date,
        )
        excel_content = builder.build()

        excel_content_bytes = excel_content.getvalue()
        base64_content = base64.b64encode(excel_content_bytes).decode('utf-8')

        return {
            "type": "download",
            "filename": f"{title}.xlsx",
            "filecontent": base64_content
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en create_excel_file")
        frappe.throw(_("Ocurrió un error al generar el archivo de Excel: {0}").format(e))