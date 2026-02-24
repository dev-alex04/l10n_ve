
import frappe
import json
import io
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from frappe.utils import formatdate, nowdate, flt

from l10n_ve.l10n_ve.report.customer_retention.customer_retention import get_columns, get_data

def _get_company_details(company_name):
	"""
	Obtiene los detalles de la compañía (nombre, RIF, dirección) desde la cache.
	"""
	if not company_name:
		return {"name": "EMPRESA", "rif": "", "address": ""}

	company_doc = frappe.get_cached_doc("Company", company_name)
	company_rif = company_doc.get("tax_id") or ""
	company_address = ""

	if company_doc.get("custom_company_primary_address"):
		try:
			address_doc = frappe.get_cached_doc("Address", company_doc.get("custom_company_primary_address"))
			company_address = address_doc.address_line1
		except frappe.DoesNotExistError:
				pass

	return {"name": company_name, "rif": company_rif, "address": company_address}

@frappe.whitelist()
def get_customer_retention_excel(filters=None):
	if isinstance(filters, str):
		filters = json.loads(filters)

	data = get_data(filters)
	columns = get_columns()
	
	# Filtrar columnas no deseadas
	columns_to_remove = ["name", "retention_type", "voucher_image"]
	columns = [c for c in columns if c.get("fieldname") not in columns_to_remove]

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "Retención de Clientes"
	
	header_font = Font(bold=True)
	header_fill = PatternFill(start_color="D8E4BC", end_color="D8E4BC", fill_type="solid")
	thin_border = Border(left=Side(style='thin'), right=Side(style='thin'),
						 top=Side(style='thin'), bottom=Side(style='thin'))
	center_align = Alignment(horizontal="center")

	company_details = _get_company_details(filters.get("company"))

	ws["A1"] = company_details.get("name")
	ws["A1"].font = Font(bold=True, size=12)
	ws["A2"] = f"R.I.F.: {company_details.get('rif')}"
	ws["A3"] = f"Dirección: {company_details.get('address')}"
	ws["A4"] = f"Fecha de Emisión: {formatdate(nowdate())}"

	last_col_letter = openpyxl.utils.get_column_letter(len(columns))
	ws.merge_cells(f'A5:{last_col_letter}5')
	ws["A5"] = "RETENCIONES DE CLIENTES"
	ws["A5"].font = header_font
	ws["A5"].alignment = center_align
	ws["A5"].fill = header_fill
	
	col_widths = [0] * len(columns)
	row_num = 7
	for col_idx, col_def in enumerate(columns, 1):
		label = col_def.get('label')
		cell = ws.cell(row=row_num, column=col_idx, value=label)
		cell.font = header_font
		cell.fill = header_fill
		cell.border = thin_border
		if label:
			col_widths[col_idx-1] = max(col_widths[col_idx-1], len(str(label)))

	for row_data_dict in data:
		row_num += 1
		for col_idx, col_def in enumerate(columns, 1):
			cell_value = row_data_dict.get(col_def.get('fieldname'), '')
			ws.cell(row=row_num, column=col_idx, value=cell_value)
			if cell_value:
				col_widths[col_idx-1] = max(col_widths[col_idx-1], len(str(cell_value)))

	row_num += 2 
	
	total_base = 0
	total_grand = 0
	total_withheld = 0
	for d in data:
		total_base += flt(d.get('base_total'))
		total_grand += flt(d.get('grand_total'))
		total_withheld += flt(d.get('withholding_amount'))

	base_idx = next((i for i, c in enumerate(columns) if c.get('fieldname') == 'base_total'), -1) + 1
	grand_idx = next((i for i, c in enumerate(columns) if c.get('fieldname') == 'grand_total'), -1) + 1
	withheld_idx = next((i for i, c in enumerate(columns) if c.get('fieldname') == 'withholding_amount'), -1) + 1

	if base_idx > 1:
		ws.cell(row=row_num, column=base_idx - 1, value="TOTALES:").font = Font(bold=True)
		ws.cell(row=row_num, column=base_idx - 1).alignment = Alignment(horizontal="right")
		if base_idx - 2 >= 0:
			col_widths[base_idx - 2] = max(col_widths[base_idx - 2], len("TOTALES:"))

	for idx, val in [(base_idx, total_base), (grand_idx, total_grand), (withheld_idx, total_withheld)]:
		if idx > 0:
			c = ws.cell(row=row_num, column=idx, value=val)
			c.font = Font(bold=True)
			c.number_format = '#,##0.00'
			if val:
				col_widths[idx-1] = max(col_widths[idx-1], len(str(val)))

	for i, width in enumerate(col_widths, 1):
		ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = width + 2

	xlsx_file = io.BytesIO()
	wb.save(xlsx_file)
	xlsx_file.seek(0)

	frappe.response['filename'] = 'Retencion_Clientes.xlsx'
	frappe.response['filecontent'] = xlsx_file.getvalue()

	frappe.response['type'] = 'binary'
