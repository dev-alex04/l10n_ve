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
			"reqd": 0
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 0
		}
	],
	"onload": function(report) {
    const add_download_button = (label, method) => {
        report.page.add_inner_button(__(label), function() {
            const filters = report.get_values();
            window.open(
                frappe.urllib.get_full_url(
                    `/api/method/${method}?filters=${encodeURIComponent(JSON.stringify(filters))}`
                )
            );
        });
    };

    add_download_button("Descargar Excel", "l10n_ve.l10n_ve.report.igtf_received.igtf_received_impression.download_custom_excel");
    add_download_button("Descargar PDF", "l10n_ve.l10n_ve.report.igtf_received.igtf_received_impression.download_custom_pdf");
}
};
