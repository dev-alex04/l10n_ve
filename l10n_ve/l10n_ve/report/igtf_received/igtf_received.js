// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["IGTF received"] = {
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
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		}
	],
	"onload": function(report) {
		report.page.add_inner_button(__("Descargar Excel"), function() {
			var filters = report.get_values();
			window.open(
				frappe.urllib.get_full_url(
					"/api/method/l10n_ve.l10n_ve.report.igtf_received.igtf_received_impression.download_custom_excel?filters=" +
					JSON.stringify(filters)
				)
			);
		});

		report.page.add_inner_button(__("Descargar PDF"), function() {
			var filters = report.get_values();
			window.open(
				frappe.urllib.get_full_url(
					"/api/method/l10n_ve.l10n_ve.report.igtf_received.igtf_received_impression.download_custom_pdf?filters=" +
					JSON.stringify(filters)
				)
			);
		});
	}
};
