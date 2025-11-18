# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from collections import defaultdict
import frappe
from frappe.model.document import Document


class VEMunicipalTaxDeclaration(Document):
    pass

@frappe.whitelist()
def get_activities_from_sales_invoices(from_date, to_date, company, municipality)-> list:
    """
    Busca en las Facturas de Venta, agrupa por actividad económica y devuelve
    una lista de diccionarios con todos los datos necesarios para la tabla hija.
    """
    if not from_date or not to_date or not company or not municipality:
        return []


    valid_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]],
            "company": company,
        },
        pluck="name"
    )

    if not valid_invoices:
        return []


    invoice_items = frappe.get_all(
        "Sales Invoice Item",
        filters={
            "parent": ["in", valid_invoices],
            "economic_activity": ["is", "set"],
        },
        fields=[
            "economic_activity",
            "SUM(base_net_amount) as taxable_base"
        ],
        group_by="economic_activity",
    )

    if not invoice_items:
        return []

    activity_names = [d.economic_activity for d in invoice_items]

    activity_details = frappe.get_all("VE Economic Activity",
        filters={"name": ["in", activity_names]},
        fields=[
            "name",
            "code",
            "sector",
            "branch"
        ]
    )

    activity_map = {d.name: d for d in activity_details}

    tax_details_map = {}
    if activity_names:
        tax_details = frappe.get_all("VE Municipality Taxes",
            filters={
                "economic_activity": ["in", activity_names],
                "municipality": municipality
            },
            fields=["economic_activity", "aliquot", "mt_tcmmv"]
        )
        tax_details_map = {d.economic_activity: d for d in tax_details}

    for item in invoice_items:
        details = activity_map.get(item.economic_activity)
        if details:
            item.update(details)
            tax_info = tax_details_map.get(item.economic_activity)
            if tax_info:
                item.update(tax_info)

    return invoice_items