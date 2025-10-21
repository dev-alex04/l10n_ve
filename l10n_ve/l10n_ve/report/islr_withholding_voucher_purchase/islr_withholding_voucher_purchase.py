import frappe
from frappe import _
from frappe.utils import getdate, get_url as get_full_url, escape_html
from l10n_ve.utils.utils import format_amounts

@frappe.whitelist()
def generate_islr_report(voucher_name):
    try:
        doc = frappe.get_doc("ISLR Withholding Voucher", voucher_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Comprobante de Retención no encontrado."))

    footer_html = get_footer_html(doc)

    format_amounts(doc, [
		"totals_islr_base_amount",
		"totals_islr_amount",
		"totals_paid_amount",
		"totals_grand_total",
	], [
		"grand_total",
		"rate",
		"paid_amount",
		"islr_base_amount",
		"subtracting",
		"islr_amount",
	], "islr_withholding_voucher_item")

    items_per_page = 13
    total_items = len(doc.islr_withholding_voucher_item)
    total_pages = int(total_items / items_per_page) + (1 if total_items % items_per_page > 0 else 0)

    page_content_html = ""
    for i in range(total_pages):
        start_index = i * items_per_page
        end_index = start_index + items_per_page
        current_items = doc.islr_withholding_voucher_item[start_index:end_index]

        current_page_number = i + 1
        header_html = get_header_html(doc, current_page_number, total_pages)

        content_table_html = generate_content_table(current_items, doc, i, total_pages, start_index)

        page_html = f"""
        <div class="page-container">
            {header_html}
            {content_table_html}
            {footer_html}
        </div>
        """
        page_content_html += page_html

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Comprobante de Retención de ISLR</title>
        <style>
            @page {{
                size: A4 landscape;
                margin: 3mm;
            }}

            body {{
                font-size: 12px;
                margin: 0;
                padding: 0;
            }}

            .page-container {{
                width: 90%;
                margin: 0 auto;
                padding-bottom: 25mm;
            }}

            .table-full-width {{
                width: 100%;
                border-collapse: collapse;
            }}

            .table-no-border {{
                border: none;
            }}

            .text-center {{ text-align: center; }}
            .text-right {{ text-align: right; }}
            .text-left {{ text-align: left; }}

            .header-box {{
                border: 1px solid #000;
                padding: 5px;
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                margin-top: 1rem;
            }}

            .logo-section {{
                display: flex;
                align-items: center;
                width: 25%;
            }}

            .header-title-section {{
                width: 50%;
                text-align: center;
                padding-top: 5px;
                margin-top: auto;
            }}

            .header-user-info-section {{
                width: 25%;
                text-align: right;
            }}

            .main-header {{
                margin-bottom: 3px;
            }}

            .supplier-company-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 5px;
            }}

            .supplier-company-table th {{
                color: #000 !important;
                border: 1px solid #000;
                text-align: center;
            }}

            .supplier-company-table td {{
                border: 1px solid #000;
                vertical-align: top;
            }}

            .footer {{
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                height: 20mm;
                text-align: right;
                font-size: 10px;
            }}

            .withholding-voucher-details-table td, .withholding-voucher-details-table th {{
                border: 1px solid #000;
            }}

			.withholding-voucher-details-table {{
				border-collapse: collapse;
                width: 100%;
                margin: 0 auto;
			}}
        </style>
    </head>
    <body>
        {page_content_html}
    </body>
    </html>
    """

    return full_html

def get_company_logo_url(doc):
    company_name = doc.empresa
    
    logo_path = frappe.db.get_value("Company", company_name, "company_logo")
    
    company_logo_url = None

    if logo_path:
        company_logo_url = frappe.utils.get_url(logo_path)
        
    return company_logo_url

def get_header_html(doc, current_page, total_pages):
    company_tax_id = frappe.db.get_value("Company", doc.empresa, "tax_id")
    supplier_tax_id = frappe.db.get_value("Supplier", doc.supplier, "tax_id")

    company_logo_url = get_company_logo_url(doc)

    return f"""
        <div class="header-box">
            <div class="logo-section">
                <img src="{company_logo_url}" alt="Logo empresa" style="width:50px; height:50px; margin-right:5px;">
                <div style="line-height: 1.1;">
                    DOMINA ERP<br>
                    { escape_html(doc.empresa) }<br>
                    R.I.F.: { escape_html(company_tax_id) }
                </div>
            </div>
            <div class="header-title-section">
                <div style="font-size: 10px; margin-bottom: 2px;">
                    <span style="font-weight: bold;">{ escape_html(doc.voucher_number) }</span>
                </div>
                <div class="main-header">I.S.L.R. - COMPROBANTE DE RETENCIÓN DE I.S.L.R.</div>
                <div>Fecha:Desde { getdate(doc.start_date).strftime('%d/%m/%Y') } Hasta { getdate(doc.end_date).strftime('%d/%m/%Y') }</div>
            </div>
            <div class="header-user-info-section">
                <table class="table-full-width table-no-border info-text-normal">
                    <tr>
                        <td class="text-left" style="width: 40%;">Usuario:</td>
                        <td class="text-left">{ frappe.session.user }</td>
                    </tr>
                    <tr>
                        <td class="text-left" style="width: 40%;">Página:</td>
                        <td class="text-left">{ current_page } de { total_pages }</td>
                    </tr>
                    <tr>
                        <td class="text-left" style="width: 40%;">Fecha:</td>
                        <td class="text-left">{ frappe.utils.get_datetime(frappe.utils.now_datetime()).strftime('%d/%m/%Y %I:%M:%S %p') }</td>
                    </tr>
                </table>
            </div>
        </div>

        <table class="supplier-company-table">
            <thead>
                <tr>
                    <th style="width: 50%;">Proveedor / Beneficiario</th>
                    <th style="width: 50%;">Empresa</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>
                        Proveedor / Beneficiario: { doc.supplier }<br>
                        R.I.F.: { escape_html(supplier_tax_id) }<br>
                        Dirección: { escape_html(doc.supplier_address) }
                    </td>
                    <td>
                        Nombre / Razón Social: { escape_html(doc.empresa) }<br>
                        R.I.F.: { escape_html(company_tax_id) }<br>
                        Dirección: { escape_html(doc.company_address) }
                    </td>
                </tr>
            </tbody>
        </table>
    """

def get_footer_html(doc):
    return f"""
    <div class="footer">
        <table style="width: 100%; border-collapse: separate;">
            <tbody>
                <tr>
                    <td style="width: 50%; text-align: center; vertical-align: bottom; padding-right: 20px;">
                        <hr style="border-top: 1px solid #000; margin-bottom: 5px; width: 200px;">
                        <p style="margin: 0; font-size: 12px;">Agente de Retención <br> (Sello, Firma y Fecha)</p>
                    </td>
                    <td style="width: 50%; text-align: center; vertical-align: bottom; padding-left: 20px;">
                        <hr style="border-top: 1px solid #000; margin-bottom: 5px; width: 200px;">
                        <p style="margin: 0; font-size: 12px;">Sujeto Retenido <br> (Sello, Firma y Fecha)</p>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
    """

def generate_content_table(items, doc, current_page, total_pages, start_index):
    table_rows = ""

    for index, item in enumerate(items):
        display_index = start_index + index + 1
        table_rows += f"""
        <tr>
            <td class="text-center">{display_index:02d}</td>
            <td class="text-center">{getdate(item.posting_date).strftime('%d/%m/%Y')}</td>
            <td class="text-center">{item.payment_entry_name}</td>
            <td class="text-center">{item.doc_type or ''}</td>
            <td class="text-center">{item.doc_no or ''}</td>
            <td class="text-center">{item.bill_control or ''}</td>
            <td class="text-right">{item.grand_total}</td>
            <td class="text-right">{item.paid_amount}</td>
            <td class="text-right">{item.islr_base_amount}</td>
            <td class="text-right">{item.rate}</td>
            <td class="text-center">{item.code or ''}</td>
            <td class="text-right">{item.subtracting}</td>
            <td class="text-right">{item.islr_amount}</td>
        </tr>
        """

    if current_page == total_pages - 1:
        table_rows += f"""
        <tr>
            <td class="text-center">Totales</td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td class="text-right">{ doc.totals_grand_total }</td>
            <td class="text-right">{ doc.totals_paid_amount }</td>
            <td class="text-right">{ doc.totals_islr_base_amount }</td>
            <td></td>
            <td></td>
            <td class="text-right"></td>
            <td class="text-right">{ doc.totals_islr_amount }</td>
        </tr>
        """

    return f"""
    <div class="page-content">
        <div class="withholding-voucher-details" style="width: 100%;">
            <table class="withholding-voucher-details-table" style="margin-top: 5px; ">
                <thead>
                    <tr>
                        <th style="width: 6%;">Oper. N°</th>
                        <th style="width: 6%;">Fecha</th>
                        <th style="width: 9%;">Número Pago</th>
                        <th style="width: 5%;">Tipo</th>
                        <th style="width: 8%;">N° Doc.</th>
                        <th style="width: 8%;">N° Control</th>
                        <th style="width: 12%;">Monto de Documento</th>
                        <th style="width: 12%;">Monto Abonado</th>
                        <th style="width: 12%;">Monto Objeto a Retención</th>
                        <th style="width: 6%;">Tarifa %</th>
                        <th style="width: 8%;">Código Concepto</th>
                        <th style="width: 8%;">Sustraendo</th>
                        <th style="width: 8%;">Impuesto Retenido</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>
    """