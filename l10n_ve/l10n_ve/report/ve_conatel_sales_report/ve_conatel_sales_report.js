// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["VE Conatel Sales Report"] = {
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
		},
		{
			"fieldname": "branch",
			"label": __("Branch"),
			"fieldtype": "Link",
			"options": "VE Branch"
		},
		{
			"fieldname": "cost_center",
			"label": __("Cost Center"),
			"fieldtype": "Link",
			"options": "Cost Center",
			"get_query": function() {
				var company = frappe.query_report.get_filter_value('company');
				return {
					filters: {
						'company': company,
						'is_group': 0
					}
				};
			}
		},
		{
			"fieldname": "customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer"
		}
	],
	"onload": function(report) {
		report.page.add_inner_button(__("Declaración de CONATEL"), function() {
			var company = report.get_filter_value('company');
			var from_date = report.get_filter_value('from_date');
			var to_date = report.get_filter_value('to_date');
			var branch = report.get_filter_value('branch');

			// Redirigir a la lista de declaraciones filtrada si es posible, o abrir una nueva con valores por defecto
			frappe.set_route("List", "VE Conatel Tax Declaration", {
				company: company,
				from_date: from_date,
				to_date: to_date,
				branch: branch
			});
		});
	}
};
