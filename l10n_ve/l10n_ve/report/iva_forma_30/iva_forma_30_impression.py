import json
import io
import frappe
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from frappe.utils import fmt_money, formatdate, nowdate
from frappe.utils.pdf import get_pdf
from l10n_ve.l10n_ve.report.iva_forma_30.iva_forma_30 import get_data

def format_val(val, company_currency):
    if val is None or val == "":
        return ""
    if val == 0 or val == 0.0:
        return "-"
    symbol = frappe.db.get_value("Currency", company_currency, "symbol") or ""
    formatted = fmt_money(val, currency=company_currency).replace(symbol, "").strip()
    return formatted

def get_row_boxes(row):
    box1 = row.get("box_base") or ""
    val1 = row.get("base_amount") if box1 else None
    
    box2 = ""
    box3 = ""
    val2 = None
    
    r_no = 0
    try:
        r_no = int(row.get("row_no") or 0)
    except ValueError:
        pass
        
    if 1 <= r_no <= 6:
        box2 = row.get("box_rate") or ""
        box3 = row.get("box_tax") or ""
        if r_no == 1:
            box2 = row.get("box_tax") or "0"
            box3 = ""
        elif r_no == 2:
            box2 = row.get("box_rate") or "9"
            box3 = ""
        val2 = row.get("tax_amount") if box3 else None
    elif 7 <= r_no <= 9:
        box3 = row.get("box_tax") or ""
        val2 = row.get("tax_amount")
    elif r_no == 10:
        box2 = row.get("box_tax") or "0"
    elif 11 <= r_no <= 17:
        box2 = row.get("box_rate") or ""
        box3 = row.get("box_tax") or ""
        val2 = row.get("tax_amount") if box3 else None
    elif 18 <= r_no <= 28:
        box3 = row.get("box_tax") or ""
        val2 = row.get("tax_amount")
    elif 29 <= r_no <= 31:
        box2 = row.get("box_tax") or ""
    elif r_no == 32:
        box3 = row.get("box_tax") or "78"
        val2 = row.get("tax_amount")
    elif 33 <= r_no <= 37:
        box2 = row.get("box_tax") or ""
    elif r_no == 38:
        box3 = row.get("box_tax") or "55"
        val2 = row.get("tax_amount")
    elif r_no == 39:
        box2 = row.get("box_tax") or ""
    elif r_no == 40:
        box3 = row.get("box_tax") or "56"
        val2 = row.get("tax_amount")
    elif 41 <= r_no <= 45:
        box2 = row.get("box_tax") or ""
    elif r_no == 46:
        box3 = row.get("box_tax") or "58"
        val2 = row.get("tax_amount")
    elif r_no == 47:
        box3 = row.get("box_tax") or "1"
        val2 = row.get("tax_amount")
    elif r_no == 48:
        box3 = row.get("box_tax") or "90"
        val2 = row.get("tax_amount")
        
    return {
        "box1": box1,
        "val1": val1,
        "box2": box2,
        "box3": box3,
        "val2": val2
    }

