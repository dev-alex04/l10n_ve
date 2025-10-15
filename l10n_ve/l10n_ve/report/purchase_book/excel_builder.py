import frappe
from frappe import _
import json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from datetime import datetime
import base64
from l10n_ve.l10n_ve.report.purchase_book.purchase_book import execute, get_totals_from_data

class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria para el Libro de Compras.
    """
    def __init__(self, title, columns, data, totals, company_data, from_date, to_date, report_summary):
        self.title = title
        self.columns = columns
        self.totals = totals
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date
        self.report_summary = report_summary

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Reporte de Compras"

        # Definimos los estilos comunes
        self.default_font = Font(name='Calibri', size=8)
        self.header_font = Font(name='Calibri', size=8, bold=True)
        self.total_font = Font(name='Calibri', size=8, bold=True)
        self.data_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'
        self.int_format = '0'


        all_data = self.process_data(data)
        self.adjustment_data = [row for row in all_data if row.get("transaction_type") == "04-Ajuste"]
        self.data = [row for row in all_data if row.get("transaction_type") != "04-Ajuste"]
        self.totals = get_totals_from_data(self.data) # Recalcular totales solo para datos principales

    def _add_report_header(self):
        """
        Agrega el encabezado con los datos de la compañía en un formato estructurado.
        """
        current_row = 1

        self.sheet.cell(row=current_row, column=1, value=_("Libro de Compras Fiscal")).font = Font(size=14, bold=True)

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

        self.sheet.cell(row=current_row, column=1, value=_("Dirección:")).font = title_font
        self.sheet.cell(row=current_row, column=12, value=_("Tipo de Contribuyente:")).font = title_font

        current_row += 1
        is_special_taxpayer_text = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("NO ESPECIAL")
        self.sheet.cell(row=current_row, column=1, value=self.company_data.get("address"))
        self.sheet.cell(row=current_row, column=12, value=is_special_taxpayer_text)

        current_row += 2

        self.sheet.cell(row=current_row, column=1, value=_("Período Fiscal:")).font = title_font
        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=f"{self.from_date.strftime('%d-%m-%Y')} - {self.to_date.strftime('%d-%m-%Y')}")

        return current_row + 2

    def _build_multi_level_headers(self, start_row: int) -> int:
        """Construye los encabezados de varios niveles para la tabla principal."""
        current_row = start_row

        header_levels = [
            [{"text": _("Compras a Contribuyentes"), "start_col": 16, "span": 6}],
            [
                {"text": _("Tasa Reducida 8%"), "start_col": 16, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": 18, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": 20, "span": 2},
                {"text": _("Retención"), "start_col": 23, "span":5},
            ],
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
                        end_column=header_info["start_col"] + header_info["span"] - 1,
                    )
            current_row += 1

        for col_index, col_def in enumerate(self.columns, start=1):
            header = col_def.get("label")
            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            self.sheet.row_dimensions[current_row].height = 25
            self.sheet.column_dimensions[get_column_letter(col_index)].width = (
                5 if col_def.get("fieldname") == "sequence_number" else 10
            )

        return current_row

    def _write_data_rows(self, start_row: int) -> int:
        """Escribe las filas de datos en la tabla principal."""
        row_index = start_row + 1
        for row_data in self.data:
            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)

                cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                cell.font = self.default_font
                cell.border = self.data_border

                if isinstance(cell_value, (int, float)):
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    cell.number_format = self.int_format if fieldname == "sequence_number" else self.numeric_format
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

            self.sheet.row_dimensions[row_index].height = None
            row_index += 1
        return row_index

    def _write_totals_row(self, start_row: int) -> int:
        """Escribe la fila de totales al final de la tabla principal."""
        total_row_index = start_row + 1
        total_label_cell = self.sheet.cell(row=total_row_index, column=1, value=_("Totales"))
        total_label_cell.font = self.total_font
        total_label_cell.border = self.data_border

        for col_index, col in enumerate(self.columns, start=1):
            fieldname = col.get("fieldname")
            if fieldname in self.totals:
                total_value = self.totals.get(fieldname)
                total_cell = self.sheet.cell(row=total_row_index, column=col_index, value=total_value)
                total_cell.font = self.total_font
                total_cell.border = self.data_border
                total_cell.number_format = self.numeric_format
                total_cell.alignment = Alignment(horizontal="right", vertical="center")

        return total_row_index

    def _build_main_table(self, start_row: int) -> int:
        """Construye la tabla principal con encabezados, datos y totales."""
        headers_last_row = self._build_multi_level_headers(start_row)
        data_last_row = self._write_data_rows(headers_last_row)
        totals_last_row = self._write_totals_row(data_last_row)
        return totals_last_row

    def _build_adjustments_table(self, start_row: int) -> int:
        """Construye una tabla separada para las transacciones de ajuste."""
        if not self.adjustment_data:
            return start_row

        current_row = start_row + 2

        # Título para la tabla de ajustes
        title_cell = self.sheet.cell(row=current_row, column=1, value=_("Ajustes de Períodos Anteriores"))
        title_cell.font = Font(size=12, bold=True)
        current_row += 2

        # Guardar y restaurar datos originales para construir la tabla
        original_data, original_totals = self.data, self.totals
        self.data = self.adjustment_data
        self.totals = get_totals_from_data(self.adjustment_data)

        # Reutilizar la lógica de construcción de la tabla principal
        last_row = self._build_main_table(current_row)

        # Restaurar datos originales
        self.data, self.totals = original_data, original_totals

        return last_row

    def _add_summary_table(self, start_row: int) -> int:
        """Construye la tabla de resumen de totales."""
        if not self.totals:
            return start_row

        current_row = start_row + 2
        summary_start_col = 13
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

        # Configuración de encabezados del resumen
        summary_headers = [
            {"text": _("RESUMEN"), "start_col": summary_start_col, "span": 5, "align": "center"},
            {"text": _("Base Imponible"), "start_col": summary_start_col + 5, "span": 1, "align": "center"},
            {"text": _("Crédito Fiscal"), "start_col": summary_start_col + 6, "span": 1, "align": "center"},
            {"text": _("Retención"), "start_col": summary_start_col + 7, "span": 1, "align": "center"},
        ]

        for header_info in summary_headers:
            cell = self.sheet.cell(row=current_row, column=header_info["start_col"], value=header_info["text"])
            cell.font = self.header_font
            cell.alignment = Alignment(horizontal=header_info["align"], vertical="center", wrap_text=True)
            self.sheet.column_dimensions[get_column_letter(header_info["start_col"])].width = 12
            if header_info["span"] > 1:
                self.sheet.merge_cells(
                    start_row=current_row,
                    start_column=header_info["start_col"],
                    end_row=current_row,
                    end_column=header_info["start_col"] + header_info["span"] - 1,
                )

        start_table_row = current_row
        current_row += 1

        summary_rows = [
                {"concept": _("Compras no Gravadas"), "base": self.totals.get("total_exempt", 0), "credit": 0, "retention": 0},
                {"concept": _("Compras de Importación"), "base": 0, "credit": 0, "retention": 0},
                {"concept": _("Compras internas (tasa general)"),
                "base": self.totals.get("base_general", 0),
                "credit": self.totals.get("impuesto_general", 0),
                "retention": self.totals.get("retencion_general", 0)},
                {"concept": _("Compras internas (tasa general + adicional)"),
                "base": self.totals.get("base_adicional", 0),
                "credit": self.totals.get("impuesto_adicional", 0),
                "retention": self.totals.get("retencion_adicional", 0)},
                {"concept": _("Compras internas (tasa reducida)"),
                "base": self.totals.get("base_reducida", 0),
                "credit": self.totals.get("impuesto_reducida", 0),
                "retention": self.totals.get("retencion_reducida", 0)},
                ]

        for row_data in summary_rows:
            concept_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=row_data["concept"])
            concept_cell.font = self.default_font
            self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

            base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=row_data["base"])
            credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=row_data["credit"])
            retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=row_data["retention"])

            for cell in [base_cell, credit_cell, retention_cell]:
                cell.font = self.default_font
                cell.number_format = self.numeric_format
                cell.alignment = Alignment(horizontal="right")
            current_row += 1

        # Fila de totales del resumen
        total_base = sum(row["base"] for row in summary_rows)
        total_credit = sum(row["credit"] for row in summary_rows)
        total_retention = sum(row["retention"] for row in summary_rows)

        total_label_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=_("Total"))
        total_label_cell.font = self.total_font
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

        total_base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=total_base)
        total_credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=total_credit)
        total_retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=total_retention)

        for cell in [total_base_cell, total_credit_cell, total_retention_cell]:
            cell.font = self.total_font
            cell.number_format = self.numeric_format
            cell.alignment = Alignment(horizontal="right")

        # Aplicar bordes a toda la tabla de resumen
        end_table_row = current_row
        start_col = summary_start_col
        end_col = summary_start_col + 7

        for r_idx in range(start_table_row, end_table_row + 2):
            for c_idx in range(start_col, end_col + 1):
                cell = self.sheet.cell(row=r_idx, column=c_idx)
                cell.border = Border(
                    left=thin_border.left if c_idx == start_col else None,
                    right=thin_border.right if c_idx == end_col else None,
                    top=thin_border.top if r_idx == start_table_row else None,
                    bottom=thin_border.bottom if r_idx == end_table_row + 1 else None,
                )

        return self.sheet.max_row

    def build(self):
        """
        Construye el libro de Excel orquestando los métodos de construcción.
        """
        try:
            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)
            last_row_summary = self._add_summary_table(last_row_main_table)
            self._build_adjustments_table(last_row_summary)

            file_stream = BytesIO()
            self.workbook.save(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            frappe.throw(_("Ocurrió un error al construir el archivo de Excel: {0}").format(e))


    def process_data(self, data: list[dict]) -> list[dict]:
        processed_data = []

        for invoice in data:
            processed_invoice = invoice.copy()

            processed_invoice['fecha_entrega'] = ''
            processed_invoice['porcentaje_ret'] = ''
            processed_invoice['taxes_and_charges_deducted'] = 0.0
            processed_invoice['nro_comprobante_retencion'] = ''

            if invoice.get("nro_comprobante_retencion"):

                withholding_voucher = invoice.copy()

                withholding_voucher['bill_no'] = ''
                withholding_voucher['grand_total'] = 0.0
                withholding_voucher['bill_control'] = ''
                withholding_voucher['base_general'] = 0.0
                withholding_voucher['base_reducida'] = 0.0
                withholding_voucher['base_adicional'] = 0.0
                withholding_voucher['impuesto_general'] = 0.0
                withholding_voucher['impuesto_reducida'] = 0.0
                withholding_voucher['impuesto_adicional'] = 0.0
                withholding_voucher['affected_invoice_number'] = invoice.get('bill_no')

                processed_data.append(withholding_voucher)

                pass

            processed_data.append(processed_invoice)

        # Asignar el número de secuencia después de procesar y duplicar filas
        for i, row in enumerate(processed_data):
            row["sequence_number"] = i + 1

        return processed_data

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

        columns, data, message, chart, report_summary = execute(filters)

        counter_column = {
            "label": "Nr Oper.",
            "fieldname": "sequence_number",
            "width": 50
        }
        columns.insert(0, counter_column)

        totals = get_totals_from_data(data)

        if not data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

        company_doc = frappe.get_doc("Company", filters.get("company"))
        address_name = company_doc.get("custom_company_primary_address")
        company_address = frappe.db.get_value("Address", address_name, "address_line1") if address_name else _("Dirección no disponible")

        company_data = {
            "company_name": company_doc.company_name,
            "tax_id": company_doc.tax_id,
            "is_special_taxpayer": company_doc.is_special_taxpayer,
            "address": company_address
        }

        from_date = frappe.utils.getdate(filters.get("date_from"))
        to_date = frappe.utils.getdate(filters.get("to_date"))

        title = _("Libro de Compras")

        builder = ExcelBuilder(
            title,
            columns,
            data,
            totals,
            company_data,
            from_date,
            to_date,
            report_summary
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