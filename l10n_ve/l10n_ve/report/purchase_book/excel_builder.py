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
        self.header_font = Font(bold=True)
        self.total_font = Font(bold=True)
        self.data_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'
        self.int_format = '0'

        self.data = self.process_data(data)

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

    def _build_main_table(self, start_row):
        """
        Construye la tabla principal con todos los datos y agrega una fila de totales al final.
        """
        current_row = start_row + 1

        headers_2level = {
            16: _("Compras a Contribuyentes"),
        }

        # Escribimos los títulos del primer nivel en la fila actual
        for col, header_text in headers_2level.items():
            cell = self.sheet.cell(row=current_row, column=col, value=header_text)
            cell.font = Font(bold=True)
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        self.sheet.merge_cells(start_row=current_row, start_column=16, end_row=current_row, end_column=21)

        current_row += 1

        headers_3level = {
            16: _("Tasa Reducida 8%"),
            18: _("Tasa General 16%"),
            20: _("Tasa General + Adicional 31%"),
            22: _("Retención"),
        }

        for col, header_text in headers_3level.items():
            cell = self.sheet.cell(row=current_row, column=col, value=header_text)
            cell.font = Font(bold=True)
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        self.sheet.merge_cells(start_row=current_row, start_column=16, end_row=current_row, end_column=17)

        self.sheet.merge_cells(start_row=current_row, start_column=18, end_row=current_row, end_column=19)
        self.sheet.merge_cells(start_row=current_row, start_column=20, end_row=current_row, end_column=21)

        self.sheet.merge_cells(start_row=current_row, start_column=22, end_row=current_row, end_column=25)

        current_row += 1

        # Escribimos los encabezados de las columnas
        for col_index, col_def in enumerate(self.columns, start=1):
            header = col_def.get("label")
            fieldname = col_def.get("fieldname")

            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            self.sheet.row_dimensions[current_row].height = 45

            # Asignar anchos de columna específicos
            self.sheet.column_dimensions[get_column_letter(col_index)].width = 5 if fieldname == "sequence_number" else 11

        row_index = current_row + 1
        for row_data in self.data:
            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)

                cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                cell.border = self.data_border

                if isinstance(cell_value, (int, float)):
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    if fieldname == "sequence_number":
                        cell.number_format = self.int_format
                    else:
                        cell.number_format = self.numeric_format
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

            self.sheet.row_dimensions[row_index].height = None # Permite el ajuste automático de altura
            row_index += 1

        row_index += 1

        total_row_index = row_index

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
                total_cell.alignment = self.data_alignment

        return self.sheet.max_row

    def _add_summary_table(self, start_row):
        if not self.totals:
            return start_row

        current_row = start_row + 5

        offset_resumen = 12
        offset_vacio1 = offset_resumen + 1
        offset_vacio2 = offset_resumen + 2
        offset_vacio3 = offset_resumen + 3
        offset_vacio4 = offset_resumen + 4
        offset_datos = offset_resumen + 5

        thin_border = Border(left=Side(style='thin'),
                            right=Side(style='thin'),
                            top=Side(style='thin'),
                            bottom=Side(style='thin'))

        no_border = Border(left=Side(style=None),
                        right=Side(style=None),
                        top=Side(style=None),
                        bottom=Side(style=None))

        resumen_cell = self.sheet.cell(row=current_row, column=1 + offset_resumen, value=_("RESUMEN"))
        resumen_cell.font = self.header_font
        resumen_cell.border = no_border
        resumen_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        for offset in [offset_vacio1, offset_vacio2, offset_vacio3, offset_vacio4]:
            cell = self.sheet.cell(row=current_row, column=1 + offset, value="")
            cell.font = self.header_font
            cell.border = no_border

        headers = [_("Base Imponible"), _("Crédito Fiscal"), _("Retención")]
        for col_index, header in enumerate(headers, start=1 + offset_datos):
            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font
            cell.border = no_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


        self.sheet.column_dimensions[get_column_letter(1 + offset_resumen)].width = 12
        self.sheet.column_dimensions[get_column_letter(1 + offset_vacio1)].width = 12
        self.sheet.column_dimensions[get_column_letter(1 + offset_vacio2)].width = 12
        self.sheet.column_dimensions[get_column_letter(1 + offset_vacio3)].width = 12
        self.sheet.column_dimensions[get_column_letter(1 + offset_vacio4)].width = 12
        self.sheet.column_dimensions[get_column_letter(1 + offset_datos)].width = 12
        self.sheet.column_dimensions[get_column_letter(2 + offset_datos)].width = 12
        self.sheet.column_dimensions[get_column_letter(3 + offset_datos)].width = 12

        start_table_row = current_row
        current_row += 1

        summary_rows = [
                {"concept": _("Compras no Gravadas"), "base": self.totals.get("total_exempt", 0), "credit": 0, "retention": 0},
                {"concept": _("Compras de Importación"), "base": 0, "credit": 0, "retention": 0},

                # Línea de Tasa General (ahora con la retención desglosada)
                {"concept": _("Compras internas (tasa general)"),
                "base": self.totals.get("base_general", 0),
                "credit": self.totals.get("impuesto_general", 0),
                "retention": self.totals.get("retencion_general", 0)},

                # Línea de Tasa General + Adicional (ahora con la retención desglosada)
                {"concept": _("Compras internas (tasa general + adicional)"),
                "base": self.totals.get("base_adicional", 0),
                "credit": self.totals.get("impuesto_adicional", 0),
                "retention": self.totals.get("retencion_adicional", 0)},

                # Línea de Tasa Reducida (ahora con la retención desglosada)
                {"concept": _("Compras internas (tasa reducida)"),
                "base": self.totals.get("base_reducida", 0),
                "credit": self.totals.get("impuesto_reducida", 0),
                "retention": self.totals.get("retencion_reducida", 0)},
                ]
        total_base = 0
        total_credit = 0
        total_retention = 0

        for row_data in summary_rows:
            self.sheet.cell(row=current_row, column=1 + offset_resumen, value=row_data["concept"]).border = no_border

            self.sheet.cell(row=current_row, column=1 + offset_vacio1).border = no_border

            self.sheet.cell(row=current_row, column=1 + offset_vacio2).border = no_border

            self.sheet.cell(row=current_row, column=1 + offset_vacio3).border = no_border

            self.sheet.cell(row=current_row, column=1 + offset_vacio4).border = no_border

            base_cell = self.sheet.cell(row=current_row, column=1 + offset_datos, value=row_data["base"])
            base_cell.border = no_border
            base_cell.number_format = self.numeric_format
            total_base += row_data["base"]

            credit_cell = self.sheet.cell(row=current_row, column=2 + offset_datos, value=row_data["credit"])
            credit_cell.border = no_border
            credit_cell.number_format = self.numeric_format
            total_credit += row_data["credit"]

            retention_cell = self.sheet.cell(row=current_row, column=3 + offset_datos, value=row_data["retention"])
            retention_cell.border = no_border
            retention_cell.number_format = self.numeric_format
            total_retention += row_data["retention"]

            current_row += 1

        end_table_row = current_row

        total_label_cell = self.sheet.cell(row=current_row, column=1 + offset_resumen, value=_("Total"))
        total_label_cell.font = self.total_font
        total_label_cell.border = no_border

        self.sheet.cell(row=current_row, column=1 + offset_vacio1).border = no_border

        self.sheet.cell(row=current_row, column=1 + offset_vacio2).border = no_border

        self.sheet.cell(row=current_row, column=1 + offset_vacio3).border = no_border

        self.sheet.cell(row=current_row, column=1 + offset_vacio4).border = no_border

        total_base_cell = self.sheet.cell(row=current_row, column=1 + offset_datos, value=total_base)
        total_base_cell.font = self.total_font
        total_base_cell.border = no_border
        total_base_cell.number_format = self.numeric_format

        total_credit_cell = self.sheet.cell(row=current_row, column=2 + offset_datos, value=total_credit)
        total_credit_cell.font = self.total_font
        total_credit_cell.border = no_border
        total_credit_cell.number_format = self.numeric_format

        total_retention_cell = self.sheet.cell(row=current_row, column=3 + offset_datos, value=total_retention)
        total_retention_cell.font = self.total_font
        total_retention_cell.border = no_border
        total_retention_cell.number_format = self.numeric_format

        current_row += 1


        start_col = 1 + offset_resumen
        end_col = 3 + offset_datos

        for r_idx in range(start_table_row, end_table_row + 1):
            for c_idx in range(start_col, end_col + 1):
                cell = self.sheet.cell(row=r_idx, column=c_idx)
                cell.border = Border(
                    left=thin_border.left if c_idx == start_col else None,
                    right=thin_border.right if c_idx == end_col else None,
                    top=thin_border.top if r_idx == start_table_row else None,
                    bottom=thin_border.bottom if r_idx == end_table_row else None,
                )

        return self.sheet.max_row

    def build(self):
        """
        Construye el libro de Excel orquestando los métodos de construcción.
        """
        try:
            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)

            # Agregamos la tabla resumen
            self._add_summary_table(last_row_main_table)

            file_stream = BytesIO()
            self.workbook.save(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            frappe.throw(_("Ocurrió un error al construir el archivo de Excel: {0}").format(e))


    def process_data(self, data: list[dict]) -> list[dict]:
        processesed_data = []

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

                processesed_data.append(withholding_voucher)

                pass

            processesed_data.append(processed_invoice)

        # Asignar el número de secuencia después de procesar y duplicar filas
        for i, row in enumerate(processesed_data):
            row["sequence_number"] = i + 1

        return processesed_data

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