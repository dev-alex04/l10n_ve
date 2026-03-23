import frappe
from frappe import _
import erpnext.accounts.report.gross_profit.gross_profit as gp

original_execute = gp.execute

def custom_execute(filters=None):
    columns, data = original_execute(filters)
    
    for col in columns:
        if isinstance(col, dict):
            if col.get("fieldname") == "gross_profit":
                col["label"] = _("Análisis de Rentabilidad / Ventas")
            elif col.get("fieldname") == "gross_profit_%":
                col["label"] = _("Análisis de Rentabilidad (%)")

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
        columns.insert(customer_col_idx + 1, rif_col)

        customer_names = set()
        for row in data:
            if isinstance(row, dict):
                c = row.get("customer")
            else:
                c = row[customer_col_idx] if len(row) > customer_col_idx else None
            
            if c and str(c).strip() != "Total":
                customer_names.add(c)
                
        tax_ids = {}
        if customer_names:
            customers = frappe.get_all(
                "Customer", 
                filters={"name": ("in", list(customer_names))}, 
                fields=["name", "tax_id"]
            )
            for doc in customers:
                tax_ids[doc.name] = doc.tax_id or ""

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

    if filters and filters.get("group_by") == "Invoice":
        cc_col = {
            "fieldname": "cost_center",
            "label": _("Centro de Costos"),
            "fieldtype": "Link",
            "options": "Cost Center",
            "width": 120,
        }
        
        insert_idx = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "tax_id":
                insert_idx = i + 1
                break
            elif isinstance(col, dict) and col.get("fieldname") == "customer":
                insert_idx = i + 1

        if insert_idx == -1:
            insert_idx = 4 

        columns.insert(insert_idx, cc_col)

        parents = list(set([row.get("parent_invoice") or row.get("sales_invoice") for row in data if isinstance(row, dict)]))
        parents = [p for p in parents if p and str(p).strip() != "Total"]

        if parents:
            si_items = frappe.db.sql(f"""
                select parent, item_code, cost_center 
                from `tabSales Invoice Item` 
                where parent in %s
            """, (tuple(parents),), as_dict=True)
            
            dn_items = frappe.db.sql(f"""
                select parent, item_code, cost_center 
                from `tabDelivery Note Item` 
                where parent in %s
            """, (tuple(parents),), as_dict=True)

            cc_map_exact = {}
            cc_map_parent = {}
            for item in si_items + dn_items:
                if item.cost_center:
                    cc_map_exact[(item.parent, item.item_code)] = item.cost_center
                    cc_map_parent[item.parent] = item.cost_center

            for row in data:
                if isinstance(row, dict):
                    p = row.get("parent_invoice")
                    name = row.get("sales_invoice")
                    
                    if p: 
                        row["cost_center"] = cc_map_exact.get((p, name)) or cc_map_parent.get(p, "")
                    elif name and str(name).strip() != "Total":
                        row["cost_center"] = cc_map_parent.get(name, "")
                    else:
                        row["cost_center"] = ""

    return columns, data

gp.execute = custom_execute
