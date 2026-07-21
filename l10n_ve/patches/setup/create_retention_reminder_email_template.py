import os
import frappe

def execute() -> None:
    """Crea la plantilla predeterminada en Email Template."""
    print("Ejecutando parche: Creando plantilla de correo predeterminada para recordatorio de retención...")
    
    template_name = "Recordatorio de Retenciones Pendientes"
    
    html_content = ""
    try:
        # Leer el archivo físico para precargar la plantilla en BD
        template_path = os.path.join(
            frappe.get_app_path("l10n_ve"),
            "templates",
            "emails",
            "missing_retention_reminder.html"
        )
        if os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                html_content = f.read()
    except Exception:
        pass

    if not html_content:
        html_content = "<p>Por favor, configure la plantilla de retenciones pendientes.</p>"

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
