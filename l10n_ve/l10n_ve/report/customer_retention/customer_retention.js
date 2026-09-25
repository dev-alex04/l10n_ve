// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

function _load_company_info(report) {
	const company = report && report.get_filter_value && report.get_filter_value("company");
	if (!company) {
		if (report) report.company_info = null;
		return;
	}
	frappe.db.get_value("Company", company, ["company_logo", "tax_id"]).then((r) => {
		report.company_info = (r && r.message) || {};
	});
}

frappe.query_reports["Customer Retention"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1,
			"on_change": () => _load_company_info(frappe.query_report)
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
			"fieldtype": "MultiSelectList",
			"get_data": function(txt) {
				return frappe.db.get_link_options("VE Branch", txt, {
					company: frappe.query_report.get_filter_value("company")
				});
			}
		},
		{
			"fieldname": "exclude_branches",
			"label": __("Excluir sucursales"),
			"fieldtype": "Check",
			"default": 0
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
			"options": ["", "IVA", "ISLR", "Gubernamental"],
			"default": ""
		},
		{
			"fieldname": "include_credit_notes",
			"label": __("Incluir Notas de Crédito"),
			"fieldtype": "Check",
			"default": 1
		}
	],
	"onload": function(report) {
		_load_company_info(report);

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

		if (column.fieldname === "doc_type" && data) {
			if (data.doc_type === "NC") {
				value = `<span class="indicator-pill orange" style="font-weight: bold;">NC</span>`;
			} else if (data.doc_type === "ND") {
				value = `<span class="indicator-pill blue" style="font-weight: bold;">ND</span>`;
			} else if (data.doc_type === "ANU") {
				value = `<span class="indicator-pill red" style="font-weight: bold;">ANU</span>`;
			} else {
				value = `<span class="indicator-pill green">FAC</span>`;
			}
		}

		if (column.fieldname === "withholding_amount" && data && data.withholding_amount < 0) {
			value = `<span style="color: var(--text-color-danger, #e24c4c); font-weight: bold;">${value}</span>`;
		}

		if (column.fieldname === "withholding_amount_usd" && data && data.withholding_amount_usd < 0) {
			value = `<span style="color: var(--text-color-danger, #e24c4c); font-weight: bold;">${value}</span>`;
		}

		return value;
	}
};
