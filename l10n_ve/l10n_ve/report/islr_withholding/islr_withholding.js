// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["ISLR Withholding"] = {
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
			"fieldname": "supplier",
			"label": __("Supplier"),
			"fieldtype": "Link",
			"options": "Supplier",
			"default": "",
			"reqd": 0
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
		},
		{
			"fieldname": "group_by",
			"label": __("Agrupar Por"),
			"fieldtype": "Select",
			"options": ["Detalle", "Por Proveedor", "Por Concepto"],
			"default": "Detalle",
			"reqd": 1
		}
	],
	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname == "parent" && value && data && data.parent) {
			value = `
                <button class="btn btn-xs btn-default" 
                    onclick="frappe.set_route('Form', 'ISLR Withholding Voucher', '${data.parent}')"
                    style="font-weight: 500; cursor: pointer; color: #525252;">
                    <i class="fa fa-external-link" style="margin-right: 5px;"></i> ${__("Ir al Comprobante")}
                </button>
            `;
		}

		if (column.fieldname == "declared_status" && data) {
			let color = data.is_declared ? "green" : "red";
			value = `<span class="indicator-pill ${color}" style="display: inline-flex; align-items: center;">
                        ${__(value)}
                     </span>`;
		}

		if (column.fieldname == "status" && data) {
			let color = "blue";
			if (data.status === "Aprobado") color = "green";
			else if (data.status === "Cancelado") color = "red";
			else if (data.status === "Borrador") color = "gray";
			value = `<span class="indicator-pill ${color}" style="display: inline-flex; align-items: center;">
                        ${__(value)}
                     </span>`;
		}

		return value;
	},
	"onload": function (report) {
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

		add_download_button("Descargar Excel", "l10n_ve.l10n_ve.report.islr_withholding.islr_withholding_impression.download_custom_excel");
		add_download_button("Descargar PDF", "l10n_ve.l10n_ve.report.islr_withholding.islr_withholding_impression.download_custom_pdf");
	}
};
