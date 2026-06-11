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
	"onload": function (report) {
		report.page.add_inner_button(__("Exportar PDF"), function () {
			var filters = report.get_filter_values();
			var safe_filters = {};
			for (var k in filters) {
				if (filters[k] !== null && filters[k] !== undefined && filters[k] !== "") {
					safe_filters[k] = filters[k];
				}
			}

			var original_get_filter_values = report.get_filter_values;
			report.get_filter_values = function () {
				return safe_filters;
			};

			if (!report.data || !report.data.length) {
				frappe.msgprint(__("No hay datos en el reporte para exportar. Por favor genere el reporte primero."));
				report.get_filter_values = original_get_filter_values;
				return;
			}

			try {
				report.pdf_report({
					orientation: "Portrait",
					include_filters: true
				});
			} catch (err) {
				console.error(err);
			} finally {
				setTimeout(function () {
					report.get_filter_values = original_get_filter_values;
				}, 500);
			}
		});
	},
	"formatter": function (value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		
		value = default_formatter(value, row, column, data);
		
		if (data.is_group || data.is_total) {
			value = `<span style="font-weight: bold;">${value}</span>`;
		}
		
		return value;
	}
};
