// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["Sales book"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 1,
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.defaults.get_user_default("From Date"),
			"reqd": 1
		},
		{
			"fieldname":"to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.defaults.get_user_default("To Date"),
			"reqd": 1
		},
	],
	"onload": function(report) {
		report.page.add_inner_button(__("Exportar a Excel"), function() {
			frappe.show_alert({
				message: __("Generando archivo Excel..."),
				indicator: 'blue'
			});
			
			const filters = report.get_filters();
			const url = frappe.url.get_full_url("/api/method/l10n_ve.l10n_ve.report.sales_book.sales_book.excel_builder");

			frappe.open_url(url, { filters }, "POST");
		});
	}
};

