import frappe
from frappe.utils.pdf import get_pdf
from frappe.utils import fmt_money
import os
import base64
from frappe.utils.html_utils import escape_html

@frappe.whitelist()
def generate_installation_note_pdf(docname):
    doc = frappe.get_doc("Installation Note", docname)

    customer_phone = escape_html(frappe.db.get_value("Customer", doc.customer, "mobile_no") or "") if doc.customer else ""
    customer_tax_id = escape_html(frappe.db.get_value("Customer", doc.customer, "tax_id") or "") if doc.customer else ""

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
        except Exception as e:
            frappe.log_error(f"Error al incrustar el logo de la compañía: {e}")
            logo = frappe.utils.get_url(company.company_logo)

    company_addr_str = ""
    if company.custom_company_primary_address:
        c_addr = frappe.get_doc("Address", company.custom_company_primary_address)
        c_city = escape_html(frappe.db.get_value("VE City", c_addr.city, "city") or c_addr.city or "") if c_addr.city and frappe.db.exists("VE City", c_addr.city) else escape_html(c_addr.city or "")
        c_state = escape_html(frappe.db.get_value("VE State", c_addr.state, "state") or c_addr.state or "") if c_addr.state and frappe.db.exists("VE State", c_addr.state) else escape_html(c_addr.state or "")
        company_addr_str = f"<strong>{escape_html(c_addr.address_line1 or '')}</strong><br>{c_city}, {c_state}"

    customer_addr_str = ""
    if doc.get("customer_address"):
        addr = frappe.get_doc("Address", doc.customer_address)
        city = escape_html(frappe.db.get_value("VE City", addr.city, "city") or addr.city or "") if frappe.db.exists("VE City", addr.city) else escape_html(addr.city or "")
        state = escape_html(frappe.db.get_value("VE State", addr.state, "state") or addr.state or "") if frappe.db.exists("VE State", addr.state) else escape_html(addr.state or "")
        customer_addr_str = f"<strong>{escape_html(addr.address_line1 or '')}</strong><br>{city}, {state}"

    vendedores = frappe.get_all("Sales Team", filters={"parent": doc.customer, "parenttype": "Customer"}, pluck="sales_person") if doc.customer else []
    vendedor_display = escape_html(", ".join(vendedores)) if vendedores else "N/A"

    # Lógica de Precios y Moneda
    dn_items_map = {}
    delivery_note_name = doc.get("delivery_note")
    if not delivery_note_name:
        for item in doc.items:
            if item.get("prevdoc_doctype") == "Delivery Note":
                delivery_note_name = item.prevdoc_docname
                break

    dn_doc = None
    doc_currency = company.default_currency 
    if delivery_note_name:
        try:
            dn_doc = frappe.get_doc("Delivery Note", delivery_note_name)
            doc_currency = dn_doc.currency or doc_currency 
            for dn_item in dn_doc.items:
                dn_items_map[dn_item.item_code] = dn_item.rate
        except frappe.DoesNotExistError:
            frappe.log_error(f"Delivery Note {delivery_note_name} not found for Installation Note {doc.name}. Item rates will default to 0.")
            pass 

    display_currency = frappe.db.get_value("Currency", doc_currency, "symbol") or doc_currency

    items_data = []
    total_installation_amount = 0

    for item in doc.items:
        qty = item.get("qty", 1)
        rate = dn_items_map.get(item.item_code, 0)
        amount = rate * qty
        total_installation_amount += amount
        items_data.append({
            "equipo": escape_html(item.item_code),
            "desc": item.get("item_name") or item.get("description") or "",
            "qty": f"{qty:g}",
            "rate": fmt_money(rate, currency=display_currency),
            "amount": fmt_money(amount, currency=display_currency)
        })

    equipos_html = "".join([f"<tr><td style='padding: 10px;'><strong>{e['equipo']}</strong><br><span style='font-size: 9px; color: #666;'>{e['desc']}</span></td><td style='text-align:center;'>{e['qty']}</td></tr>" for e in items_data])
    fecha_doc = doc.get_formatted("inst_date") if doc.get("inst_date") else frappe.utils.formatdate(doc.creation)
    fecha_instalacion = doc.get_formatted("inst_date") or "N/A"
    
    escaped_customer_name = escape_html(doc.customer_name or "")
    escaped_remarks = escape_html(doc.remarks or "Sin observaciones adicionales.")

    bundle_rows_html = ""
    if dn_doc and hasattr(dn_doc, "packed_items") and dn_doc.packed_items:
        inst_note_bundle_qtys = {item.item_code: item.qty for item in doc.items}
        dn_bundle_qtys = {item.item_code: item.qty for item in dn_doc.items}

        for packed_item in dn_doc.packed_items:
            bundle_item_code = packed_item.parent_item
            inst_qty = inst_note_bundle_qtys.get(bundle_item_code)
            dn_qty = dn_bundle_qtys.get(bundle_item_code)

            if inst_qty and dn_qty and dn_qty > 0:
                qty_per_bundle = packed_item.qty / dn_qty
                final_component_qty = qty_per_bundle * inst_qty
                
                child_item_code = packed_item.item_code
                child_desc = packed_item.description or frappe.db.get_value("Item", child_item_code, "item_name") or ""
                uom = packed_item.uom or ""

                bundle_rows_html += f"""<tr>
                    <td style='padding: 4px 10px;'>
                        <strong>{escape_html(child_item_code)}</strong><br>
                        <div style='font-size: 9px; color: #666;'>{child_desc}</div>
                        <span style='font-size: 8px; color: #999;'>Incluido en: {escape_html(bundle_item_code)}</span>
                    </td>
                    <td style='text-align:center;'>{final_component_qty:g}</td>
                    <td style='text-align:center; font-size: 9px;'>{escape_html(uom)}</td>
                </tr>"""

    bundle_section = ""
    if bundle_rows_html:
        bundle_section = f"""
        <div style="clear: both; margin-top: 15px;"></div>
        <div class="section-header" style="font-size: 9px; padding: 4px 10px;">Contenido del Paquete</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th width="70%">Componente</th>
                    <th width="15%" style="text-align:center;">Cant.</th>
                    <th width="15%" style="text-align:center;">Unidad</th>
                </tr>
            </thead>
            <tbody>{bundle_rows_html}</tbody>
        </table>
        """

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica', sans-serif; color: #333; padding: 10px; }}
            .header-table {{ width: 100%; border-bottom: 2px solid #2c3e50; margin-bottom: 10px; padding-bottom: 10px; }}
            .header-table td {{ vertical-align: top; }}
            .logo {{ max-height: 50px; }} /* Reducido de 70px a 50px */
            .doc-info {{ text-align: right; font-size: 11px; }}
            .doc-title {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
            .section-header {{ background: #2c3e50; color: white; padding: 5px 10px; font-size: 10px; font-weight: bold; text-transform: uppercase; margin-top: 15px; }}
            .info-table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; border: 1px solid #e0e0e0; }}
            .info-table td {{ padding: 8px; font-size: 10px; border: 1px solid #e0e0e0; vertical-align: top; }}
            .label {{ color: #7f8c8d; font-size: 8px; text-transform: uppercase; display: block; margin-bottom: 3px; font-weight: bold; }}
            .data-table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }}
            .data-table th {{ border-bottom: 2px solid #333; padding: 10px; text-align: left; font-size: 11px; background: #f9f9f9; }}
            .data-table td {{ border-bottom: 1px solid #eee; padding: 10px; font-size: 11px; vertical-align: top; }}
            .total-box {{ float: right; width: 250px; border: 2px solid #2c3e50; margin-top: 20px; padding: 10px; text-align: right; }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td width="50%">
                    {f'<img src="{logo}" class="logo">' if logo else ''}
                    <div style="font-weight: bold; font-size: 12px; margin-top: 5px;">{escape_html(company.company_name or "")}</div>
                    <div style="font-size: 10px; color: #555;">RIF: {escape_html(company.tax_id or 'N/A')}</div>
                </td>
                <td class="doc-info" width="50%">
                    <div class="doc-title">NOTA DE INSTALACIÓN</div>
                    <span style="font-size: 14px; font-weight: bold;">{escape_html(doc.name or "")}</span><br><br>
                    <strong>VENDEDOR:</strong> {vendedor_display}<br>
                    <strong>FECHA:</strong> {escape_html(fecha_doc or "")}
                </td>
            </tr>
        </table>

        <div class="section-header">Información de Instalación</div>
        <table class="info-table">
            <tr>
                <td width="40%"><span class="label">Cliente / Razón Social</span>{escaped_customer_name}</td>
                <td width="20%"><span class="label">RIF / Cédula</span>{customer_tax_id}</td>
                <td width="20%"><span class="label">Teléfono</span>{customer_phone}</td>
                <td width="20%"><span class="label">Fecha Inst.</span>{fecha_instalacion}</td>
            </tr>
            <tr>
                <td width="40%"><span class="label">Dirección de Instalación (Cliente)</span>{customer_addr_str}</td>
                <td width="60%" colspan="3"><span class="label">Dirección de Origen (Empresa)</span>{company_addr_str}</td>
            </tr>
        </table>

        <div class="section-header">Detalles de Instalación</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th width="80%">Descripción</th>
                    <th width="20%" style="text-align:center;">Cant.</th>
                </tr>
            </thead>
            <tbody>{equipos_html}</tbody>
        </table>

        {bundle_section}

        <div style="clear: both; margin-top: 20px;">
            <span class="label">Observaciones</span>
            <div style="font-size: 10px; border: 1px solid #eee; padding: 10px; min-height: 50px;">{escaped_remarks}</div>
        </div>
    </body>
    </html>
    """

    pdf_file = get_pdf(html)
    frappe.local.response.filename = f"Orden_{docname}.pdf"
    frappe.local.response.filecontent = pdf_file
    frappe.local.response.type = "pdf"