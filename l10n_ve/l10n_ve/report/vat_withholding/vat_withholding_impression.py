import json
import io
import frappe
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from frappe.utils import fmt_money, formatdate, nowdate
from frappe.utils.pdf import get_pdf
from l10n_ve.l10n_ve.report.vat_withholding.vat_withholding import get_data

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
            frappe.log_error(frappe.get_traceback(), "Error al obtener la dirección de la empresa para el reporte de IVA")
            pass
    return {"name": company_name, "rif": company_rif, "address": company_address}

@frappe.whitelist()
def download_custom_excel(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)

    data = get_data(filters)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Retenciones IVA"

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

    ws.merge_cells('A5:L5')
    ws["A5"] = "REPORTE DETALLADO DE RETENCIONES IVA"
    ws["A5"].font = bold_font
    ws["A5"].alignment = center_align
    ws["A5"].fill = green_fill

    headers = [
        "RIF Proveedor", "Nombre del Proveedor", "Número de Factura", "Número de Control", "Fecha Factura", 
        "Impuesto", "Fecha Emisión", "Documento Retención", 
        "Base Imponible Bs", "Monto Retención Bs", "Estado del Documento", "Estado del Comprobante"
    ]

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_num, value=header)
        cell.font = bold_font
        cell.border = thin_border
        cell.fill = green_fill

    row_num = 7
    total_base = 0
    total_ret = 0

    for d in data:
        ws.cell(row=row_num, column=1, value=d.tax_id)
        ws.cell(row=row_num, column=2, value=d.supplier)
        ws.cell(row=row_num, column=3, value=d.bill_no)
        ws.cell(row=row_num, column=4, value=d.bill_control)
        cell_date = ws.cell(row=row_num, column=5, value=d.posting_date)
        cell_date.number_format = 'DD-MM-YYYY'
        cell_date.alignment = Alignment(horizontal="center")
        ws.cell(row=row_num, column=6, value=d.tax_withholding_category)
        cell_issue = ws.cell(row=row_num, column=7, value=d.issue_date)
        cell_issue.number_format = 'DD-MM-YYYY'
        cell_issue.alignment = Alignment(horizontal="center")
        ws.cell(row=row_num, column=8, value=d.voucher_number)
        cell_base = ws.cell(row=row_num, column=9, value=d.total)
        cell_base.number_format = '#,##0.00'
        cell_ret = ws.cell(row=row_num, column=10, value=d.tax_amount_vat)
        cell_ret.number_format = '#,##0.00'
        ws.cell(row=row_num, column=11, value=d.status)
        ws.cell(row=row_num, column=12, value=d.declared_status)
        
        total_base += (d.total or 0)
        total_ret += (d.tax_amount_vat or 0)
        row_num += 1

    row_num += 1
    ws.cell(row=row_num, column=8, value="TOTALES:").font = bold_font
    ws.cell(row=row_num, column=8).alignment = Alignment(horizontal="right")
    
    cell_total_base = ws.cell(row=row_num, column=9, value=total_base)
    cell_total_base.number_format = '#,##0.00'
    cell_total_base.font = bold_font

    cell_total_ret = ws.cell(row=row_num, column=10, value=total_ret)
    cell_total_ret.number_format = '#,##0.00'
    cell_total_ret.font = bold_font

    for col_idx in range(1, 11):
        ws.column_dimensions[get_column_letter(col_idx)].width = 16

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    content = output.read()

    frappe.local.response.filename = f"Retenciones_IVA_{nowdate()}.xlsx"
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
    total_ret = sum(d.tax_amount_vat or 0 for d in data)

    for d in data:
        d["total_f"] = fmt_money(d.total, currency=currency)
        d["ret_f"] = fmt_money(d.tax_amount_vat, currency=currency)
        d["p_date"] = formatdate(d.posting_date)
        d["i_date"] = formatdate(d.issue_date)

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: sans-serif; font-size: 7pt; margin: 0; }
            .company-details { margin-bottom: 10px; line-height: 1.2; }
            .company-name { font-size: 9pt; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 1px solid #000; padding: 2px; word-wrap: break-word; }
            th { background-color: #D8E4BC; font-weight: bold; text-align: center; }
            .text-right { text-align: right; }
            .text-center { text-align: center; }
            .title-row { background-color: #D8E4BC; text-align: center; font-weight: bold; padding: 5px; border: 1px solid #000; margin-bottom: 5px; font-size: 10pt; }
        </style>
    </head>
    <body>
        <div class="company-details">
            <div class="company-name">{{ company_name }}</div>
            <div>R.I.F.: {{ company_rif }}</div>
            <div>Dirección: {{ company_address }}</div>
            <div>Fecha de Emisión: {{ print_date }}</div>
        </div>

        <div class="title-row">REPORTE DETALLADO DE RETENCIONES IVA</div>

        <table>
            <thead>
                <tr>
                    <th style="width: 8%;">RIF Proveedor</th>
                    <th style="width: 15%;">Nombre del Proveedor</th>
                    <th style="width: 8%;">Número de Factura</th>
                    <th style="width: 9%;">Número de Control</th>
                    <th style="width: 8%;">Fecha Factura</th>
                    <th style="width: 10%;">Impuesto</th>
                    <th style="width: 8%;">Fecha Emisión</th>
                    <th style="width: 12%;">Documento Retención</th>
                    <th style="width: 11%;">Base Imponible Bs</th>
                    <th style="width: 11%;">Monto Retención Bs</th>
                    <th style="width: 5%;">Estado del Documento</th>
                    <th style="width: 5%;">Estado del Comprobante</th>
                </tr>
            </thead>
            <tbody>
                {% for row in data %}
                <tr>
                    <td class="text-center">{{ row.tax_id }}</td>
                    <td>{{ row.supplier }}</td>
                    <td class="text-center">{{ row.bill_no }}</td>
                    <td class="text-center">{{ row.bill_control }}</td>
                    <td class="text-center">{{ row.p_date }}</td>
                    <td>{{ row.tax_withholding_category or '' }}</td>
                    <td class="text-center">{{ row.i_date }}</td>
                    <td class="text-center">{{ row.voucher_number }}</td>
                    <td class="text-right">{{ row.total_f }}</td>
                    <td class="text-right">{{ row.ret_f }}</td>
                    <td class="text-center">{{ row.status }}</td>
                    <td class="text-center">{{ row.declared_status }}</td>
                </tr>
                {% endfor %}
                <tr style="font-weight: bold; background-color: #f2f2f2;">
                    <td colspan="8" class="text-right">TOTALES</td>
                    <td class="text-right">{{ total_base_f }}</td>
                    <td class="text-right">{{ total_ret_f }}</td>
                    <td colspan="2"></td>
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
        "total_base_f": fmt_money(total_base, currency=currency),
        "total_ret_f": fmt_money(total_ret, currency=currency)
    }

    final_html = frappe.render_template(html_content, context)
    pdf_content = get_pdf(final_html, {"orientation": "Landscape"})

    frappe.local.response.filename = f"Retenciones_IVA_{nowdate()}.pdf"
    frappe.local.response.filecontent = pdf_content
    frappe.local.response.type = "pdf"