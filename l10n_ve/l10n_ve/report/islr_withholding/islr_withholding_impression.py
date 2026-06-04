import json
import io
import frappe
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from frappe.utils import fmt_money, formatdate, nowdate
from frappe.utils.pdf import get_pdf
from l10n_ve.l10n_ve.report.islr_withholding.islr_withholding import get_data

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
            frappe.log_error(frappe.get_traceback(), "Error al obtener la dirección de la empresa para el reporte de ISLR")
            pass
    return {"name": company_name, "rif": company_rif, "address": company_address}

@frappe.whitelist()
def download_custom_excel(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)

    data = get_data(filters)
    group_by = filters.get("group_by") or "Detalle"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Retenciones ISLR"

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

    # Determine headers and colspan based on group_by
    if group_by == "Por Proveedor":
        headers = ["RIF Proveedor", "Nombre Proveedor", "Base Imponible Bs", "Monto Retenido Bs"]
        merge_range = "A5:D5"
        total_col_label = 2
        total_col_base = 3
        total_col_ret = 4
    elif group_by == "Por Concepto":
        headers = ["Código Concepto", "Concepto de Retención", "Base Imponible Bs", "Monto Retenido Bs"]
        merge_range = "A5:D5"
        total_col_label = 2
        total_col_base = 3
        total_col_ret = 4
    else:
        headers = [
            "RIF Proveedor", "Nombre Proveedor", "Nro. Factura", "Nro. Control", "Fecha Factura", 
            "Código Concepto", "Concepto de Retención", "Fecha Emisión", "Nro. Retención", "Factura Compra",
            "Base Imponible Bs", "Monto Retenido Bs", "Estado del Documento", "Estado del Comprobante"
        ]
        merge_range = "A5:N5"
        total_col_label = 10
        total_col_base = 11
        total_col_ret = 12

    ws.merge_cells(merge_range)
    ws["A5"] = f"REPORTE DE RETENCIONES ISLR - {group_by.upper()}"
    ws["A5"].font = bold_font
    ws["A5"].alignment = center_align
    ws["A5"].fill = green_fill

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_num, value=header)
        cell.font = bold_font
        cell.border = thin_border
        cell.fill = green_fill

    row_num = 7
    total_base = 0
    total_ret = 0

    for d in data:
        if group_by == "Por Proveedor":
            ws.cell(row=row_num, column=1, value=d.tax_id)
            ws.cell(row=row_num, column=2, value=d.supplier)
            cell_base = ws.cell(row=row_num, column=3, value=d.islr_base_amount)
            cell_ret = ws.cell(row=row_num, column=4, value=d.islr_amount)
        elif group_by == "Por Concepto":
            ws.cell(row=row_num, column=1, value=d.concept_code)
            ws.cell(row=row_num, column=2, value=d.concept_description)
            cell_base = ws.cell(row=row_num, column=3, value=d.islr_base_amount)
            cell_ret = ws.cell(row=row_num, column=4, value=d.islr_amount)
        else:
            ws.cell(row=row_num, column=1, value=d.tax_id)
            ws.cell(row=row_num, column=2, value=d.supplier)
            ws.cell(row=row_num, column=3, value=d.doc_no)
            ws.cell(row=row_num, column=4, value=d.bill_control)
            
            cell_f_date = ws.cell(row=row_num, column=5, value=d.bill_date)
            cell_f_date.number_format = 'DD-MM-YYYY'
            
            ws.cell(row=row_num, column=6, value=d.concept_code)
            ws.cell(row=row_num, column=7, value=d.concept_description)
            
            cell_p_date = ws.cell(row=row_num, column=8, value=d.posting_date)
            cell_p_date.number_format = 'DD-MM-YYYY'
            
            ws.cell(row=row_num, column=9, value=d.voucher_no)
            ws.cell(row=row_num, column=10, value=d.purchase_invoice)
            
            cell_base = ws.cell(row=row_num, column=11, value=d.islr_base_amount)
            cell_ret = ws.cell(row=row_num, column=12, value=d.islr_amount)
            
            ws.cell(row=row_num, column=13, value=d.status)
            ws.cell(row=row_num, column=14, value=d.declared_status)

        cell_base.number_format = '#,##0.00'
        cell_ret.number_format = '#,##0.00'
        
        total_base += (d.islr_base_amount or 0)
        total_ret += (d.islr_amount or 0)
        row_num += 1

    # Fila de Totales
    row_num += 1
    ws.cell(row=row_num, column=total_col_label, value="TOTALES:").font = bold_font
    
    cell_total_base = ws.cell(row=row_num, column=total_col_base, value=total_base)
    cell_total_base.number_format = '#,##0.00'
    cell_total_base.font = bold_font

    cell_total_ret = ws.cell(row=row_num, column=total_col_ret, value=total_ret)
    cell_total_ret.number_format = '#,##0.00'
    cell_total_ret.font = bold_font

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    frappe.local.response.filename = f"Retenciones_ISLR_{nowdate()}.xlsx"
    frappe.local.response.filecontent = output.read()
    frappe.local.response.type = "binary"

