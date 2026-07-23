# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from l10n_ve.l10n_ve.doctype.ve_conatel_tax_declaration.ve_conatel_tax_declaration import get_conatel_data

def execute(filters=None):
    if not filters:
        filters = {}

    columns = get_columns(filters)
    
    # Consumir la función unificada de obtención de datos
    res = get_conatel_data(
        company=filters.get("company"),
        from_date=filters.get("from_date"),
        to_date=filters.get("to_date"),
        branch=filters.get("branch"),
        cost_center=filters.get("cost_center"),
        customer=filters.get("customer")
    )
    
    data = res.get("detailed_data") or []
    report_summary = res.get("report_summary") or []

    return columns, data, None, None, report_summary

def get_columns(filters):
    columns = [
        {
            "fieldname": "invoice",
            "label": _("Invoice"),
            "fieldtype": "Data",
            "width": 180
        },
        {
            "fieldname": "posting_date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 100
        },
        {
            "fieldname": "document_type",
            "label": _("Tipo de Documento"),
            "fieldtype": "Data",
            "width": 140
        },
        {
            "fieldname": "control_no",
            "label": _("No. Control"),
            "fieldtype": "Data",
            "width": 120
        },
        {
            "fieldname": "customer_name",
            "label": _("Customer"),
            "fieldtype": "Data",
            "width": 200
        },
        {
            "fieldname": "customer",
            "label": _("Customer ID"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 120
        },
        {
            "fieldname": "tax_id",
            "label": _("Cédula / RIF"),
            "fieldtype": "Data",
            "width": 110
        },
        {
            "fieldname": "branch",
            "label": _("Branch"),
            "fieldtype": "Link",
            "options": "VE Branch",
            "width": 120
        },
        {
            "fieldname": "cost_center",
            "label": _("Cost Center"),
            "fieldtype": "Link",
            "options": "Cost Center",
            "width": 140
        },
        {
            "fieldname": "item_code",
            "label": _("Item Code"),
            "fieldtype": "Link",
            "options": "Item",
            "width": 130
        },
        {
            "fieldname": "item_name",
            "label": _("Item Name"),
            "fieldtype": "Data",
            "width": 180
        },
        {
            "fieldname": "taxable_base_usd",
            "label": _("Base Sujeta (USD)"),
            "fieldtype": "Currency",
            "options": "USD",
            "width": 150
        },
        {
            "fieldname": "taxable_base_ves",
            "label": _("Base Sujeta (Bs.)"),
            "fieldtype": "Currency",
            "options": "VES",
            "width": 150
        }
    ]

    # Columnas dinámicas en USD y VES por cada impuesto configurado en VE Conatel Tax Type
    tax_types = get_conatel_tax_types()
    for t in tax_types:
        fieldname_usd = frappe.scrub(f"conatel_tax_{t.name}_usd")
        fieldname_ves = frappe.scrub(f"conatel_tax_{t.name}_ves")
        
        columns.append({
            "fieldname": fieldname_usd,
            "label": f"{t.name} ({t.aliquot}%) USD",
            "fieldtype": "Currency",
            "options": "USD",
            "width": 160
        })
        columns.append({
            "fieldname": fieldname_ves,
            "label": f"{t.name} ({t.aliquot}%) Bs.",
            "fieldtype": "Currency",
            "options": "VES",
            "width": 160
        })

    return columns

def get_conatel_tax_types():
    return frappe.get_all("VE Conatel Tax Type", fields=["name", "aliquot"])
