import frappe
from frappe import _
import json
from frappe.utils import getdate
from l10n_ve.utils.utils import format_amounts

@frappe.whitelist()
def generate_islr_report(voucher_name):
    try:
        doc = frappe.get_doc("ISLR Withholding Voucher", voucher_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Comprobante de Retención no encontrado."))

    header_html = get_header_html(doc)
    footer_html = get_footer_html(doc)

    format_amounts(doc, [
		"totals_grand_total",
		"totals_total_exempt",
		"totals_total",
		"totals_taxes_and_charges_added",
		"totals_taxes_and_charges_deducted",
	], [
		"grand_total",
		"rate",
		"total_exempt",
		"total",
		"taxes_and_charges_added",
		"taxes_and_charges_deducted",
	], "vat_withholding_voucher_item")

    items_per_page = 10
    total_items = len(doc.islr_withholding_voucher_item)
    total_pages = int(total_items / items_per_page) + (1 if total_items % items_per_page > 0 else 0)

    page_content_html = ""
    for i in range(total_pages):
        start_index = i * items_per_page
        end_index = start_index + items_per_page
        current_items = doc.islr_withholding_voucher_item[start_index:end_index]

        content_table_html = generate_content_table(current_items, doc, i, total_pages)

        page_html = f"""
        <div class="page-container">
            {header_html}
            {content_table_html}
            {footer_html}
        </div>
        """
        page_content_html += page_html

        # if i < total_pages - 1:
        #     page_content_html += page_html

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
                font-size: 9px !important;
                margin: 0;
                padding: 0;
            }}

            .container {{
                font-size: 11px !important;
                width: 100%;
                margin: auto;
            }}

            .table-full-width {{
                width: 100%;
                border-collapse: collapse;
            }}

            .table-no-border {{
                border: none;
            }}

            .table-border-all td, .table-border-all th {{
                border: 1px solid #000;
            }}

            .text-center {{ text-align: center; }}
            .text-right {{ text-align: right; }}
            .text-left {{ text-align: left; }}

            .align-bottom {{ vertical-align: bottom; }}
            .align-top {{ vertical-align: top; }}

            .header-box {{
                border: 1px solid #000;
                padding: 5px;
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
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
                font-size: 12px;
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

            .detail-table th, .detail-table td {{
                color: #000 !important;
                border: 1px solid #000;
                /*padding: 5px 2px;*/
                text-align: center;
            }}

            .info-text-small {{ font-size: 8px; }}
            .info-text-normal {{ font-size: 9px; }}

            .footer {{
                position: fixed;
                bottom: 50px;
                left: 0;
                right: 0;
                height: 20mm;
                text-align: right;
                font-size: 10px;
            }}
        </style>
    </head>
    <body>
        {page_content_html}
    </body>
    </html>
    """

    return full_html

def get_header_html(doc):
    company_tax_id = frappe.db.get_value("Company", doc.empresa, "tax_id")
    supplier_tax_id = frappe.db.get_value("Supplier", doc.supplier, "tax_id")

    return f"""
        <div class="header-box">
            <div class="logo-section">
                <img src="https://via.placeholder.com/60x60.png?text=LOGO" alt="Logo" style="width:50px; height:50px; margin-right:5px;">
                <div style="line-height: 1.1;">
                    DOMINA ERP<br>
                    {{ doc.empresa }}<br>
                    R.I.F.: {{ doc.company_tax_id }}
                </div>
            </div>
            <div class="header-title-section">
                <div style="font-size: 10px; margin-bottom: 2px;">
                    <span style="font-weight: bold;">{{ doc.voucher_number }}</span>
                </div>
                <div class="main-header">I.S.L.R. - COMPROBANTE DE RETENCIÓN DE I.S.L.R.</div>
                <div>Fecha:Desde {{ frappe.utils.getdate(doc.start_date).strftime('%d/%m/%Y') }} Hasta {{ frappe.utils.getdate(doc.end_date).strftime('%d/%m/%Y') }}:</div>
            </div>
            <div class="header-user-info-section">
                <table class="table-full-width table-no-border info-text-normal">
                    <tr>
                        <td class="text-left" style="width: 40%;">Usuario:</td>
                        <td class="text-left">{{ frappe.session.user }}</td>
                    </tr>
                    <tr>
                        <td class="text-left" style="width: 40%;">Página:</td>
                        <td class="text-left">1 de 1</td>
                    </tr>
                    <tr>
                        <td class="text-left" style="width: 40%;">Fecha:</td>
                        <td class="text-left">{{ frappe.utils.get_datetime(frappe.utils.now_datetime()).strftime('%d/%m/%Y %I:%M:%S %p') }}</td>
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
                    <td class="text-left align-top">
                        Proveedor / Beneficiario: {{ doc.supplier }}<br>
                        R.I.F.: {{ doc.supplier_tax_id }}<br>
                        Dirección: {{ doc.supplier_address }}
                    </td>
                    <td class="text-left align-top">
                        Nombre / Razón Social: {{ doc.empresa }}<br>
                        R.I.F.: {{ doc.company_tax_id }}<br>
                        Dirección: {{ doc.company_address }}
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
        <div style="text-align: center; margin-top: 10px;">
            <small>Éste comprobante se emite en función a lo establecido en el artículo 16 de la Providencia Administrativa N° SNAT/2025/000054 de fecha 02/07/2025 </small>
        </div>
    </div>
    """

def generate_content_table(items, doc, current_page, total_pages):
    table_rows = ""

    for index, item in enumerate(items):
        transaction_type = ('02-Comp'
            if item.debit_note_no or item.credit_note_no
            else '01-Reg')

        display_index = index + 1
        table_rows += f"""
        <tr>
            <td class="text-center">{display_index:02d}</td>
            <td class="text-center">{getdate(item.posting_date).strftime('%d/%m/%Y')}</td>
            <td class="text-center">{item.bill_no or ''}</td>
            <td class="text-center">{item.bill_control or ''}</td>
            <td class="text-center">{item.debit_note_no or ''}</td>
            <td class="text-center">{item.credit_note_no or ''}</td>
            <td class="text-center">{transaction_type}</td>
            <td class="text-center">{item.affected_invoice_number or ''}</td>
            <td class="text-right">{item.grand_total}</td>
            <td class="text-right">{item.total_exempt}</td>
            <td class="text-right">{item.total}</td>
            <td class="text-right">{item.rate or ''}</td>
            <td class="text-right">{item.taxes_and_charges_added}</td>
            <td class="text-right">{item.taxes_and_charges_deducted}</td>
        </tr>
        """

    if current_page == total_pages - 1:
        table_rows += f"""
        <tr>
            <td class="text-left">Totales</td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td class="text-right">{ doc.totals_total_exempt }</td>
            <td></td>
            <td></td>
            <td class="text-right"></td>
            <td class="text-right">{ doc.totals_tax_amount }</td>
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