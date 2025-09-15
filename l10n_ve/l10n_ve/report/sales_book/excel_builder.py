import frappe
from frappe import _
import json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
import base64
# Importamos las funciones directamente del reporte para obtener los datos
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_columns, get_sales_data, get_total_row

class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria con formato profesional.
    Ahora incluye un encabezado de dos niveles para mayor claridad en el reporte.
    """
    def __init__(self, title, columns, data, summary_data, company_data, from_date, to_date):
        self.title = title
        self.data = data
        self.columns = columns
        self.summary_data = summary_data
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Reporte"
        
        # Definimos los estilos comunes
        self.header_font = Font(bold=True)
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
        
        # Ajustamos el ancho de las columnas
        self.sheet.column_dimensions[get_column_letter(1)].width = 30
        self.sheet.column_dimensions[get_column_letter(2)].width = 40
        self.sheet.column_dimensions[get_column_letter(3)].width = 30
        self.sheet.column_dimensions[get_column_letter(4)].width = 40
        # Ahora el espacio está en la columna E (columna 5).
        self.sheet.column_dimensions[get_column_letter(5)].width = 15
        
        title_font = Font(bold=True)
        
        # Bloque superior: Nombre y RIF
        self.sheet.cell(row=current_row, column=1, value=_("Nombre o Razón Social:")).font = title_font
        self.sheet.cell(row=current_row, column=4, value=_("Número de Registro de Información Fiscal (RIF):")).font = title_font
        
        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=self.company_data.get("company_name"))
        self.sheet.cell(row=current_row, column=4, value=self.company_data.get("tax_id"))
        
        current_row += 2
        
        # Bloque inferior: Dirección y Tipo de Contribuyente
        is_special_taxpayer_text = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("NO ESPECIAL")
        
        self.sheet.cell(row=current_row, column=1, value=_("Dirección:")).font = title_font
        self.sheet.cell(row=current_row, column=4, value=_("Tipo de Contribuyente:")).font = title_font
        
        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=self.company_data.get("address"))
        self.sheet.cell(row=current_row, column=4, value=is_special_taxpayer_text)
        
        current_row += 2
        
        # Período Fiscal
        self.sheet.cell(row=current_row, column=1, value=_("Período Fiscal:")).font = title_font
        current_row += 1
        self.sheet.cell(row=current_row, column=1, value=f"{self.from_date.strftime('%d-%m-%Y')} - {self.to_date.strftime('%d-%m-%Y')}")
        
        return current_row + 2

    def _build_main_table(self, start_row):
        """
        Construye la tabla principal con todos los datos y agrega un encabezado de dos niveles
        sobre las columnas específicas solicitadas.
        """
        current_row = start_row
        
        # --- Primer nivel de encabezados (subtítulos) ---
        # Definimos las posiciones de inicio y el texto de los encabezados de dos niveles
        headers_2level = {
            15: _("Ventas a Contribuyentes"),
            21: _("Ventas a No Contribuyentes"),
            
        }
        
        # Escribimos los títulos del primer nivel en la fila actual
        for col, header_text in headers_2level.items():
            cell = self.sheet.cell(row=current_row, column=col, value=header_text)
            cell.font = Font(bold=True)
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Combinamos las celdas para los títulos que agrupan
        # 'Ventas a Contribuyentes' abarca las columnas 10 y 11
        self.sheet.merge_cells(start_row=current_row, start_column=15, end_row=current_row, end_column=20)
        # 'Ventas a No Contribuyentes' abarca las columnas 12 y 13
        self.sheet.merge_cells(start_row=current_row, start_column=21, end_row=current_row, end_column=26)
        # 'Retención' y 'IGTF' son de una sola columna, no necesitan ser combinadas
        
        current_row += 1

        headers_3level = {
            15: _("Tasa Reducida 8%"),
            17: _("Tasa General 16%"),
            19: _("Tasa General + Adicional 31%"),
            21: _("Tasa Reducida 8%"),
            23: _("Tasa General 16%"),
            25: _("Tasa General + Adicional 31%"),
            27: _("Retención"),
            31: _("IGTF")

        }

        for col, header_text in headers_3level.items():
            cell = self.sheet.cell(row=current_row, column=col, value=header_text)
            cell.font = Font(bold=True)
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        self.sheet.merge_cells(start_row=current_row, start_column=15, end_row=current_row, end_column=16)
        # 'Ventas a No Contribuyentes' abarca las columnas 12 y 13
        self.sheet.merge_cells(start_row=current_row, start_column=17, end_row=current_row, end_column=18)
        self.sheet.merge_cells(start_row=current_row, start_column=19, end_row=current_row, end_column=20)
        # 'Ventas a No Contribuyentes' abarca las columnas 12 y 13
        self.sheet.merge_cells(start_row=current_row, start_column=21, end_row=current_row, end_column=22) 
        self.sheet.merge_cells(start_row=current_row, start_column=23, end_row=current_row, end_column=24)
        # 'Ventas a No Contribuyentes' abarca las columnas 12 y 13
        self.sheet.merge_cells(start_row=current_row, start_column=25, end_row=current_row, end_column=26)     
        self.sheet.merge_cells(start_row=current_row, start_column=27, end_row=current_row, end_column=30)
        self.sheet.merge_cells(start_row=current_row, start_column=31, end_row=current_row, end_column=33)
        current_row += 1
        # --- Segundo nivel de encabezados (detalles) ---
        # Ahora escribimos todos los encabezados originales en la siguiente fila
        main_table_headers = [col.get("label") for col in self.columns]
        for col_index, header in enumerate(main_table_headers, start=1):
            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = Font(bold=True)
            cell.border = self.data_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            self.sheet.row_dimensions[current_row].height = 40
        
        # Ajustar el ancho de las columnas basado en los encabezados del segundo nivel
        column_widths = {get_column_letter(i + 1): len(header) + 2 for i, header in enumerate(main_table_headers)}

        # Agregar los datos y aplicar estilos
        row_index = current_row + 1
        for row_data in self.data:
            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)
                
                cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                cell.border = self.data_border
                cell.alignment = self.data_alignment
                
                # Aplicamos formato numérico si es un número
                if isinstance(cell_value, (int, float)):
                    if fieldname == "sequence_number":
                        # Formato para el contador (entero)
                        cell.number_format = self.int_format
                    else:
                        # Formato para los demás números (con decimales)
                        cell.number_format = self.numeric_format
                # Calcular el ancho de la columna basado en los datos
                cell_length = len(str(cell_value)) if cell_value is not None else 0
                col_letter = get_column_letter(col_index)
                column_widths[col_letter] = max(column_widths.get(col_letter, 0), cell_length + 2)
            row_index += 1
        
        # Aplicar los anchos de columna finales
        for col, width in column_widths.items():
            self.sheet.column_dimensions[col].width = width
        
        return self.sheet.max_row
    
   
    
    def _build_summary_table(self, start_row):
        """
        Construye la tabla de resumen con 4 columnas y el mismo estilo,
        ahora con la columna 'Concepto' ocupando 2 celdas.
        """
        current_row = start_row + 2
        
        # Definimos la columna de inicio para centrar la tabla
        summary_start_col = 10

        # Escribimos el título de la tabla
        self.sheet.cell(row=current_row, column=summary_start_col, value=_("Resumen de Totales")).font = Font(bold=True, size=12)
        
        # Encabezados de la tabla de resumen
        summary_row_index = current_row + 1
        summary_headers = [_("Concepto"), _("Base Imponible"), _("Débito Fiscal"), _("Retención")]
        
        # Escribimos y fusionamos la celda de 'Concepto'
        self.sheet.cell(row=summary_row_index, column=summary_start_col, value=summary_headers[0]).font = Font(bold=True)
        self.sheet.cell(row=summary_row_index, column=summary_start_col).border = self.data_border
        self.sheet.merge_cells(start_row=summary_row_index, start_column=summary_start_col, end_row=summary_row_index, end_column=summary_start_col + 1)

        # Escribimos los demás encabezados
        for col_index, header_text in enumerate(summary_headers[1:], start=summary_start_col + 2):
            cell = self.sheet.cell(row=summary_row_index, column=col_index, value=header_text)
            cell.font = Font(bold=True)
            cell.border = self.data_border

        # Ajustar el ancho de las columnas para la tabla de resumen
        self.sheet.column_dimensions[get_column_letter(summary_start_col)].width = 25
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 1)].width = 25
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 2)].width = 15
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 3)].width = 15
        self.sheet.column_dimensions[get_column_letter(summary_start_col + 4)].width = 15

        summary_row_index += 1

        # Definimos los datos de las filas de resumen
        summary_data_rows = [
            {
                "concepto": _("De las Ventas Internas NO Gravadas"),
                "base": self.summary_data.get("non_taxable_internal_sales", 0),
                "iva": 0,
                "retencion": 0
            },
            {
                "concepto": _("Ventas de exportación"),
                "base": 0,
                "iva": 0,
                "retencion": 0
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota General"),
                "base": self.summary_data.get("base_general_taxpayer", 0) + self.summary_data.get("base_general_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_general_taxpayer", 0) + self.summary_data.get("iva_general_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_general", 0)
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota General + Adicional"),
                "base": self.summary_data.get("base_additional_taxpayer", 0) + self.summary_data.get("base_additional_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_additional_taxpayer", 0) + self.summary_data.get("iva_additional_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_additional", 0)
            },
            {
                "concepto": _("De las Ventas Internas Solo Afecta Alicuota Reducida)"),
                "base": self.summary_data.get("base_reduced_taxpayer", 0) + self.summary_data.get("base_reduced_non_taxpayer", 0),
                "iva": self.summary_data.get("iva_reduced_taxpayer", 0) + self.summary_data.get("iva_reduced_non_taxpayer", 0),
                "retencion": self.summary_data.get("iva_retained_reduced", 0)
            }
        ]

        # Escribir las filas de resumen
        for row_data in summary_data_rows:
            self.sheet.cell(row=summary_row_index, column=summary_start_col, value=row_data.get("concepto")).border = self.data_border
            self.sheet.cell(row=summary_row_index, column=summary_start_col, value=row_data.get("concepto")).alignment = self.data_alignment
            self.sheet.merge_cells(start_row=summary_row_index, start_column=summary_start_col, end_row=summary_row_index, end_column=summary_start_col + 1)
            
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 2, value=row_data.get("base")).number_format = self.numeric_format
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 2).border = self.data_border
            
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 3, value=row_data.get("iva")).number_format = self.numeric_format
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 3).border = self.data_border
            
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 4, value=row_data.get("retencion")).number_format = self.numeric_format
            self.sheet.cell(row=summary_row_index, column=summary_start_col + 4).border = self.data_border
            summary_row_index += 1
            
        # Escribir la fila de totales
        current_row = self.sheet.max_row + 1
        total_base = sum(row.get("base") for row in summary_data_rows)
        total_iva = sum(row.get("iva") for row in summary_data_rows)
        total_retencion = self.summary_data.get("iva_retained", 0)
        
        self.sheet.cell(row=current_row, column=summary_start_col, value=_("Totales")).font = Font(bold=True)
        self.sheet.cell(row=current_row, column=summary_start_col).border = self.data_border
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 1)
        
        self.sheet.cell(row=current_row, column=summary_start_col + 2, value=total_base).number_format = self.numeric_format
        self.sheet.cell(row=current_row, column=summary_start_col + 2).border = self.data_border
        
        self.sheet.cell(row=current_row, column=summary_start_col + 3, value=total_iva).number_format = self.numeric_format
        self.sheet.cell(row=current_row, column=summary_start_col + 3).border = self.data_border
        
        self.sheet.cell(row=current_row, column=summary_start_col + 4, value=total_retencion).number_format = self.numeric_format
        self.sheet.cell(row=current_row, column=summary_start_col + 4).border = self.data_border
            
    def build(self):
        """
        Construye el libro de Excel orquestando los métodos de construcción.
        """
        try:
            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)
            self._build_summary_table(last_row_main_table)

            file_stream = BytesIO()
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
        data = get_sales_data(filters)

        counter_column = {
            "label": "Nr Oper.",
            "fieldname": "sequence_number",
            "width": 50
        }
        columns.insert(0, counter_column)
        for i, row in enumerate(data):
            row["sequence_number"] = i + 1
        
        if not data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))
        
        summary_data = get_total_row(data)
         
        total_summary_row = get_total_row(data)
    
        data.append(total_summary_row) 

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
            data,
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