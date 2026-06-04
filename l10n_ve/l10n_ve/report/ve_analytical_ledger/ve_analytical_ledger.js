// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_analytical_ledger"] = {
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
	],
	"formatter": function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);

		value = default_formatter(value, row, column, data);

		if (data.is_header || data.is_total) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}

		if (column.fieldtype === "Currency" && data[column.fieldname] < 0) {
			value = `<span style="color: red;">${value}</span>`;
		}

		return value;
	}
};
