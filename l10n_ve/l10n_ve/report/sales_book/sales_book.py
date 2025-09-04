# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days

def execute(filters=None):
    """
    Punto de entrada principal para el Reporte de Libro de Ventas.
    Devuelve las columnas y los datos basados en los filtros.
    """
    columns = get_columns()
    data = get_sales_data(filters)
    return columns, data

def get_columns():
    """
    Define las columnas de la tabla del reporte.
    """
    return [
        {"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("RIF del Cliente"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": 120},
        {"label": _("Nombre del Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
        {"label": _("Nro. de Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 150},
        {"label": _("Nro. de Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 120},
        {"label": _("Total Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
        {"label": _("Ventas Exoneradas"), "fieldname": "exempt_amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Base Imponible (G)"), "fieldname": "base_general", "fieldtype": "Currency", "width": 120},
        {"label": _("IVA (G)"), "fieldname": "iva_general", "fieldtype": "Currency", "width": 100},
        {"label": _("Base Imponible (R)"), "fieldname": "base_reduced", "fieldtype": "Currency", "width": 120},
        {"label": _("IVA (R)"), "fieldname": "iva_reduced", "fieldtype": "Currency", "width": 100},
        {"label": _("Base Imponible (A)"), "fieldname": "base_additional", "fieldtype": "Currency", "width": 120},
        {"label": _("IVA (A)"), "fieldname": "iva_additional", "fieldtype": "Currency", "width": 100},
        {"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 120},
    ]

def get_sales_data(filters):
    """
    Busca y procesa facturas de venta para generar los datos del reporte.
    """
    invoices_and_notes = frappe.get_list(
        "Sales Invoice",
        filters={
            "posting_date": ["between", [filters.get("from_date"), filters.get("to_date")]],
            "company": filters.get("company"),
            "docstatus": ["in", [1, 2]]
        },
        fields=[
            "name", "posting_date", "customer", "customer_name", "grand_total",
            "bill_no", "bill_control"
        ],
        order_by="posting_date asc"
    )

    data = []
    for doc in invoices_and_notes:
        doc_data = {
            "posting_date": doc.posting_date,
            "customer_tax_id": frappe.db.get_value("Customer", doc.customer, "tax_id"),
            "customer_name": doc.customer_name,
            "bill_no": doc.bill_no,
            "bill_control": doc.bill_control,
            "grand_total": doc.grand_total,
            "exempt_amount": 0,
            "base_general": 0,
            "iva_general": 0,
            "base_reduced": 0,
            "iva_reduced": 0,
            "base_additional": 0,
            "iva_additional": 0,
            "iva_retained": 0
        }

        taxes = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={"parent": doc.name},
            fields=["tax_amount", "base_tax_amount", "rate"]
        )

        for tax in taxes:
            if tax.rate == 16:
                doc_data["base_general"] += tax.base_tax_amount
                doc_data["iva_general"] += tax.tax_amount
            elif tax.rate == 8:
                doc_data["base_reduced"] += tax.base_tax_amount
                doc_data["iva_reduced"] += tax.tax_amount
            elif tax.rate == 30:
                doc_data["base_additional"] += tax.base_tax_amount
                doc_data["iva_additional"] += tax.tax_amount
            elif tax.rate == 0 and tax.tax_amount == 0:
                doc_data["exempt_amount"] += tax.base_tax_amount

        data.append(doc_data)

    return data

def get_filters():
    """
    Define los filtros que aparecen en la página del reporte.
    """
    return [
        {
            "fieldname": "company",
            "label": _("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1,
            "default": frappe.defaults.get_user_default("Company")
        },
        {
            "fieldname": "from_date",
            "label": _("From Date"),
            "fieldtype": "Date",
            "reqd": 1,
            "default": frappe.utils.add_days(frappe.utils.nowdate(), -30)
        },
        {
            "fieldname": "to_date",
            "label": _("To Date"),
            "fieldtype": "Date",
            "reqd": 1,
            "default": frappe.utils.nowdate()
        }
    ]
