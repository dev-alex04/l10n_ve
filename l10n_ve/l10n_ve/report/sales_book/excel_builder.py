import frappe
from frappe import _
import json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from datetime import datetime

# Importamos la función get_column_letter para una correcta nomenclatura de las columnas
from openpyxl.utils import get_column_letter 

# Importamos las funciones directamente de tu reporte para obtener los datos
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_columns, get_sales_data, get_total_row

class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria con formato profesional.
    """
    def __init__(self, title, columns, data, summary_data, company_name, company_tax_id, company_is_special_taxpayer, from_date, to_date, company_address):
        self.title = title
        self.data = data
        self.columns = columns
        self.summary_data = summary_data
        self.company_name = company_name
        self.company_tax_id = company_tax_id
        self.company_is_special_taxpayer = company_is_special_taxpayer
        self.company_address = company_address
        self.from_date = from_date
        self.to_date = to_date

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Reporte"
        
        # Definimos los estilos una sola vez
        self.header_font = Font(bold=True)
        self.header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
        self.data_border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )
        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'

    def build(self):
        """
        Construye el libro de Excel y devuelve un objeto BytesIO.
        Esta versión optimiza la escritura y el formateado.
        """
        try:
            # 1. Encabezado del reporte
            current_row = 1
            self.sheet.cell(row=current_row, column=1, value=_("Libro de Ventas Fiscal")).font = Font(size=14, bold=True)
            
            current_row += 1
            self.sheet.cell(row=current_row, column=1, value=_("Nombre o Razón Social:")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=self.company_name)
            
            current_row += 1
            self.sheet.cell(row=current_row, column=1, value=_("Número de Registro de Información Fiscal (RIF):")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=self.company_tax_id)
            
            current_row += 1
           
            self.sheet.cell(row=current_row, column=1, value=_("Dirección:")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=self.company_address)
            current_row += 1
            
            is_special_taxpayer_text = _("ESPECIAL") if self.company_is_special_taxpayer else _("NO ESPECIAL")
            self.sheet.cell(row=current_row, column=1, value=_("Tipo de Contribuyente")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=is_special_taxpayer_text)

            current_row += 1
            self.sheet.cell(row=current_row, column=1, value=_("Período Fiscal:")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=f"{self.from_date.strftime('%d-%m-%Y')} - {self.to_date.strftime('%d-%m-%Y')}")
            
            current_row += 2 # Fila en blanco antes de los encabezados de la tabla
            
            # 2. Agregar los encabezados y sus estilos
            headers = [col.get("label") for col in self.columns]
            self.sheet.append(headers)
            header_row_number = self.sheet.max_row
            for cell in self.sheet[header_row_number]:
                cell.font = self.header_font
                cell.fill = self.header_fill
                cell.border = self.data_border
            
            # 3. Agregar los datos y aplicar estilos en una sola pasada
            column_widths = {}
            row_index = header_row_number + 1
            for row_data in self.data:
                for col_index, col in enumerate(self.columns, start=1):
                    fieldname = col.get("fieldname")
                    cell_value = row_data.get(fieldname)
                    
                    cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                    cell.border = self.data_border
                    cell.alignment = self.data_alignment

                    # Calcular el ancho de la columna de manera eficiente
                    cell_length = len(str(cell_value)) if cell_value is not None else 0
                    col_letter = get_column_letter(col_index)
                    column_widths[col_letter] = max(column_widths.get(col_letter, 0), cell_length)
                row_index += 1
            
            # 4. Ajustar el ancho de las columnas
            for col, width in column_widths.items():
                self.sheet.column_dimensions[col].width = width + 2

            # 5. Agregar el resumen de totales
            current_row = self.sheet.max_row + 2
            self.sheet.cell(row=current_row, column=1, value=_("Resumen de Totales")).font = Font(bold=True, size=12)
            
            # Encabezados de la tabla de resumen
            summary_row_index = current_row + 1
            summary_headers = [_("Concepto"), _("Base Imponible"), _("Débito Fiscal"), _("Retención")]
            self.sheet.append(summary_headers)
            
            # Aplicar estilos a los encabezados de la tabla de resumen
            for cell in self.sheet[summary_row_index]:
                cell.font = self.header_font
                cell.fill = self.header_fill
                cell.border = self.data_border
            
            summary_row_index += 1

            # Definimos los datos de las filas de resumen
            summary_data_rows = [
                {
                    "concepto": _("Ventas no grabadas"),
                    "base": self.summary_data.get("non_taxable_internal_sales", 0),
                    "iva":  0,
                    "retencion": 0
                },
                {
                    "concepto": _("Ventas de exportación"),
                    "base": 0,
                    "iva": 0,
                    "retencion": 0
                },
                 {
                    "concepto": _("Ventas alícuota general (16%)"),
                    "base": self.summary_data.get("base_general_taxpayer", 0) + self.summary_data.get("base_general_non_taxpayer", 0),
                    "iva": self.summary_data.get("iva_general_taxpayer", 0) + self.summary_data.get("iva_general_non_taxpayer", 0),
                    "retencion": self.summary_data.get("iva_retained", 0)
                },
                {
                    "concepto": _("Ventas alícuota general + adicional (31%)"),
                    "base": self.summary_data.get("base_additional_taxpayer", 0) + self.summary_data.get("base_additional_non_taxpayer", 0),
                    "iva": self.summary_data.get("iva_additional_taxpayer", 0) + self.summary_data.get("iva_additional_non_taxpayer", 0),
                    "retencion": self.summary_data.get("iva_retained", 0)
                },
                {
                    "concepto": _("Ventas alícuota reducida (8%)"),
                    "base": self.summary_data.get("base_reduced_taxpayer", 0) + self.summary_data.get("base_reduced_non_taxpayer", 0),
                    "iva": self.summary_data.get("iva_reduced_taxpayer", 0) + self.summary_data.get("iva_reduced_non_taxpayer", 0),
                    "retencion": self.summary_data.get("iva_retained_reduced", 0)
                }
            ]

            # Escribir las filas de resumen
            for row_data in summary_data_rows:
                row = summary_row_index
                self.sheet.cell(row=row, column=1, value=row_data.get("concepto"))
                self.sheet.cell(row=row, column=2, value=row_data.get("base")).number_format = self.numeric_format
                self.sheet.cell(row=row, column=3, value=row_data.get("iva")).number_format = self.numeric_format
                self.sheet.cell(row=row, column=4, value=row_data.get("retencion")).number_format = self.numeric_format
                
                # Aplicar bordes a las celdas
                for col in range(1, 5):
                    self.sheet.cell(row=row, column=col).border = self.data_border

                summary_row_index += 1

            # Escribir la fila de totales
            current_row = summary_row_index
            
            # Calcular los totales
            total_base = sum(row.get("base") for row in summary_data_rows)
            total_iva = sum(row.get("iva") for row in summary_data_rows)
            total_retencion = self.summary_data.get("iva_retained", 0) # Retención total del reporte
            
            self.sheet.cell(row=current_row, column=1, value=_("Totales")).font = self.header_font
            self.sheet.cell(row=current_row, column=2, value=total_base).number_format = self.numeric_format
            self.sheet.cell(row=current_row, column=3, value=total_iva).number_format = self.numeric_format
            self.sheet.cell(row=current_row, column=4, value=total_retencion).number_format = self.numeric_format
            
            for col in range(1, 5):
                self.sheet.cell(row=current_row, column=col).border = self.data_border

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

        if not data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

        # 1. Obtenemos la fila de totales y resumen de los datos originales.
        total_summary_row = get_total_row(data)

        

        # 2. Agregamos esta fila de totales a la lista de datos para la tabla principal.
        data.append(total_summary_row) 
        
        # Obtener los datos de la compañía de manera segura
        company_name = frappe.db.get_value("Company", filters.get("company"), "company_name")
        company_tax_id = frappe.db.get_value("Company", filters.get("company"), "tax_id")
        
        company_address = _("Dirección no disponible")
        company_is_special_taxpayer = False
        
        try:
            company_doc = frappe.get_doc("Company", filters.get("company"))
            address_name = company_doc.get("custom_company_primary_address")
            
            if address_name:
                company_address = frappe.db.get_value("Address", address_name, "address_line1")
            
            company_is_special_taxpayer = frappe.db.get_value("Company", filters.get("company"), "is_special_taxpayer")
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), f"Error al obtener datos de la compañía: {e}")
            
        from_date = frappe.utils.getdate(filters.get("from_date"))
        to_date = frappe.utils.getdate(filters.get("to_date"))

        title = "Libro de Ventas"
        
        builder = ExcelBuilder(
            title, 
            columns, 
            data,
            total_summary_row, # Pasamos la fila de totales ya calculada
            company_name, 
            company_tax_id, 
            company_is_special_taxpayer, 
            from_date, 
            to_date, 
            company_address
        )
        excel_content = builder.build()

        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"{title}.xlsx",
            "attached_to_doctype": "Report",
            "attached_to_name": report_name,
            "content": excel_content.getvalue(),
            "is_private": 1
        })
        file_doc.insert(ignore_permissions=True)

        return file_doc.file_url

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en create_excel_file")
        frappe.throw(_("Ocurrió un error al generar el archivo de Excel: {0}").format(e))