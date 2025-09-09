frappe.query_reports["Sales book"] = {
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
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.now_date(), -1)
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.now_date()
        }
    ],

   
    "onload": function(report) {
        // Añade el botón "Excel" al menú de la página
        report.page.add_inner_button(__("Excel"), function() {
            const filters = report.get_filter_values();
            
            if (!filters.company) {
                frappe.throw(__("Por favor, selecciona una Compañía para generar el reporte."));
                return;
            }
            
            // Llama a la función de Python para la exportación y maneja la descarga
            frappe.call({
                method: "l10n_ve.l10n_ve.report.sales_book.excel_builder.create_excel_file",
                args: { report_name: "Sales book", filters: JSON.stringify(filters) },
                callback: function(r) {
                    if (r.message) {
                        // El servidor ha devuelto la URL del archivo, abrimos la descarga
                        window.open(r.message);
                        frappe.show_alert({
                            message: __('Reporte Excel generado correctamente.'),
                            indicator: 'green'
                        });
                    } else {
                        // Si por alguna razón no hay URL, mostramos un error
                        frappe.throw(__("No se pudo generar el archivo de Excel."));
                    }
                },
                error: function(r) {
                    frappe.throw(__("Ocurrió un error al generar el archivo. Por favor, revisa el Log de Errores."));
                }
            });
        });
    }
};
