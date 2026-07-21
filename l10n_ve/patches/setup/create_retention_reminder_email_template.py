import frappe

def execute() -> None:
    """Crea la plantilla predeterminada en Email Template."""
    print("Ejecutando parche: Creando plantilla de correo predeterminada para recordatorio de retención...")
    
    template_name = "Recordatorio de Retenciones Pendientes"
    
    html_content = """<div style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
    <div style="background-color: #1e3a8a; padding: 24px; text-align: center; color: #ffffff;">
        <h2 style="margin: 0; font-size: 20px; font-weight: 600; letter-spacing: 0.5px;">Recordatorio de Retenciones Pendientes</h2>
    </div>
    <div style="padding: 24px; color: #2d3748; line-height: 1.6;">
        <p style="margin-top: 0; font-size: 16px; font-weight: bold;">Estimado(a) {{ customer_name }},</p>
        <p style="font-size: 14px; color: #4a5568;">
            Le escribimos para recordarle que tenemos pendiente el registro de los comprobantes de retención correspondientes a las siguientes facturas de venta. Agradecemos su valioso apoyo gestionando el envío de estos soportes a la brevedad:
        </p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0;">
            <thead>
                <tr style="background-color: #f7fafc;">
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Factura</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Control</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Fecha Emisión</th>
                    <th style="padding: 12px; text-align: center; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Retención Faltante</th>
                </tr>
            </thead>
            <tbody>
                {% for inv in invoices %}
                <tr>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #2d3748; font-weight: 500;">{{ inv.name }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #4a5568;">{{ inv.bill_control or "" }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #4a5568;">{{ inv.formatted_date }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; text-align: center;">
                        {% if inv.missing_vat %}
                        <span style="background-color: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 4px; display: inline-block;">IVA</span>
                        {% endif %}
                        {% if inv.missing_islr %}
                        <span style="background-color: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">ISLR</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        
        <p style="font-size: 14px; color: #4a5568; margin-bottom: 24px;">
            Por favor, responda a este correo adjuntando los comprobantes fiscales correspondientes para que podamos procesarlos y conciliar su cuenta.
        </p>
        
        <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; font-size: 12px; color: #718096; text-align: center;">
            <p style="margin: 0 0 8px 0; font-style: italic;">Este es un mensaje automático del sistema de facturación.</p>
            {% if company %}
            <div style="background-color: #f8fafc; border: 1px solid #edf2f7; border-radius: 6px; padding: 12px; margin-top: 12px; text-align: center; display: inline-block; min-width: 250px;">
                <strong style="color: #2d3748; font-size: 13px;">{{ company }}</strong>
            </div>
            {% endif %}
        </div>
    </div>
</div>"""

    if not frappe.db.exists("Email Template", template_name):
        doc = frappe.new_doc("Email Template")
        doc.name = template_name
        doc.subject = "Recordatorio: Comprobantes de Retención Pendientes"
        doc.use_html = 1
        doc.response_html = html_content
        doc.insert(ignore_permissions=True)
        print(f"  ✔ Plantilla predeterminada '{template_name}' creada.")
    else:
        # Si ya existe pero el HTML está vacío, tiene un bucle Jinja roto o tiene columnas obsoletas, lo actualizamos
        doc = frappe.get_doc("Email Template", template_name)
        is_broken = False
        current_html = doc.response_html or doc.response or ""
        if current_html and "{% for inv in invoices %}" in current_html and "{% endfor %}" in current_html:
            loop_content = current_html.split("{% for inv in invoices %}")[1].split("{% endfor %}")[0]
            if "<tr>" not in loop_content and "<tr" not in loop_content:
                is_broken = True
        
        if current_html and ("branch_info" in current_html or "formatted_total" in current_html or "Monto Total" in current_html):
            is_broken = True

        if not current_html or len(current_html.strip()) < 50 or is_broken:
            doc.response_html = html_content
            doc.use_html = 1
            doc.save(ignore_permissions=True)
            print(f"  ✔ Plantilla '{template_name}' actualizada con contenido base corregido.")
        else:
            print(f"  -- La plantilla '{template_name}' ya existe y tiene contenido, se omite.")
