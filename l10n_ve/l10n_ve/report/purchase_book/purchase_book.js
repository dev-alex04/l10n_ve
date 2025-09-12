// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["purchase_book"] = {
	"filters": [
		{
			"fieldname": "company",
			"fieldtype": "Link",
			"label": "Company",
			"options": "Company",
			"reqd": 1,
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname": "date_from",
			"fieldtype": "Date",
			"label": "Fecha Inicio",
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "to_date",
			"fieldtype": "Date",
			"label": "Fecha Fin",
			"default": frappe.datetime.get_today()
		}
	],
};
