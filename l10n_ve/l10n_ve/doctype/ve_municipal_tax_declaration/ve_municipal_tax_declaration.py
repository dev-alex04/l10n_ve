# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt


import frappe
from frappe.model.document import Document
from frappe.utils import get_defaults


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
            "SUM(base_amount) as taxable_base"
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

@frappe.whitelist()
def get_exchange_rate(declaration_date, from_currency)->float:
	to_currency = get_defaults().get("currency")
	if not declaration_date or not from_currency or not to_currency:
		return 0

	exchange_rate = frappe.db.get_value("Currency Exchange", {
		"date": declaration_date, "from_currency": from_currency, "to_currency": to_currency
	}, "exchange_rate")

	return exchange_rate or 0

@frappe.whitelist()
def get_company_details_for_declaration(company_name: str) -> dict:
	"""
	Obtiene los detalles de la compañía y su dirección principal para la declaración.
	"""
	if not company_name:
		return {}

	company = frappe.get_doc("Company", company_name, fields=[ # type: ignore
		"tax_id", "num_license_economic", "legal_representative",
		"legal_representative_id", "municipality", "custom_company_primary_address"
	])

	details = company.as_dict()
	details["address_details"] = None

	if company.custom_company_primary_address:
		try:
			address = frappe.get_doc("Address", company.custom_company_primary_address, fields=[ # type: ignore
				"address_line1", "state", "parish", "phone", "email_id"
			])
			address_details = address.as_dict()

			# Obtener los nombres legibles para los campos Link de la dirección
			if address.state:
				address_details["state_name"] = frappe.db.get_value("VE State", address.state, "state")
			if address.parish:
				address_details["parish_name"] = frappe.db.get_value("VE Parish", address.parish, "parish")

			details["address_details"] = address_details

		except frappe.DoesNotExistError:
			frappe.log_error(
				f"La dirección '{company.custom_company_primary_address}' no fue encontrada.",
				"Error en get_company_details_for_declaration"
			)

	# Obtener el nombre legible para el campo Link de municipio en la compañía
	if company.municipality:
		details["municipality_name"] = frappe.db.get_value("VE Municipality", company.municipality, "municipality")

	return details