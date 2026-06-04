// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_balance_sheet"] = {
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
		},
		{
			"fieldname": "presentation",
			"label": __("Presentación"),
			"fieldtype": "Select",
			"options": "1 Columna\n3 Columnas (por niveles)",
			"default": "1 Columna",
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

		if (column.fieldname === "account") {
			let text = "";
			if (data.is_header) {
				let num = data.account_number ? `<span style="display: inline-block; width: 80px; font-weight: bold;">${data.account_number}</span>` : "";
				text = `${num}<span style="font-weight: bold;">${data.account_name}</span>`;
				value = `<span>${text}</span>`;
			} else if (data.is_total) {
				text = `<span style="font-weight: bold; margin-left: 40px;">${data.account_name}</span>`;
				value = `<span>${text}</span>`;
			} else {
				let num = data.account_number ? `<span style="display: inline-block; width: 80px;">${data.account_number}</span>` : "";
				text = `${num}<span>${data.account_name}</span>`;
				value = `<span>${text}</span>`;
			}
		}

		if (data.is_group || data.is_header || data.is_total) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}

		if (column.fieldtype === "Currency" && data[column.fieldname] < 0) {
			value = `<span style="color: red;">${value}</span>`;
		}

		return value;
	}
};
