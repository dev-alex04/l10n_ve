// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_cash_flow"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Empresa"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("company"),
			"reqd": 1
		},
		{
			"fieldname": "from_date",
			"label": __("Desde"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_start(),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("Hasta"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1
		},
		{
			"fieldname": "cost_center",
			"label": __("Centro de Costo"),
			"fieldtype": "Link",
			"options": "Cost Center"
		}
	]
};
