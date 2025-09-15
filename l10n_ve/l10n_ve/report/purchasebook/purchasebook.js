// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["purchasebook"] = {
    "filters": [
        {
            "fieldname": "company",
            "label": __("Company"),
            "fieldtype": "Link",
            "options": "Company",
            "reqd": 1,
            "default": frappe.defaults.get_user_default("Company")
        },
        {
            "fieldname": "fiscal_year",
            "label": __("Año Fiscal"),
            "fieldtype": "Int",
            "reqd": 1,
            "default": frappe.datetime.now_date().split("-")[0]
        },
        {
            "fieldname": "fiscal_month",
            "label": __("Mes Fiscal"),
            "fieldtype": "Int",
            "reqd": 1,
            "default": frappe.datetime.now_date().split("-")[1]
        }
    ],

	"onload": function(report) {
		// Añade el botón "Descargar TXT" al menú de la página
		report.page.add_inner_button(__("Descargar TXT"), function() {
			frappe.msgprint(__("Iniciando la generación del archivo TXT..."));
			const filters = frappe.query_report.get_filter_values();
			
			frappe.call({
				method: "l10n_ve.l10n_ve.report.purchasebook.purchasebook.generate_txt_file",
				args: {
					filters: JSON.stringify(filters)
				},
				callback: function(r) {
					if (r.message) {
						const file_url = r.message;
						const link = document.createElement('a');
						link.href = file_url;
						link.download = file_url.split('/').pop();
						document.body.appendChild(link);
						link.click();
						document.body.removeChild(link);
						frappe.msgprint(__("Archivo TXT generado con éxito. La descarga debería comenzar en breve."));
					} else {
						frappe.throw(__("Error al generar el archivo TXT."));
					}
				},
				error: function(err) {
					console.error("Error calling generate_txt_file:", err);
					frappe.throw(__("Error al comunicarse con el servidor para generar el archivo."));
				}
			});
		});
	}
};



