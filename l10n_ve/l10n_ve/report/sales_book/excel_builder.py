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
    def __init__(self, title, columns, data):
        self.title = title
        self.data = data
        self.columns = columns
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


    def build(self):
        """
        Construye el libro de Excel y devuelve un objeto BytesIO.
        Esta versión optimiza la escritura y el formateado.
        """
        try:
            # 1. Título principal del reporte
            self.sheet["A1"] = self.title
            self.sheet["A1"].font = Font(size=14, bold=True)
            
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
    # Si los filtros no se pasan directamente, buscamos en los argumentos del request
    if not filters:
        filters = kwargs.get("filters_json")
    
    if isinstance(filters, str):
        filters = json.loads(filters)
    
    try:
        columns = get_columns()
        data = get_sales_data(filters)

        if not data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

        total_row = get_total_row(data)
        data.append(total_row)

        title = "Libro de Ventas"
        builder = ExcelBuilder(title, columns, data)
        excel_content = builder.build()

        # Usar la clase File para guardar el archivo, compatible con Frappe 15
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"{title}.xlsx",
            "attached_to_doctype": "Report",
            "attached_to_name": report_name,
            "content": excel_content.getvalue(),
            "is_private": 1
        })
        file_doc.insert(ignore_permissions=True)

        # Retornar la URL del archivo para que el navegador lo descargue
        return file_doc.file_url

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en create_excel_file")
        frappe.throw(_("Ocurrió un error al generar el archivo de Excel: {0}").format(e))
