import frappe
from frappe import _
import erpnext.accounts.report.gross_profit.gross_profit as gp

original_execute = gp.execute

def custom_execute(filters=None):
    columns, data = original_execute(filters)
    
    # 1. Cambiar etiquetas de las métricas
    for col in columns:
        if isinstance(col, dict):
            if col.get("fieldname") == "gross_profit":
                col["label"] = _("Análisis de Rentabilidad / Ventas")
            elif col.get("fieldname") == "gross_profit_%":
                col["label"] = _("Análisis de Rentabilidad (%)")

    # 2. Agregar la columna RIF (tax_id) si existe la columna "customer"
    customer_col_idx = -1
    for i, col in enumerate(columns):
        if isinstance(col, dict) and col.get("fieldname") == "customer":
            customer_col_idx = i
            break

    if customer_col_idx != -1:
        rif_col = {
            "fieldname": "tax_id",
            "label": _("RIF"),
            "fieldtype": "Data",
            "width": 120,
        }
        # Insertar después del cliente
        columns.insert(customer_col_idx + 1, rif_col)

        # Recopilar todos los clientes para hacer una sola consulta a DB
        customer_names = set()
        for row in data:
            if isinstance(row, dict):
                c = row.get("customer")
            else:
                c = row[customer_col_idx] if len(row) > customer_col_idx else None
            
            if c and str(c).strip() != "Total":
                customer_names.add(c)
                
        # Consultar RIFs
        tax_ids = {}
        if customer_names:
            customers = frappe.get_all(
                "Customer", 
                filters={"name": ("in", list(customer_names))}, 
                fields=["name", "tax_id"]
            )
            for doc in customers:
                tax_ids[doc.name] = doc.tax_id or ""

        # Enriquecer data con el RIF
        for row in data:
            if isinstance(row, dict):
                c = row.get("customer")
                if not c or str(c).strip() == "Total":
                    row["tax_id"] = ""
                else:
                    row["tax_id"] = tax_ids.get(c, "")
            else:
                c = row[customer_col_idx] if len(row) > customer_col_idx else None
                if not c or str(c).strip() == "Total":
                    row.insert(customer_col_idx + 1, "")
                else:
                    row.insert(customer_col_idx + 1, tax_ids.get(c, ""))

    return columns, data

gp.execute = custom_execute
