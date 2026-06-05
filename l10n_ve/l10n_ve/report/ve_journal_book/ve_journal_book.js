// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_journal_book"] = {
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
			"fieldname": "presentation",
			"label": __("Presentación / Nivel"),
			"fieldtype": "Select",
			"options": "Detallado\nResumido\n1° Nivel\n2° Nivel\n3° Nivel",
			"default": "Detallado",
			"reqd": 1
		}
	],

	"formatter": function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);

		value = default_formatter(value, row, column, data);

		// Style group header, total rows and leaf accounts
		if (data.is_group_header || data.is_group_total || data.is_total) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}

		if (column.fieldname === "account" && data.indent) {
			let indent_px = data.indent * 12;
			value = `<span style="padding-left: ${indent_px}px; display: inline-block;">${value}</span>`;
		}

		return value;
	}
};
