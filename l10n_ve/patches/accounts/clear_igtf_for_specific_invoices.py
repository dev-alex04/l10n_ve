import frappe

def execute():
    """
    Limpia los campos de IGTF (establece en 0) para las facturas específicas
    ACC-SINV-2026-09026 y ACC-SINV-2026-10164-1. Esto también corregirá
    de forma automática el cálculo dinámico de IGTF en sus respectivas Notas de Crédito.
    """
    invoices = ["ACC-SINV-2026-09026", "ACC-SINV-2026-10164-1"]
    
    for inv_name in invoices:
        if frappe.db.exists("Sales Invoice", inv_name):
            frappe.db.set_value("Sales Invoice", inv_name, {
                "base_amount_igtf": 0.0,
                "total_igtf": 0.0,
                "igtf_rate": 0.0
            })
            frappe.clear_document_cache("Sales Invoice", inv_name)
            
    frappe.db.commit()
