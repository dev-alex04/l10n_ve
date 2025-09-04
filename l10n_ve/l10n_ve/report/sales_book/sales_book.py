# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    columns = get_columns()
    data = get_sales_data(filters)
    return columns, data

def get_columns():
    columns = [
        {"label": _("Compañía"), "fieldname": "company", "fieldtype": "Data", "width": 200},
    ]
    return columns

def get_sales_data(filters):
    sales_invoices = frappe.get_list(
        "Sales Invoice",
        filters={
            "posting_date": ["between", [filters.get("from_date"), filters.get("to_date")]],
            "company": filters.get("company"),
            "docstatus": ["in", [1, 2]]
        },
        fields=["posting_date"],
        order_by="posting_date asc"
    )

    # Línea de depuración: Imprime la cantidad de facturas encontradas
    print(f"Se encontraron {len(sales_invoices)} facturas de venta.")
    
    return sales_invoices