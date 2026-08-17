import json
import io
import frappe
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from frappe.utils import formatdate, nowdate, flt
from l10n_ve.l10n_ve.report.vat_report.vat_report import get_data, _get_date_range_from_filters
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data

def _get_company_details(company_name):
    if not company_name:
        return {"name": "EMPRESA", "rif": "", "address": ""}
    company_doc = frappe.get_cached_doc("Company", company_name)
    company_rif = company_doc.get("tax_id") or ""
    company_address = ""
    if company_doc.get("custom_company_primary_address"):
        try:
            address_doc = frappe.get_cached_doc("Address", company_doc.get("custom_company_primary_address"))
            company_address = address_doc.address_line1
        except Exception:
            frappe.log_error(title="Error obteniendo dirección de empresa")
    return {"name": company_name, "rif": company_rif, "address": company_address}

@frappe.whitelist()
def download_custom_excel(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)

    # Replicar lógica de ejecución del reporte
    from_date, to_date = _get_date_range_from_filters(filters)
    if from_date and to_date:
        filters["from_date"] = from_date
        filters["to_date"] = to_date

    main_data, adjustment_data = get_sales_data(filters)
    data = get_data(main_data)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reporte IVA"

    bold_font = Font(bold=True)
    center_align = Alignment(horizontal="center")
    green_fill = PatternFill(start_color="D8E4BC", end_color="D8E4BC", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    company_details = _get_company_details(filters.get("company"))

    ws["A1"] = company_details.get("name")
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = f"R.I.F.: {company_details.get('rif')}"
    ws["A3"] = f"Dirección: {company_details.get('address')}"
    ws["A4"] = f"Fecha de Emisión: {formatdate(nowdate())}"

    ws.merge_cells('A5:J5')
    ws["A5"] = "REPORTE DE CONTROL DE IVA (VENTAS)"
    ws["A5"].font = bold_font
    ws["A5"].alignment = center_align
    ws["A5"].fill = green_fill

    headers = [
        "Fecha", "Sucursal", "Cliente", "RIF / CI", "Tipo", 
        "Nro. Factura", "Nro. Control", "Monto de la base", "Total IVA", "Total"
    ]

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_num, value=header)
        cell.font = bold_font
        cell.border = thin_border
        cell.fill = green_fill

    row_num = 7
    total_base = 0
    total_iva = 0
    total_grand = 0

    for d in data:
        ws.cell(row=row_num, column=1, value=formatdate(d.get("posting_date")))
        ws.cell(row=row_num, column=2, value=d.get("branch"))
        ws.cell(row=row_num, column=3, value=(d.get("customer_name") or "").replace("<b>", "").replace("</b>", ""))
        ws.cell(row=row_num, column=4, value=d.get("customer_tax_id"))
        ws.cell(row=row_num, column=5, value=d.get("document_type"))
        ws.cell(row=row_num, column=6, value=d.get("bill_no"))
        ws.cell(row=row_num, column=7, value=d.get("bill_control"))
        
        cell_base = ws.cell(row=row_num, column=8, value=flt(d.get("taxable_base")))
        cell_base.number_format = '#,##0.00'
        
        cell_iva = ws.cell(row=row_num, column=9, value=flt(d.get("tax_amount")))
        cell_iva.number_format = '#,##0.00'
        
        cell_total = ws.cell(row=row_num, column=10, value=flt(d.get("grand_total")))
        cell_total.number_format = '#,##0.00'
        
        total_base += flt(d.get("taxable_base", 0))
        total_iva += flt(d.get("tax_amount", 0))
        total_grand += flt(d.get("grand_total", 0))
        row_num += 1

    # Fila de totales
    row_num += 1
    ws.cell(row=row_num, column=7, value="TOTALES:").font = bold_font
    ws.cell(row=row_num, column=7).alignment = Alignment(horizontal="right")
    
    for col, val in [(8, total_base), (9, total_iva), (10, total_grand)]:
        cell = ws.cell(row=row_num, column=col, value=val)
        cell.number_format = '#,##0.00'
        cell.font = bold_font

    # Ajustar anchos
    ws.column_dimensions['C'].width = 30
    for col_idx in [1, 2, 4, 6, 7, 8, 9, 10]:
        ws.column_dimensions[get_column_letter(col_idx)].width = 15

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    content = output.read()

    frappe.local.response.filename = f"Reporte_IVA_{nowdate()}.xlsx"
    frappe.local.response.filecontent = content
    frappe.local.response.type = "binary"
