// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ve_journal_book"] = {
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
			"fieldname": "from_date",
			"label": __("Desde"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_start(),
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("Hasta"),
			"fieldtype": "Date",
			"default": frappe.datetime.month_end(),
			"reqd": 1
		},
		{
			"fieldname": "currency_filter",
			"label": __("Moneda"),
			"fieldtype": "Select",
			"options": "VES\nUSD\nBimoneda",
			"default": "VES",
			"reqd": 1
		},
		{
			"fieldname": "presentation",
			"label": __("Presentación / Nivel"),
			"fieldtype": "Select",
			"options": "Detallado\nResumido\n1° Nivel\n2° Nivel\n3° Nivel\n4° Nivel",
			"default": "Detallado",
			"reqd": 1
		},
		{
			"fieldname": "voucher_type",
			"label": __("Tipo de Comprobante"),
			"fieldtype": "Select",
			"options": "Todos\nJournal Entry\nSales Invoice\nPurchase Invoice\nPayment Entry\nVE Sales Debit Note\nVE Sales Credit Note\nVE Purchase Debit Note\nVE Purchase Credit Note",
			"default": "Todos"
		},
		{
			"fieldname": "account",
			"label": __("Cuenta Contable"),
			"fieldtype": "Link",
			"options": "Account",
			"get_query": function () {
				let company = frappe.query_report.get_filter_value("company");
				return {
					filters: { "company": company }
				};
			}
		},
		{
			"fieldname": "party_type",
			"label": __("Tipo de Tercero"),
			"fieldtype": "Link",
			"options": "DocType",
			"get_query": function () {
				return {
					filters: {
						"name": ["in", ["Customer", "Supplier", "Employee"]]
					}
				};
			},
			"on_change": function () {
				frappe.query_report.set_filter_value("party", "");
			}
		},
		{
			"fieldname": "party",
			"label": __("Tercero"),
			"fieldtype": "Dynamic Link",
			"get_options": function () {
				return frappe.query_report.get_filter_value("party_type");
			}
		},
		{
			"fieldname": "cost_center",
			"label": __("Centro de Costo"),
			"fieldtype": "Link",
			"options": "Cost Center",
			"get_query": function () {
				let company = frappe.query_report.get_filter_value("company");
				return {
					filters: { "company": company, "is_group": 0 }
				};
			}
		},
		{
			"fieldname": "include_cancelled",
			"label": __("Incluir Anulados"),
			"fieldtype": "Check",
			"default": 0
		}
	],
	"onload": function (report) {
		report.page.add_inner_button(__("Exportar PDF (Legal / Folios)"), function () {
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
					orientation: "Landscape",
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

		if (data.is_spacer) {
			return `<div style="height: 4px; border-bottom: 1px dashed var(--border-color, rgba(255,255,255,0.15)); opacity: 0.5;"></div>`;
		}

		let formatted = default_formatter(value, row, column, data);

		// Subtotales de Comprobante
		if (data.is_voucher_total) {
			if (column.fieldname === "account") {
				let status_badge = data.is_balanced
					? `<span style="display: inline-block; padding: 1px 6px; font-size: 11px; font-weight: 600; border-radius: 10px; background-color: rgba(34, 197, 94, 0.2); color: #4ade80; margin-left: 8px;">✓ Cuadrado</span>`
					: `<span style="display: inline-block; padding: 1px 6px; font-size: 11px; font-weight: 600; border-radius: 10px; background-color: rgba(239, 68, 68, 0.2); color: #f87171; margin-left: 8px;">⚠️ Descuadre</span>`;
				return `<span style="font-weight: bold;">${formatted}</span> ${status_badge}`;
			}
			return `<span style="font-weight: bold;">${formatted}</span>`;
		}

		// Fila de Total General o de Grupo
		if (data.is_total || data.is_group_total || data.is_group_header) {
			return `<span style="font-weight: bold;">${formatted}</span>`;
		}

		// Indentación en modo jerárquico
		if (column.fieldname === "account" && data.indent) {
			let indent_px = data.indent * 14;
			return `<span style="padding-left: ${indent_px}px; display: inline-block;">${formatted}</span>`;
		}

		return formatted;
	}
};
