import frappe
from frappe.utils.pdf import get_pdf
from frappe.utils import fmt_money
import os
import base64

@frappe.whitelist()
def generate_installation_note_pdf(docname):
    doc = frappe.get_doc("Installation Note", docname)

    # Datos del cliente
    customer_phone = frappe.db.get_value("Customer", doc.customer, "mobile_no") if doc.customer else ""
    customer_tax_id = frappe.db.get_value("Customer", doc.customer, "tax_id") if doc.customer else ""

    # Datos de la empresa
    company = frappe.get_doc("Company", doc.company)
    logo = ""
    if company.company_logo:
        try:
            file_path = frappe.get_site_path("public", company.company_logo.lstrip("/"))
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    encoded_string = base64.b64encode(f.read()).decode()
                extension = company.company_logo.split(".")[-1].lower()
                mime_type = f"image/{extension}" if extension != "svg" else "image/svg+xml"
                logo = f"data:{mime_type};base64,{encoded_string}"
        except Exception:
            logo = frappe.utils.get_url(company.company_logo)

    # Dirección de la Empresa (Lógica simplificada para la tabla)
    company_addr_str = ""
    if company.custom_company_primary_address:
        c_addr = frappe.get_doc("Address", company.custom_company_primary_address)
        c_city = frappe.db.get_value("VE City", c_addr.city, "city") if c_addr.city and frappe.db.exists("VE City", c_addr.city) else c_addr.city
        c_state = frappe.db.get_value("VE State", c_addr.state, "state") if c_addr.state and frappe.db.exists("VE State", c_addr.state) else c_addr.state
        company_addr_str = f"<strong>{c_addr.address_line1 or ''}</strong><br>{c_city}, {c_state}"

    # Dirección del Cliente
    customer_addr_str = ""
    if doc.get("customer_address"):
        addr = frappe.get_doc("Address", doc.customer_address)
        city = frappe.db.get_value("VE City", addr.city, "city") if frappe.db.exists("VE City", addr.city) else addr.city
        state = frappe.db.get_value("VE State", addr.state, "state") if frappe.db.exists("VE State", addr.state) else addr.state
        customer_addr_str = f"<strong>{addr.address_line1 or ''}</strong><br>{city}, {state}"

    # Obtener Vendedor
    vendedores = frappe.get_all("Sales Team", filters={"parent": doc.customer, "parenttype": "Customer"}, pluck="sales_person") if doc.customer else []
    vendedor_display = ", ".join(vendedores) if vendedores else "N/A"

    # Lógica de Precios
    dn_items_map = {}
    delivery_note_name = doc.get("delivery_note")
    if not delivery_note_name:
        for item in doc.items:
            if item.get("prevdoc_doctype") == "Delivery Note":
                delivery_note_name = item.prevdoc_docname
                break

    if delivery_note_name:
        dn_doc = frappe.get_doc("Delivery Note", delivery_note_name)
        for dn_item in dn_doc.items:
            dn_items_map[dn_item.item_code] = dn_item.rate

    items_data = []
    total_installation_amount = 0
    display_currency = "Bs."

    for item in doc.items:
        qty = item.get("qty", 1)
        rate = dn_items_map.get(item.item_code, 0)
        amount = rate * qty
        total_installation_amount += amount
        items_data.append({
            "equipo": item.item_code,
            "desc": item.get("item_name") or item.get("description"),
            "qty": f"{qty:g}",
            "rate": fmt_money(rate, currency=display_currency),
            "amount": fmt_money(amount, currency=display_currency)
        })

    equipos_html = "".join([f"<tr><td style='padding: 10px;'><strong>{e['equipo']}</strong><br><span style='font-size: 9px; color: #666;'>{e['desc']}</span></td><td style='text-align:center;'>{e['qty']}</td><td style='text-align:right;'>{e['rate']}</td><td style='text-align:right;'>{e['amount']}</td></tr>" for e in items_data])
    fecha_doc = doc.get_formatted("inst_date") if doc.get("inst_date") else frappe.utils.formatdate(doc.creation)

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica', sans-serif; color: #333; padding: 10px; }}
            .header-table {{ width: 100%; border-bottom: 2px solid #2c3e50; margin-bottom: 10px; padding-bottom: 10px; }}
            .logo {{ max-height: 50px; }} /* Reducido de 70px a 50px */
            .doc-info {{ text-align: right; font-size: 11px; }}
            .doc-title {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
            .section-header {{ background: #2c3e50; color: white; padding: 5px 10px; font-size: 10px; font-weight: bold; text-transform: uppercase; margin-top: 15px; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; border: 1px solid #e0e0e0; }}
            .info-table td {{ padding: 8px; font-size: 10px; border: 1px solid #e0e0e0; vertical-align: top; }}
            .label {{ color: #7f8c8d; font-size: 8px; text-transform: uppercase; display: block; margin-bottom: 3px; font-weight: bold; }}
            .data-table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }}
            .data-table th {{ border-bottom: 2px solid #333; padding: 10px; text-align: left; font-size: 11px; background: #f9f9f9; }}
            .data-table td {{ border-bottom: 1px solid #eee; padding: 10px; font-size: 11px; }}
            .total-box {{ float: right; width: 250px; border: 2px solid #2c3e50; margin-top: 20px; padding: 10px; text-align: right; }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td width="50%">
                    {f'<img src="{logo}" class="logo">' if logo else ''}
                    <div style="font-weight: bold; font-size: 12px; margin-top: 5px;">{company.company_name}</div>
                    <div style="font-size: 10px; color: #555;">RIF: {company.tax_id or 'N/A'}</div>
                </td>
                <td class="doc-info" width="50%">
                    <div class="doc-title">NOTA DE INSTALACIÓN</div>
                    <span style="font-size: 14px; font-weight: bold;">{doc.name}</span><br><br>
                    <strong>VENDEDOR:</strong> {vendedor_display}<br>
                    <strong>FECHA:</strong> {fecha_doc}
                </td>
            </tr>
        </table>

        <div class="section-header">Información de Instalación</div>
        <table class="info-table">
            <tr>
                <td width="50%"><span class="label">Cliente / Razón Social</span>{doc.customer_name}</td>
                <td width="25%"><span class="label">RIF / Cédula</span>{customer_tax_id}</td>
                <td width="25%"><span class="label">Teléfono</span>{customer_phone}</td>
            </tr>
            <tr>
                <td width="50%"><span class="label">Dirección de Instalación (Cliente)</span>{customer_addr_str}</td>
                <td width="50%" colspan="2"><span class="label">Dirección de Origen (Empresa)</span>{company_addr_str}</td>
            </tr>
        </table>

        <div class="section-header">Detalles de Instalación</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th width="50%">Descripción</th>
                    <th width="10%" style="text-align:center;">Cant.</th>
                    <th width="20%" style="text-align:right;">Precio</th>
                    <th width="20%" style="text-align:right;">Total</th>
                </tr>
            </thead>
            <tbody>{equipos_html}</tbody>
        </table>

        <div class="total-box">
            <span style="font-size: 9px; color: #666; display: block;">MONTO TOTAL NETO</span>
            <strong style="font-size: 16px;">{fmt_money(total_installation_amount, currency=display_currency)}</strong>
        </div>

        <div style="clear: both; margin-top: 20px;">
            <span class="label">Observaciones</span>
            <div style="font-size: 10px; border: 1px solid #eee; padding: 10px; min-height: 50px;">{doc.remarks or 'Sin observaciones adicionales.'}</div>
        </div>
    </body>
    </html>
    """

    pdf_file = get_pdf(html)
    frappe.local.response.filename = f"Orden_{docname}.pdf"
    frappe.local.response.filecontent = pdf_file
    frappe.local.response.type = "pdf"