@frappe.whitelist()
def get_iva_forma_30_pdf(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)
        
    data = get_data(filters)
    company_name = filters.get("company")
    company_currency = frappe.get_cached_value("Company", company_name, "default_currency")
    
    company_doc = frappe.get_cached_doc("Company", company_name)
    company_rif = company_doc.get("tax_id") or "J-00000000-0"
    
    rif_letter = "J"
    rif_number = company_rif
    if company_rif and "-" in company_rif:
        parts = company_rif.split("-")
        rif_letter = parts[0]
        rif_number = "-".join(parts[1:])
    elif company_rif and len(company_rif) > 1:
        rif_letter = company_rif[0]
        rif_number = company_rif[1:]
        
    processed_rows = []
    for d in data:
        if d.get("is_header"):
            is_autoliquidacion = "AUTOLIQUIDACION" in (d.get("concept") or "")
            processed_rows.append({
                "is_header": True,
                "is_autoliquidacion": is_autoliquidacion,
                "concept": d.get("concept"),
                "box_base": d.get("box_base") or "Base Imponible",
                "box_tax": d.get("box_tax") or "Impuesto"
            })
        else:
            boxes = get_row_boxes(d)
            processed_rows.append({
                "is_header": False,
                "is_total": d.get("is_total", False),
                "row_no": d.get("row_no"),
                "concept": d.get("concept"),
                "box1": boxes["box1"],
                "val1": format_val(boxes["val1"], company_currency) if boxes["box1"] else "",
                "box2": boxes["box2"],
                "box3": boxes["box3"],
                "val2": format_val(boxes["val2"], company_currency) if boxes["box3"] else ""
            })
            
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
                font-size: 7.5pt;
                color: #000;
                margin: 0;
                padding: 10px;
                background-color: #fff;
            }
            
            /* Seniat Form Style Header */
            .seniat-header {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 12px;
            }
            
            .seniat-header td {
                border: 2px solid #000 !important;
                padding: 8px !important;
                font-weight: 700;
                color: #000;
                vertical-align: middle;
            }
            
            .company-title {
                font-size: 11pt;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .rif-label {
                width: 100px;
                text-align: center;
                background-color: #f1f5f9 !important;
                font-size: 8pt;
            }
            
            .rif-value {
                width: 100px;
                text-align: center;
                font-size: 9.5pt;
            }
            
            /* Main Form Table */
            table.seniat-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 5px;
                margin-bottom: 15px;
                border: 2px solid #000 !important;
            }
            
            table.seniat-table tr {
                border-bottom: 1px solid #000 !important;
            }
            
            table.seniat-table td {
                padding: 4px 5px;
                vertical-align: middle;
                font-size: 7.5pt;
                border-top: 1px solid #000 !important;
                border-bottom: 1px solid #000 !important;
                border-left: none !important;
                border-right: none !important;
            }
            
            /* Header Row */
            .header-row {
                background-color: #e2e8f0 !important;
                font-weight: 700;
                text-align: center;
                font-size: 8pt;
                text-transform: uppercase;
                color: #000;
            }
            
            .header-row td {
                border-top: 2px solid #000 !important;
                border-bottom: 2px solid #000 !important;
                padding: 6px 5px !important;
            }
            
            /* Text Styles */
            .total-row {
                font-weight: 700 !important;
            }
            
            /* Column alignments & widths */
            .row-no-cell {
                width: 25px;
                text-align: center;
                font-weight: 700;
                font-size: 7.5pt;
                border-left: 2px solid #000 !important;
                border-right: 1.5px solid #000 !important;
            }
            
            .concept-cell {
                text-align: left;
                font-size: 7.5pt;
                border-right: 1.5px solid #000 !important;
            }
            
            /* Active Box & Value styling */
            .active-box {
                width: 35px;
                text-align: center;
                font-size: 7.5pt;
                font-weight: 700;
                background-color: #e2e8f0 !important;
                border: 1.5px solid #000 !important;
            }
            
            .active-value {
                width: 125px;
                text-align: right;
                font-size: 7.5pt;
                background-color: #fff !important;
                border: 1.5px solid #000 !important;
                white-space: nowrap;
                padding-right: 6px !important;
            }
            
            /* Empty placeholders */
            .empty-cell {
                border-left: none !important;
                border-right: none !important;
            }
            
            /* Outer right border */
            .border-right-outer {
                border-right: 2px solid #000 !important;
            }
        </style>
    </head>
    <body>
        <!-- Seniat style header -->
        <table class="seniat-header">
            <tr>
                <td class="company-title" colspan="4">
                    {{ company_name }}
                </td>
                <td class="rif-label">RIF</td>
                <td class="rif-value">{{ rif_letter }}</td>
            </tr>
            <tr>
                <td colspan="4" style="text-align: center; font-size: 8.5pt; font-weight: 600; color: #000;">
                    DECLARACIÓN DEL IMPUESTO AL VALOR AGREGADO (FORMA 30)
                </td>
                <td class="rif-label">RIF NRO.</td>
                <td class="rif-value">{{ rif_number }}</td>
            </tr>
        </table>

        <table class="seniat-table">
            <tbody>
                {% for row in processed_rows %}
                    {% if row.is_header %}
                        <tr class="header-row">
                            {% if row.is_autoliquidacion %}
                                <td colspan="7" class="border-right-outer" style="text-align: center; font-weight: bold; border-left: 2px solid #000 !important;">
                                    AUTOLIQUIDACION
                                </td>
                            {% else %}
                                <td class="row-no-cell" style="border-right: none !important;"></td>
                                <td class="concept-cell" style="text-align: center; border-right: 1.5px solid #000 !important; font-weight: bold;">{{ row.concept }}</td>
                                <td colspan="2" style="text-align: center; border-right: 1.5px solid #000 !important; font-weight: bold;">{{ row.box_base }}</td>
                                <td style="text-align: center; border-right: 1.5px solid #000 !important;"></td>
                                <td colspan="2" class="border-right-outer" style="text-align: center; font-weight: bold;">{{ row.box_tax }}</td>
                            {% endif %}
                        </tr>
                    {% else %}
                        <tr class="{{ 'total-row' if row.is_total else '' }}">
                            <td class="row-no-cell">{{ row.row_no }}</td>
                            <td class="concept-cell {{ 'total-row' if row.is_total else '' }}">
                                {% if row.is_total %}
                                    <b>{{ row.concept }}</b>
                                {% else %}
                                    {{ row.concept }}
                                {% endif %}
                            </td>
                            
                            {% if row.box1 %}
                                <td class="active-box">{{ row.box1 }}</td>
                            {% else %}
                                <td class="empty-cell" style="width: 35px;"></td>
                            {% endif %}

                            {% if row.box1 %}
                                <td class="active-value">
                                    {% if row.is_total %}
                                        <b>{{ row.val1 }}</b>
                                    {% else %}
                                        {{ row.val1 }}
                                    {% endif %}
                                </td>
                            {% else %}
                                <td class="empty-cell" style="width: 125px;"></td>
                            {% endif %}

                            {% if row.box2 %}
                                <td class="active-box">{{ row.box2 }}</td>
                            {% else %}
                                <td class="empty-cell" style="width: 35px;"></td>
                            {% endif %}

                            {% if row.box3 %}
                                <td class="active-box">{{ row.box3 }}</td>
                            {% else %}
                                <td class="empty-cell" style="width: 35px;"></td>
                            {% endif %}

                            {% if row.box3 %}
                                <td class="active-value border-right-outer">
                                    {% if row.is_total %}
                                        <b>{{ row.val2 }}</b>
                                    {% else %}
                                        {{ row.val2 }}
                                    {% endif %}
                                </td>
                            {% else %}
                                <td class="empty-cell border-right-outer" style="width: 125px;"></td>
                            {% endif %}
                        </tr>
                    {% endif %}
                {% endfor %}
            </tbody>
        </table>
        
        <div style="font-size: 7pt; text-align: right; color: #000; font-style: italic; margin-top: 10px;">
            Expresado en Bolívares (VES) &nbsp;|&nbsp; Generado en base a Libros de Compras y Ventas de {{ from_date_f }} al {{ to_date_f }}
        </div>
    </body>
    </html>
    """
    
    from_date_f = formatdate(filters.get("from_date"))
    to_date_f = formatdate(filters.get("to_date"))
    
    context = {
        "company_name": company_name,
        "rif_letter": rif_letter,
        "rif_number": rif_number,
        "from_date_f": from_date_f,
        "to_date_f": to_date_f,
        "processed_rows": processed_rows
    }
    
    final_html = frappe.render_template(html_content, context)
    pdf_content = get_pdf(final_html, {
        "orientation": "Portrait",
        "margin-top": "10mm",
        "margin-bottom": "10mm",
        "margin-left": "10mm",
        "margin-right": "10mm"
    })
    
    frappe.response["filename"] = f"Declaracion_IVA_Forma_30_{nowdate()}.pdf"
    frappe.response["filecontent"] = pdf_content
    frappe.response["type"] = "download"

@frappe.whitelist()
def get_iva_forma_30_excel(filters=None):
    if isinstance(filters, str):
        filters = json.loads(filters)
        
    data = get_data(filters)
    company_name = filters.get("company")
    company_doc = frappe.get_cached_doc("Company", company_name)
    company_rif = company_doc.get("tax_id") or "J-00000000-0"
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Forma 30 IVA"
    
    bold_font = Font(bold=True)
    center_align = Alignment(horizontal="center")
    right_align = Alignment(horizontal="right")
    gray_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    
    ws["A1"] = company_name
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = f"R.I.F.: {company_rif}"
    ws["A3"] = "DECLARACIÓN DEL IMPUESTO AL VALOR AGREGADO (FORMA 30)"
    ws["A3"].font = bold_font
    ws["A4"] = f"Periodo: {formatdate(filters.get('from_date'))} al {formatdate(filters.get('to_date'))}"
    
    headers = ["Nro", "Concepto", "Casilla Base", "Monto Base Bs", "Casilla Alícuota", "Casilla Impuesto", "Monto Impuesto Bs"]
    
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_num, value=header)
        cell.font = bold_font
        cell.border = thin_border
        cell.fill = gray_fill
        cell.alignment = center_align
        
    row_num = 7
    for d in data:
        if d.get("is_header"):
            concept = d.get("concept").replace("<b>", "").replace("</b>", "")
            ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=7)
            cell = ws.cell(row=row_num, column=1, value=concept)
            cell.font = bold_font
            cell.alignment = center_align
            cell.fill = gray_fill
            row_num += 1
            continue
            
        boxes = get_row_boxes(d)
        
        ws.cell(row=row_num, column=1, value=d.get("row_no")).alignment = center_align
        concept_clean = d.get("concept").replace("<b>", "").replace("</b>", "")
        ws.cell(row=row_num, column=2, value=concept_clean)
        
        if boxes["box1"]:
            cell_box1 = ws.cell(row=row_num, column=3, value=int(boxes["box1"]))
            cell_box1.alignment = center_align
            cell_box1.fill = gray_fill
            
            cell_val1 = ws.cell(row=row_num, column=4, value=boxes["val1"])
            cell_val1.number_format = '#,##0.00'
            cell_val1.alignment = right_align
            
        if boxes["box2"]:
            cell_box2 = ws.cell(row=row_num, column=5, value=int(boxes["box2"]))
            cell_box2.alignment = center_align
            cell_box2.fill = gray_fill
            
        if boxes["box3"]:
            cell_box3 = ws.cell(row=row_num, column=6, value=int(boxes["box3"]))
            cell_box3.alignment = center_align
            cell_box3.fill = gray_fill
            
            cell_val2 = ws.cell(row=row_num, column=7, value=boxes["val2"])
            cell_val2.number_format = '#,##0.00'
            cell_val2.alignment = right_align
            
        if d.get("is_total"):
            for c in range(1, 8):
                ws.cell(row=row_num, column=c).font = bold_font
                
        row_num += 1
        
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = str(cell.value or '')
            if cell.coordinate in ws.merged_cells:
                continue
            max_len = max(max_len, len(val))
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
        
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    frappe.response["filename"] = f"Declaracion_IVA_Forma_30_{nowdate()}.xlsx"
    frappe.response["filecontent"] = output.read()
    frappe.response["type"] = "binary"
