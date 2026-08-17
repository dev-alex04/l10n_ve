// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["prorrata_iva"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_start(),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1
		}
	],
	"onload": function(report) {
		report.page.add_inner_button(__("Mes Actual"), function() {
			report.set_filter_value("from_date", frappe.datetime.month_start());
			report.set_filter_value("to_date", frappe.datetime.month_end());
			report.refresh();
		});

		report.page.add_inner_button(__("Mes Anterior"), function() {
			var from_date = moment().subtract(1, "months").startOf("month").format("YYYY-MM-DD");
			var to_date = moment().subtract(1, "months").endOf("month").format("YYYY-MM-DD");
			report.set_filter_value("from_date", from_date);
			report.set_filter_value("to_date", to_date);
			report.refresh();
		});
	}
};
