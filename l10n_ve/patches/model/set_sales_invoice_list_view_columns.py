"""Configura las columnas de la vista de lista de Sales Invoice.

Agrega 'Nro. Control' (bill_control) y 'Cliente' (customer_name)
a la vista de lista para facilitar la identificación rápida de facturas
sin necesidad de abrir cada documento.

El List View Settings tiene prioridad sobre los property setters
de in_list_view, lo que garantiza un orden determinístico de columnas.
"""

import json

import frappe


def execute() -> None:
    list_view_fields: list[dict] = [
        {"fieldname": "bill_no", "label": "Número de Factura"},
        {"fieldname": "bill_control", "label": "Nro. Control"},
        {"fieldname": "customer_name", "label": "Cliente"},
        {"fieldname": "status_field", "label": "Estado"},
        {"fieldname": "grand_total", "label": "Total"},
    ]

    if frappe.db.exists("List View Settings", "Sales Invoice"):
        frappe.db.set_value(
            "List View Settings",
            "Sales Invoice",
            "fields",
            json.dumps(list_view_fields),
        )
    else:
        doc = frappe.new_doc("List View Settings")
        doc.name = "Sales Invoice"
        doc.fields = json.dumps(list_view_fields)
        doc.total_fields = 5
        doc.insert(ignore_permissions=True)

    frappe.clear_cache(doctype="Sales Invoice")
