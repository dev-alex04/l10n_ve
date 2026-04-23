frappe.query_reports["VAT report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Empresa"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1
		},
		{
			fieldname: "branch",
			label: __("Sucursal"),
			fieldtype: "Link",
			options: "VE Branch",
			get_query: () => {
				return {
					filters: { company: frappe.query_report.get_filter_value("company") }
				};
			}
		},
		{
			fieldname: "from_date",
			label: __("Desde"),
			fieldtype: "Date",
			default: frappe.datetime.month_start()
		},
		{
			fieldname: "to_date",
			label: __("Hasta"),
			fieldtype: "Date",
			default: frappe.datetime.month_end()
		},
		{
			fieldname: "fiscal_year",
			label: __("Año Fiscal (Opcional)"),
			fieldtype: "Select",
			options: ["", "2024", "2025", "2026", "2027"]
		},
		{
			fieldname: "fiscal_month",
			label: __("Mes Fiscal (Opcional)"),
			fieldtype: "Select",
			options: ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
		}
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "bill_no" && data && data.name && data.doctype_link) {
			const doc_link = frappe.utils.get_dev_mode() ?
				`/app/${data.doctype_link.toLowerCase().replace(/ /g, "-")}/${data.name}` :
				frappe.utils.get_form_link(data.doctype_link, data.name);

			// Si no estamos en modo dev, get_form_link suele ser más robusto
			const final_link = `/app/${data.doctype_link.toLowerCase().replace(/ /g, "-")}/${data.name}`;

			value = `<a href="${final_link}" style="font-weight: bold; color: var(--primary-color); text-decoration: none;">${value}</a>`;
		}

		return value;
	},
	onload: function (report) {
		const add_download_button = (label, method) => {
			report.page.add_inner_button(__(label), function () {
				const filters = report.get_values();
				window.open(
					frappe.urllib.get_full_url(
						`/api/method/${method}?filters=${encodeURIComponent(JSON.stringify(filters))}`
					)
				);
			});
		};

		add_download_button("Descargar Excel", "l10n_ve.l10n_ve.report.vat_report.vat_report_impression.download_custom_excel");
	}
};
