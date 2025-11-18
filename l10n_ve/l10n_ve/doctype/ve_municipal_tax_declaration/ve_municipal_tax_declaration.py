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

    # Paso 1: Obtener los NOMBRES de las facturas que están en el rango de fechas.
    # La búsqueda se hace en el DocType 'Sales Invoice' porque ahí está el campo 'posting_date'.
    # Esto evita el error "Unknown column 'posting_date'".
    valid_invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]],
            "company": company,
        },
        pluck="name" # Solo queremos la lista de nombres de las facturas.
    )

    if not valid_invoices:
        return []

    # Paso 2: Con el campo 'economic_activity' ahora en 'Sales Invoice Item',
    # la consulta se simplifica a una sola llamada.
    invoice_items = frappe.get_all(
        "Sales Invoice Item",
        filters={
            "parent": ["in", valid_invoices],
            "economic_activity": ["is", "set"], # Filtramos directamente por el nuevo campo.
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

    # Paso 3: Obtener los detalles de las actividades (sector, branch, y el link a tax_municipality).
    # Asumimos que el DocType se llama 'VE ' y tiene los campos 'code', 'sector', 'branch'.
    activity_details = frappe.get_all("VE Economic Activity",
        filters={"name": ["in", activity_names]},
        fields=[
            "name", # ID de la actividad
            "code", # Código de la actividad
            "sector", # Nombre del sector
            "branch"  # Nombre del ramo
        ]
    )

    activity_map = {d.name: d for d in activity_details}

    # Paso 4: Usando el enlace 'economic_activity', obtener los detalles de los impuestos.
    # Esto asume que en 'VE Municipality Taxes' existe un campo Link llamado 'economic_activity'.
    tax_details_map = {}
    if activity_names:
        tax_details = frappe.get_all("VE Municipality Taxes",
            filters={
                "economic_activity": ["in", activity_names],
                "municipality": municipality # Filtramos también por el municipio.
            },
            fields=["economic_activity", "aliquot", "mt_tcmmv"]
        )
        # Creamos un mapa usando el nombre de la actividad económica como clave
        tax_details_map = {d.economic_activity: d for d in tax_details} # La clave es el ID de la actividad.

    # Paso 5: Combinar todos los datos.
    for item in invoice_items:
        details = activity_map.get(item.economic_activity)
        if details:
            item.update(details)
            # Buscamos el impuesto usando el nombre de la actividad económica
            tax_info = tax_details_map.get(item.economic_activity) # Buscamos por el ID de la actividad.
            if tax_info:
                item.update(tax_info)

    return invoice_items