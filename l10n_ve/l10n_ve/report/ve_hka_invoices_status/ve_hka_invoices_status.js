// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["VE HKA Invoices Status"] = {
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
			"reqd": 0
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 0
		},
		{
			"fieldname": "document_type",
			"label": __("Tipo de Documento"),
			"fieldtype": "Select",
			"options": "All\nSales Invoice\nVE Sales Credit Note\nVE Sales Debit Note",
			"default": "All",
			"reqd": 0
		},
		{
			"fieldname": "status",
			"label": __("Estado HKA"),
			"fieldtype": "Select",
			"options": "All\nEmitida\nError\nPendiente",
			"default": "All",
			"reqd": 0
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

		// Delegación de eventos para el botón "Ver Error"
		report.page.main.off("click", ".btn-view-error").on("click", ".btn-view-error", function(e) {
			e.preventDefault();
			var error_msg = $(this).attr("data-error");
			var docname = $(this).attr("data-docname");
			
			frappe.msgprint({
				title: __("Detalle del Error HKA - {0}", [docname]),
				message: '<pre style="white-space: pre-wrap; word-break: break-all; background-color: var(--bg-light-gray, #f8f9fa); border: 1px solid var(--border-color, #e9ecef); color: var(--text-color, #212529); padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px;">' + frappe.utils.escape_html(error_msg) + '</pre>',
				wide: true
			});
		});
	},
	"formatter": function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "log_notes" && data && data.status === "Error" && value) {
			var escaped_value = frappe.utils.escape_html(value);
			return `<button class="btn btn-xs btn-default btn-view-error" data-docname="${data.name}" data-error="${escaped_value}"><i class="fa fa-exclamation-circle text-danger" style="margin-right: 5px;"></i> ${__("Ver Error")}</button>`;
		}

		return value;
	}
};
