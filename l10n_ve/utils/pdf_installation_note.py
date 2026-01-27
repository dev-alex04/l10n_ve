import frappe
from frappe.utils.pdf import get_pdf
from frappe.utils import fmt_money
import os
import base64

@frappe.whitelist()
def generate_installation_note_pdf(docname):
    doc = frappe.get_doc("Installation Note", docname)

    customer_phone = frappe.db.get_value("Customer", doc.customer, "mobile_no") if doc.customer else ""
    customer_tax_id = frappe.db.get_value("Customer", doc.customer, "tax_id") if doc.customer else ""

    company = frappe.get_doc("Company", doc.company)
    logo = ""
    if company.company_logo:
        if company.company_logo.startswith("http"):
            logo = company.company_logo
        else:
            try:
                file_path = frappe.get_site_path("public", company.company_logo.lstrip("/"))
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        encoded_string = base64.b64encode(f.read()).decode()
                    extension = company.company_logo.split(".")[-1].lower()
                    mime_type = "image/png"
                    if extension == "svg":
                        mime_type = "image/svg+xml"
                    elif extension in ["jpg", "jpeg"]:
                        mime_type = "image/jpeg"
                    logo = f"data:{mime_type};base64,{encoded_string}"
                else:
                    logo = frappe.utils.get_url(company.company_logo)
            except Exception:
                logo = frappe.utils.get_url(company.company_logo)

    customer_address_html = ""
    if doc.get("customer_address"):
        addr = frappe.get_doc("Address", doc.customer_address)
        city = addr.city
        if city and frappe.db.exists("VE City", city):
            city = frappe.db.get_value("VE City", city, "city")
        state = addr.state
        if state and frappe.db.exists("VE State", state):
            state = frappe.db.get_value("VE State", state, "state")
        municipality = addr.get("municipality")
        if municipality and frappe.db.exists("VE Municipality", municipality):
            municipality = frappe.db.get_value("VE Municipality", municipality, "municipality")

        line1 = f"{addr.address_line1 or ''} {addr.address_line2 or ''}".strip()
        loc_parts = [p for p in [city, municipality, state] if p]
        location = ", ".join(loc_parts)
        customer_address_html = f"{line1}<br>{location}"
    else:
        customer_address_html = doc.address_display.replace("\n", ", ") if doc.address_display else "N/A"

    company_address = ""
    if company.custom_company_primary_address:
        c_addr = frappe.get_doc("Address", company.custom_company_primary_address)
        c_city = frappe.db.get_value("VE City", c_addr.city, "city") if c_addr.city and frappe.db.exists("VE City", c_addr.city) else c_addr.city
        c_state = frappe.db.get_value("VE State", c_addr.state, "state") if c_addr.state and frappe.db.exists("VE State", c_addr.state) else c_addr.state
        c_loc_parts = [p for p in [c_city, c_state] if p]
        c_location = ", ".join(c_loc_parts)
        company_address = f"{c_location}<br>{c_addr.address_line1 or ''}"

    sales_persons = []
    if doc.customer:
        sales_persons = frappe.get_all("Sales Team", 
                                        filters={"parent": doc.customer, "parenttype": "Customer"}, 
                                        pluck="sales_person")

    items_data = []
    materials_data = []

    dn_items_map = {}
    dn_doc = None
    delivery_note_name = doc.get("delivery_note")
    subscription_plan_name = ""
    
    if not delivery_note_name:
        for item in doc.items:
            if item.get("prevdoc_docname") and item.get("prevdoc_doctype") == "Delivery Note":
                delivery_note_name = item.prevdoc_docname
                break

    if delivery_note_name:
        dn_doc = frappe.get_doc("Delivery Note", delivery_note_name)
        subscription_plan_name = dn_doc.get("subscription_plan") or ""
        for dn_item in dn_doc.items:
            dn_items_map[dn_item.item_code] = dn_item.rate

    total_installation_amount = 0
    display_currency = dn_doc.currency if dn_doc else frappe.get_cached_value('Company', doc.company, 'default_currency')

    if doc.get("items"):
        for item in doc.items:
            qty = item.get("qty", 1)
            rate = dn_items_map.get(item.item_code, 0)
            amount = rate * qty
            total_installation_amount += amount

            items_data.append({
                "equipo": item.item_code,
                "desc": item.get("item_name") or item.get("description") or frappe.db.get_value("Item", item.item_code, "item_name"),
                "qty": f"{qty:g}",
                "rate": fmt_money(rate, currency=display_currency),
                "amount": fmt_money(amount, currency=display_currency)
            })
            
            if not delivery_note_name:
                product_bundle = frappe.db.get_value("Product Bundle", {"new_item_code": item.item_code}, "name")
                if product_bundle:
                    bundle_items = frappe.get_all("Product Bundle Item",
                                                  filters={"parent": product_bundle},
                                                  fields=["item_code", "description", "qty", "uom"])
                    for bi in bundle_items:
                        materials_data.append({
                            "desc": bi.description or frappe.db.get_value("Item", bi.item_code, "item_name"),
                            "cant": f"{bi.qty:g} {bi.uom or ''}"
                        })

    if delivery_note_name:
        packed_items = frappe.get_all("Packed Item",
                                      filters={"parent": delivery_note_name},
                                      fields=["item_name", "qty", "uom"])
        for pi in packed_items:
            materials_data.append({
                "desc": pi.item_name,
                "cant": f"{pi.qty:g} {pi.uom or ''}"
            })

    data = {
        "company": company,
        "logo": logo,
        "company_address": company_address,
        "nro_orden": doc.name,
        "vendedor": ", ".join([s for s in sales_persons if s]),
        "telefono": customer_phone or "N/A",
        "fecha_emision": frappe.utils.formatdate(frappe.utils.nowdate()),
        "fecha_instalacion": doc.get_formatted("inst_date") or "",
        "cliente": doc.customer_name or "N/A",
        "cedula": customer_tax_id or "N/A",
        "direccion_cliente": customer_address_html,
        "monto_total": fmt_money(total_installation_amount, currency=display_currency),
        "observaciones": doc.remarks or "",
        "equipos": items_data,
        "materiales": materials_data,
        "subscription_plan": subscription_plan_name
    }

    equipos_html = "".join([f"<tr><td style='text-align:center;'>{e['equipo']}</td><td>{e['desc']}</td><td style='text-align:center;'>{e['qty']}</td><td style='text-align:right;'>{e['rate']}</td><td style='text-align:right;'>{e['amount']}</td></tr>" for e in data['equipos']])
    materiales_html = "".join([f"<tr><td>{m['desc']}</td><td style='text-align:center;'>{m['cant']}</td></tr>" for m in data['materiales']])

    plan_html = ""
    if data["subscription_plan"]:
        plan_html = f"""
        <div style="margin-top: 5px; margin-bottom: 10px;">
            <table class="data-table">
                <tr>
                    <td width="20%" style="background: #f9f9f9;"><strong>Plan Contratado:</strong></td>
                    <td>{data['subscription_plan']}</td>
                </tr>
            </table>
        </div>
        """

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: 'Helvetica', sans-serif; color: #333; padding: 20px; }}
            .header-table {{ width: 100%; border-bottom: 2px solid #333; margin-bottom: 20px; padding-bottom: 10px; }}
            .logo-cell {{ width: 60%; vertical-align: middle; }}
            .info-cell {{ width: 40%; text-align: right; font-size: 10px; line-height: 1.4; }}
            .section-title {{ background: #f2f2f2; text-align: center; font-weight: bold; padding: 6px; margin: 15px 0 5px; border: 1px solid #ccc; text-transform: uppercase; font-size: 11px; }}
            .data-table {{ width: 100%; border-collapse: collapse; }}
            .data-table th, .data-table td {{ border: 1px solid #ccc; padding: 8px; text-align: left; font-size: 11px; }}
            .data-table th {{ background: #f9f9f9; }}
            .obs-box {{ border: 1px solid #ccc; min-height: 100px; padding: 10px; font-size: 11px; margin-top: 0; background: #fff; }}
            .total-wrapper {{ margin-top: 15px; text-align: right; }}
            .total-box {{ display: inline-block; border: 2px solid #000; padding: 10px; background: #fff; min-width: 150px; }}
            .total-text {{ font-size: 14px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td class="logo-cell">
                    {f'<img src="{data["logo"]}" style="max-height: 70px; max-width: 200px;">' if data["logo"] else '<div style="padding: 10px; color: #888; font-size: 10px; border: 1px dashed #ccc; display: inline-block;">Logo no configurado</div>'}
                    <div style="font-weight: bold; font-size: 10px; margin-top: 5px;">{data['company'].company_name}</div>
                    <div style="font-size: 9px;">{data['company'].tax_id or ''}</div>
                </td>
                <td class="info-cell">
                    <strong style="font-size: 12px;">{data['company'].company_name}</strong><br>
                    {data['company_address']}<br>
                    <span style="font-size: 11px; margin-top: 5px; display: block;">
                        <strong>ORDEN:</strong> {data['nro_orden']}<br>
                        {f'<strong>Vendedor:</strong> {data["vendedor"]}<br>' if data["vendedor"] else ''}
                        <strong>EMISIÓN:</strong> {data['fecha_emision']}
                    </span>
                </td>
            </tr>
        </table>

        <div class="section-title">Datos del Cliente</div>
        <table class="data-table">
            <tr>
                <td width="20%"><strong>Nombre:</strong></td>
                <td width="30%">{data['cliente']}</td>
                <td width="20%"><strong>Cédula:</strong></td>
                <td width="30%">{data['cedula']}</td>
            </tr>
            <tr>
                <td><strong>Dirección:</strong></td>
                <td colspan="3">{data['direccion_cliente']}</td>
            </tr>
            <tr>
                <td><strong>Teléfono:</strong></td>
                <td>{data['telefono']}</td>
                <td><strong>Fecha de Instalación:</strong></td>
                <td>{data['fecha_instalacion']}</td>
            </tr>
        </table>

        <div class="section-title">Detalles de Instalación</div>
        <table class="data-table">
            <thead><tr><th width="15%">Código</th><th width="45%">Descripción</th><th width="10%">Cant.</th><th width="15%">Precio</th><th width="15%">Total</th></tr></thead>
            <tbody>{equipos_html}</tbody>
        </table>
        {plan_html}

        <div class="section-title">Accesorios Instalados</div>
        <table class="data-table">
            <thead><tr><th>Materiales</th><th width="25%">Cantidad</th></tr></thead>
            <tbody>{materiales_html}</tbody>
        </table>

        <div class="section-title" style="text-align: left; padding-left: 10px;">Observaciones</div>
        <div class="obs-box">{data['observaciones'] or ''}</div>

        <div class="total-wrapper">
            <div class="total-box">
                <span class="total-text">TOTAL: {data['monto_total']}</span>
            </div>
        </div>

        <table style="width: 100%; margin-top: 80px;">
            <tr>
                <td style="width: 40%; text-align: center; border-top: 1px solid #000; padding-top: 5px;">
                    <strong>Firma del Cliente</strong><br>
                    <span style="font-size: 10px;">{data['cliente']}</span>
                </td>
                <td style="width: 20%;"></td>
                <td style="width: 40%; text-align: center; border-top: 1px solid #000; padding-top: 5px;">
                    <strong>Firma del Técnico</strong>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    pdf_file = get_pdf(html)
    frappe.local.response.filename = f"Orden_{docname}.pdf"
    frappe.local.response.filecontent = pdf_file
    frappe.local.response.type = "pdf"