@frappe.whitelist()
def download_custom_pdf(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)

    data = get_data(filters)
    group_by = filters.get("group_by") or "Detalle"
    company_name = filters.get("company")
    company_details = _get_company_details(company_name)
    currency = frappe.get_cached_value('Company', company_name, 'default_currency')

    total_base = sum(d.islr_base_amount or 0 for d in data)
    total_ret = sum(d.islr_amount or 0 for d in data)

    # Formatear datos para el HTML
    for d in data:
        d["base_f"] = fmt_money(d.islr_base_amount, currency=currency)
        d["ret_f"] = fmt_money(d.islr_amount, currency=currency)
        d["f_date"] = formatdate(d.bill_date) if d.get("bill_date") else ""
        d["p_date"] = formatdate(d.posting_date) if d.get("posting_date") else ""

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: sans-serif; font-size: 7pt; margin: 0; }
            .company-details { margin-bottom: 8px; line-height: 1.2; }
            .company-name { font-size: 9pt; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 0.5pt solid #000; padding: 3px; word-wrap: break-word; }
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

        <div class="title-row">REPORTE DE RETENCIONES ISLR - {{ group_by.upper() }}</div>

        <table>
            <thead>
                <tr>
                    {% if group_by == 'Por Proveedor' %}
                        <th style="width: 25%;">RIF Proveedor</th>
                        <th style="width: 35%;">Nombre Proveedor</th>
                        <th style="width: 20%;">Base Imp. Bs</th>
                        <th style="width: 20%;">Monto Ret. Bs</th>
                    {% elif group_by == 'Por Concepto' %}
                        <th style="width: 25%;">Código Concepto</th>
                        <th style="width: 35%;">Concepto de Retención</th>
                        <th style="width: 20%;">Base Imp. Bs</th>
                        <th style="width: 20%;">Monto Ret. Bs</th>
                    {% else %}
                        <th style="width: 8%;">RIF</th>
                        <th style="width: 12%;">Proveedor</th>
                        <th style="width: 7%;">Factura</th>
                        <th style="width: 7%;">Control</th>
                        <th style="width: 7%;">Fecha Fact.</th>
                        <th style="width: 6%;">Código</th>
                        <th style="width: 12%;">Concepto</th>
                        <th style="width: 7%;">Fecha Emis.</th>
                        <th style="width: 8%;">Nro. Ret.</th>
                        <th style="width: 8%;">Factura Compra</th>
                        <th style="width: 9%;">Base Imp. Bs</th>
                        <th style="width: 9%;">Monto Ret. Bs</th>
                        <th style="width: 6%;">Doc. Estado</th>
                        <th style="width: 6%;">Comp. Estado</th>
                    {% endif %}
                </tr>
            </thead>
            <tbody>
                {% for row in data %}
                <tr>
                    {% if group_by == 'Por Proveedor' %}
                        <td class="text-center">{{ row.tax_id }}</td>
                        <td>{{ row.supplier }}</td>
                        <td class="text-right">{{ row.base_f }}</td>
                        <td class="text-right">{{ row.ret_f }}</td>
                    {% elif group_by == 'Por Concepto' %}
                        <td class="text-center">{{ row.concept_code }}</td>
                        <td>{{ row.concept_description }}</td>
                        <td class="text-right">{{ row.base_f }}</td>
                        <td class="text-right">{{ row.ret_f }}</td>
                    {% else %}
                        <td class="text-center">{{ row.tax_id }}</td>
                        <td>{{ row.supplier }}</td>
                        <td class="text-center">{{ row.doc_no }}</td>
                        <td class="text-center">{{ row.bill_control }}</td>
                        <td class="text-center">{{ row.f_date }}</td>
                        <td class="text-center">{{ row.concept_code }}</td>
                        <td>{{ row.concept_description or '' }}</td>
                        <td class="text-center">{{ row.p_date }}</td>
                        <td class="text-center">{{ row.voucher_no }}</td>
                        <td class="text-center">{{ row.purchase_invoice }}</td>
                        <td class="text-right">{{ row.base_f }}</td>
                        <td class="text-right">{{ row.ret_f }}</td>
                        <td class="text-center">{{ row.status }}</td>
                        <td class="text-center">{{ row.declared_status }}</td>
                    {% endif %}
                </tr>
                {% endfor %}
                <tr style="font-weight: bold; background-color: #f2f2f2;">
                    {% if group_by == 'Por Proveedor' or group_by == 'Por Concepto' %}
                        <td colspan="2" class="text-right">TOTALES</td>
                        <td class="text-right">{{ total_base_f }}</td>
                        <td class="text-right">{{ total_ret_f }}</td>
                    {% else %}
                        <td colspan="10" class="text-right">TOTALES</td>
                        <td class="text-right">{{ total_base_f }}</td>
                        <td class="text-right">{{ total_ret_f }}</td>
                        <td colspan="2"></td>
                    {% endif %}
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
        "group_by": group_by,
        "total_base_f": fmt_money(total_base, currency=currency),
        "total_ret_f": fmt_money(total_ret, currency=currency)
    }

    final_html = frappe.render_template(html_content, context)
    pdf_content = get_pdf(final_html, {"orientation": "Landscape"})

    frappe.local.response.filename = f"Retenciones_ISLR_{nowdate()}.pdf"
    frappe.local.response.filecontent = pdf_content
    frappe.local.response.type = "download"