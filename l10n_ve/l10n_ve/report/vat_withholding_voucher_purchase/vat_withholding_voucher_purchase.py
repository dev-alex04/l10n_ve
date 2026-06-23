import frappe
from frappe import _
from frappe.utils import getdate

from l10n_ve.utils.utils import format_amounts

@frappe.whitelist()
def generate_vat_report(voucher_name):
    try:
        doc = frappe.get_doc("VAT Withholding Voucher", voucher_name)
    except frappe.DoesNotExistError:
        frappe.throw(_("Comprobante de Retención no encontrado."))

    header_html = get_header_html(doc)
    footer_html = get_footer_html(doc)
    special_formats = {'rate': '{:.2f}'}

    format_amounts(doc, [
        "totals_grand_total",
        "totals_total_exempt",
        "totals_total",
        "totals_taxes_and_charges_added",
        "totals_tax_amount_vat",
    ], [
        "grand_total",
        "rate",
        "total_exempt",
        "total",
        "taxes_and_charges_added",
        "tax_amount_vat",
        ''
    ], "vat_withholding_voucher_item", special_formats)

    items_per_page = 10
    total_items = len(doc.vat_withholding_voucher_item)
    total_pages = int(total_items / items_per_page) + (1 if total_items % items_per_page > 0 else 0)

    page_content_html = ""
    for i in range(total_pages):
        start_index = i * items_per_page
        end_index = start_index + items_per_page
        current_items = doc.vat_withholding_voucher_item[start_index:end_index]

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
        <title>Reporte de Comprobante de Retención</title>
        <style>
            /* Estilos para el formato de impresión */
            @page {{
                size: A4 landscape;
                margin: 5mm;
            }}

            .page-container {{
                width: 90%;
                margin: 0 auto;
                page-break-after: always;
            }}

            .page-container:last-child {{
                page-break-after: avoid;
            }}

            .page-header {{
                width: 90%;
                margin: 0 auto 5mm auto;
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

            .mb-7 {{
                margin-bottom: 0px !important;
            }}

            .mt-7 {{
                margin-top: 0px !important;
            }}

            .text-right {{
                text-align: right;
            }}

            .text-center {{
                text-align: center;
            }}

            tr > th {{
                text-align: center;
                font-size: 12px;
            }}

            .withholding-voucher-info {{
                width: 100%;
                border-collapse: separate;
                border-spacing: 0;
            }}

            .withholding-voucher-table h6, .withholding-voucher-table p {{
                margin: 2px 0;
            }}

            .withholding-voucher-table {{
                width: 100%;
                margin: 0 auto;
                border-collapse: separate;
                border-spacing: 5px;
            }}

            .withholding-voucher-table td {{
                padding: 5px;
                vertical-align: top;
                border: 1px solid #000;
            }}

            b, strong, h6 {{
                font-weight: bold !important;
            }}

            .withholding-voucher-details-table td, .withholding-voucher-details-table th {{
                border-bottom: 1px solid #000;
            }}

            .withholding-voucher-details-table {{
                border-collapse: collapse;
                font-size: 12px;
                width: 100%;
                margin: 0 auto;
            }}

            .withholding-voucher-details-table th {{
                border-top: 1px solid #000;
            }}

            .withholding-voucher-details-table tr.totales td {{
                border-bottom: none !important;
            }}

            .withholding-voucher-details {{
                padding-bottom: 40mm;
            }}

            .page-container {{
                page-break-after: always;
            }}

            .page-container:last-child {{
                page-break-after: avoid;
            }}

            .withholding-voucher-table p {{
                font-size: 12px;
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
    company_tax_id = frappe.db.get_value("Company", doc.empresa, "tax_id", cache=True)
    supplier_tax_id = frappe.db.get_value("Supplier", doc.supplier, "tax_id", cache=True)

    return f"""
    <div class="page-header">
        <div style="text-align: center;">
            <h3> COMPROBANTE DE RETENCIÓN DEL IMPUESTO AL VALOR AGREGADO </h3>
        </div>
        <table class="withholding-voucher-table" >
            <tbody>
                <tr>
                    <td>
                        <p class="mt-7">
                            (Ley IVA - Art. 11. Gaceta Oficial 6.152 Extraordinario: "La Administración Tributaria podrá designar como
                            responsables del pago del impuesto, en calidad de agentes de retención, a quienes por sus funciones públicas
                            o por razón de sus actividades privadas intervengan en operaciones gravadas como el impuesto establecido en
                            este Documento con Rango, Valor y Fuerza de Ley")
                        </p>
                    </td>
                </tr>
            </tbody>
        </table>
        <table class="withholding-voucher-table">
            <tbody>
                <tr>
                    <td style="width: 40%;">
                        <h6 class="mt-7" style="font-weight: bold;">NOMBRE O RAZÓN SOCIAL DEL AGENTE DE RETENCIÓN </h6>
                        <p class="mb-7">{doc.empresa}</p>
                    </td>
                    <td style="width: 30%;">
                        <h6 class="mt-7" style="font-weight: bold; margin-bottom: 0px !important;">REGISTRO DE INFORMACIÓN FISCAL </br> DEL AGENTE DE RETENCIÓN (R.I.F) </h6>
                        <p class="mb-7"> {company_tax_id} </p>
                    </td>
                    <td style="width: 30%;">
                        <h6 class="mt-7" style="font-weight: bold;">Nº COMPROBANTE:</h6>
                        <p class="mb-7">{doc.voucher_number}</p>
                    </td>
                </tr>
            </tbody>
        </table>
        <table class="withholding-voucher-table">
            <tbody>
                <tr>
                    <td style="width: 70%;">
                        <h6 class="mt-7" style="font-weight: bold;">DIRECCIÓN FISCAL DEL AGENTE DE RETENCIÓN </h6>
                        <p class="mb-7">{doc.company_address}</p>
                    </td>
                    <td style="width: 15%;">
                        <h6 class="mt-7" style="font-weight: bold;">FECHA DE EMISIÓN</h6>
                        <p class="mb-7">{getdate(doc.issue_date).strftime('%d/%m/%Y')}</p>
                    </td>
                    <td style="width: 15%;">
                        <h6 class="mt-7" style="font-weight: bold;">FECHA DE ENTREGA</h6>
                        <p class="mb-7">{getdate(doc.delivery_date).strftime('%d/%m/%Y')}</p>
                    </td>
                </tr>
            </tbody>
        </table>
        <table class="withholding-voucher-table">
            <tbody>
                <tr>
                    <td style="width: 40%;">
                        <h6 class="mt-7" style="font-weight: bold;">NOMBRE O RAZÓN SOCIAL DEL CONTRIBUYENTE</h6>
                        <p class="mb-7">{doc.supplier}</p>
                    </td>
                    <td style="width: 30%;">
                        <h6 class="mt-7" style="font-weight: bold; margin-bottom: 0px !important;">REGISTRO DE INFORMACIÓN FISCAL </br> DEL CONTRIBUYENTE (R.I.F) </h6>
                        <p class="mb-7"> {supplier_tax_id} </p>
                    </td>
                    <td style="width: 30%;">
                        <h6 class="mt-7" style="font-weight: bold;">PERIODO FISCAL:</h6>
                        <p class="mb-7">{doc.fiscal_period}</p>
                    </td>
                </tr>
            </tbody>
        </table>
        <table class="withholding-voucher-table">
                    <tbody>
                        <tr>
                            <td style="width: 70%;">
                                <h6 class="mt-7" style="font-weight: bold;">DIRECCIÓN FISCAL DEL CONTRIBUYENTE </h6>
                                <p class="mb-7">{doc.supplier_address}</p>
                            </td>
                            <td style="width: 30%; border: none !important;"></td>
                        </tr>
                    </tbody>
                </table>
    </div>
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
            <td class="text-right">{item.tax_amount_vat}</td>
        </tr>
        """

    if current_page == total_pages - 1:
        table_rows += f"""
        <tr class="totales">
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td></td>
            <td>Totales:</td>
            <td class="text-right">{doc.totals_grand_total}</td>
            <td class="text-right">{doc.totals_total_exempt}</td>
            <td class="text-right">{doc.totals_total}</td>
            <td class="text-right"></td>
            <td class="text-right">{doc.totals_taxes_and_charges_added}</td>
            <td class="text-right">{doc.totals_tax_amount_vat}</td>
        </tr>
        """

    return f"""
    <div class="page-content">
        <div class="withholding-voucher-details" style="width: 100%;">
            <table class="withholding-voucher-details-table" style="margin-top: 5px; ">
                <thead>
                    <tr>
                        <th style="font-weight: bold; width: 5%;">Oper. N°</th>
                        <th style="font-weight: bold; width: 10%;">Fecha </br> Factura</th>
                        <th style="font-weight: bold; width: 10%;">Nº Factura</th>
                        <th style="font-weight: bold; width: 5%;">Nº Control</th>
                        <th style="font-weight: bold; width: 5%;">N/D</th>
                        <th style="font-weight: bold; width: 5%;">N/C</th>
                        <th style="font-weight: bold; width: 5%;">Tipo Trans.</th>
                        <th style="font-weight: bold; width: 5%;">Factura </br> Afectada</th>
                        <th style="font-weight: bold; width: 10%;">Total Compras </br> + IVA</th>
                        <th style="font-weight: bold; width: 10%;">Compras sin </br> credito fiscal</th>
                        <th style="font-weight: bold; width: 10%;">Base </br> Imponible</th>
                        <th style="font-weight: bold; width: 5%;">% Alicuota</th>
                        <th style="font-weight: bold; width: 10%;">IVA</th>
                        <th style="font-weight: bold; width: 10%;">IVA Retenido</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
    </div>
    """