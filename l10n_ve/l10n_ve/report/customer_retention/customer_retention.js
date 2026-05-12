// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["Customer Retention"] = {
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
		},
		{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
		},
		{
			"fieldname": "branch",
			"label": __("Sucursal"),
			"fieldtype": "Link",
			"options": "VE Branch",
			"get_query": () => {
				return {
					filters: { company: frappe.query_report.get_filter_value("company") }
				};
			}
		},
		{
			"fieldname": "customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
		},
		{
			"fieldname": "retention_type",
			"label": __("Tipo de Retención"),
			"fieldtype": "Select",
			"options": ["", "IVA", "ISLR"],
			"default": ""
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

		report.page.add_inner_button(__("Exportar Excel"), function() {
			var filters = report.get_values();
			if(filters) {
				window.open('/api/method/l10n_ve.l10n_ve.report.customer_retention.customer_retention_impression.get_customer_retention_excel?filters=' + encodeURIComponent(JSON.stringify(filters)));
			} else {
				frappe.msgprint(__("Por favor genere el reporte primero."));
			}
		});

		report.page.add_inner_button(__("Exportar PDF"), function() {
			var filters = report.get_values();
			if(filters) {
				window.open('/api/method/l10n_ve.l10n_ve.report.customer_retention.customer_retention_impression.get_customer_retention_pdf?filters=' + encodeURIComponent(JSON.stringify(filters)));
			} else {
				frappe.msgprint(__("Por favor genere el reporte primero."));
			}
		});
	},
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "bill_no" && data && data.name && data.doctype) {
			const final_link = `/app/${data.doctype.toLowerCase().replace(/ /g, "-")}/${data.name}`;
			value = `<a href="${final_link}" style="font-weight: bold; color: var(--primary-color); text-decoration: none;">${value}</a>`;
		}

		return value;
	}
};
