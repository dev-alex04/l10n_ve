# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import json
import io
import frappe
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from l10n_ve.l10n_ve.report.igtf_received.igtf_received import get_data
from frappe.utils import fmt_money, formatdate, nowdate
from frappe.utils.pdf import get_pdf

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
def download_custom_excel(filters=None):
	if isinstance(filters, str):
		filters = json.loads(filters)

	data = get_data(filters)

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "IGTF Percibido"

	bold_font = Font(bold=True)
	center_align = Alignment(horizontal="center")
	green_fill = PatternFill(start_color="D8E4BC", end_color="D8E4BC", fill_type="solid")
	thin_border = Border(left=Side(style='thin'), right=Side(style='thin'),
						top=Side(style='thin'), bottom=Side(style='thin'))

	company_details = _get_company_details(filters.get("company"))

	ws["A1"] = company_details.get("name")
	ws["A1"].font = Font(bold=True, size=12)
	ws["A2"] = f"R.I.F.: {company_details.get('rif')}"
	ws["A3"] = f"Dirección: {company_details.get('address')}"
	ws["A4"] = f"Fecha de Emisión: {formatdate(nowdate())}"

	ws.merge_cells('A5:G5')
	ws["A5"] = "IGTF PERCIBIDo"
	ws["A5"].font = bold_font
	ws["A5"].alignment = center_align
	ws["A5"].fill = green_fill

	headers = [
		"Fecha", "Nro. Factura", "Nombre o razón social", "RIF",
		"Monto de factura", "Monto Sujeto", "Monto IGTF"
	]

	for col_num, header in enumerate(headers, 1):
		cell = ws.cell(row=6, column=col_num, value=header)
		cell.font = bold_font
		cell.border = thin_border
		cell.fill = green_fill

	row_num = 7
	total_base = sum(d.total or 0 for d in data)
	total_base_igtf = sum(d.base_igtf or 0 for d in data)
	total_igtf = sum(d.igtf_amount or 0 for d in data)

	for d in data:
		ws.cell(row=row_num, column=1, value=d.date)
		ws.cell(row=row_num, column=2, value=d.bill_no)
		ws.cell(row=row_num, column=3, value=d.customer)
		ws.cell(row=row_num, column=4, value=d.tax_id)
		ws.cell(row=row_num, column=5, value=d.total)
		ws.cell(row=row_num, column=6, value=d.base_igtf)
		ws.cell(row=row_num, column=7, value=d.igtf_amount)

		row_num += 1

	row_num += 1
	ws.cell(row=row_num, column=4, value="TOTALES").font = bold_font
	ws.cell(row=row_num, column=4).alignment = Alignment(horizontal="right")
	ws.cell(row=row_num, column=5, value=total_base).font = bold_font
	ws.cell(row=row_num, column=6, value=total_base_igtf).font = bold_font
	ws.cell(row=row_num, column=7, value=total_igtf).font = bold_font

	for col_idx in range(1, 8):
		max_length = 0
		for r in range(6, row_num + 1):
			cell_value = ws.cell(row=r, column=col_idx).value
			if cell_value:
				max_length = max(max_length, len(str(cell_value)))

		ws.column_dimensions[get_column_letter(col_idx)].width = max_length + 3

	output = io.BytesIO()
	wb.save(output)
	output.seek(0)
	content = output.read()

	frappe.local.response.filename = "Reporte_IGTF_Percibido.xlsx"
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"

@frappe.whitelist()
def download_custom_pdf(filters=None):
	if isinstance(filters, str):
		filters = json.loads(filters)

	data = get_data(filters)

	company_name = filters.get("company")
	company_details = _get_company_details(company_name)
	currency = frappe.get_cached_value('Company', company_name, 'default_currency') if company_name else None

	total_base = sum(d.total or 0 for d in data)
	total_base_igtf = sum(d.base_igtf or 0 for d in data)
	total_igtf = sum(d.igtf_amount or 0 for d in data)

	for d in data:
		d["total_formatted"] = fmt_money(d.total, currency=currency)
		d["base_igtf_formatted"] = fmt_money(d.base_igtf, currency=currency)
		d["igtf_amount_formatted"] = fmt_money(d.igtf_amount, currency=currency)
		d["date"] = formatdate(d.date)

	html_content = """
	<!DOCTYPE html>
	<html>
	<head>
		<meta charset="utf-8">
		<style>
			body { font-family: sans-serif; font-size: 8pt; }
			.header { text-align: center; margin-bottom: 10px; }
			.company-details { margin-bottom: 10px; }
			.company-name { font-size: 10pt; font-weight: bold; }
			table { width: 100%; border-collapse: collapse; margin-top: 5px; }
			th, td { border: 1px solid #000; padding: 2px; vertical-align: middle; }
			th { background-color: #D8E4BC; font-weight: bold; text-align: center; }
			.text-right { text-align: right; }
			.text-center { text-align: center; }
			.title-row { background-color: #D8E4BC; text-align: center; font-weight: bold; padding: 3px; border: 1px solid #000; }
		</style>
	</head>
	<body>
		<div class="company-details">
			<div class="company-name">{{ company_name }}</div>
			<div>R.I.F.: {{ company_rif }}</div>
			<div>Dirección: {{ company_address }}</div>
			<div>Fecha de Emisión: {{ print_date }}</div>
		</div>

		<div class="title-row">IGTF PERCIBIDO</div>

		<table>
			<thead>
				<tr>
					<th>Fecha</th>
					<th>Nro. Factura</th>
					<th>Nombre o razón social</th>
					<th>RIF</th>
					<th>Monto de factura</th>
					<th>Monto Sujeto</th>
					<th>Monto IGTF</th>
				</tr>
			</thead>
			<tbody>
				{% for row in data %}
				<tr>
					<td class="text-center">{{ row.date }}</td>
					<td class="text-center">{{ row.bill_no }}</td>
					<td>{{ row.customer }}</td>
					<td class="text-center">{{ row.tax_id }}</td>
					<td class="text-right">{{ row.total_formatted }}</td>
					<td class="text-right">{{ row.base_igtf_formatted }}</td>
					<td class="text-right">{{ row.igtf_amount_formatted }}</td>
				</tr>
				{% endfor %}
				<tr>
					<td colspan="7" style="border: none; height: 10px;"></td>
				</tr>
				<tr>
					<td colspan="4" class="text-right" style="font-weight: bold;">TOTALES</td>
					<td class="text-right" style="font-weight: bold;">{{ total_base }}</td>
					<td class="text-right" style="font-weight: bold;">{{ total_base_igtf }}</td>
					<td class="text-right" style="font-weight: bold;">{{ total_igtf }}</td>
				</tr>
			</tbody>
		</table>
	</body>
	</html>
	"""

	context = {
		"company_name": company_details.get("name"),
		"company_rif": company_details.get("rif"),
		"company_address": company_details.get("address"),
		"print_date": formatdate(nowdate()),
		"data": data,
		"total_base": fmt_money(total_base, currency=currency),
		"total_base_igtf": fmt_money(total_base_igtf, currency=currency),
		"total_igtf": fmt_money(total_igtf, currency=currency)
	}

	final_html = frappe.render_template(html_content, context)
	pdf_content = get_pdf(final_html)

	frappe.local.response.filename = "Reporte_IGTF_Percibido.pdf"
	frappe.local.response.filecontent = pdf_content
	frappe.local.response.type = "pdf"