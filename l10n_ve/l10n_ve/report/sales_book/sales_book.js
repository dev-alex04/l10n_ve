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
        report.page.add_inner_button(__("Exportar Excel"), function() {
            frappe.dom.freeze();

            const filters = report.get_filter_values();
           
            if (!filters.company) {
                frappe.dom.unfreeze();
                frappe.throw(__("Por favor, selecciona una Compañía para generar el reporte."));
                return;
            }
           
            // Llama a la función de Python para la exportación y maneja la descarga
            frappe.call({
                method: "l10n_ve.l10n_ve.report.sales_book.excel_builder.create_excel_file",
                args: { report_name: "Sales book", filters: JSON.stringify(filters) },
                callback: function(r) {
                    frappe.dom.unfreeze();
                    if (r.message && r.message.type === 'download') {
                        const filename = r.message.filename;
                        const filecontent = r.message.filecontent;

                        const byteCharacters = atob(filecontent);
                        const byteNumbers = new Array(byteCharacters.length);
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteNumbers[i] = byteCharacters.charCodeAt(i);
                        }
                        const byteArray = new Uint8Array(byteNumbers);
                        const blob = new Blob([byteArray], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        a.download = filename;
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);

                        frappe.show_alert({
                            message: __('Reporte Excel generado y descargado correctamente.'),
                            indicator: 'green'
                        });
                    } else if (r.message) {
                        frappe.throw(__("No se pudo generar el archivo de Excel."));
                    } else {
                        frappe.throw(__("Respuesta inesperada del servidor."));
                    }
                },
                error: function(r) {
                    frappe.dom.unfreeze();
                    frappe.throw(__("Ocurrió un error al generar el archivo. Por favor, revisa el Log de Errores."));
                }
            });
        });
    }

};
