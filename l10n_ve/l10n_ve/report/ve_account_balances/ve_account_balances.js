// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_account_balances"] = {
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
			"fieldname": "to_date",
			"label": __("Fecha de Corte"),
			"fieldtype": "Date",
			"default": frappe.datetime.nowdate(),
			"reqd": 1
		}
	],
	"formatter": function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		
		value = default_formatter(value, row, column, data);
		
		if (data.is_group || data.is_total) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}
		
		return value;
	}
};
