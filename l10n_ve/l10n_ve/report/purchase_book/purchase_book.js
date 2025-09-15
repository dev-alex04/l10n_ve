// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.query_reports["purchase_book"] = {
    "filters": [
        {
            "fieldname": "company",
            "fieldtype": "Link",
            "label": "Company",
            "options": "Company",
            "reqd": 1,
            "default": frappe.defaults.get_user_default("Company")
        },
        {
            "fieldname": "date_from",
            "fieldtype": "Date",
            "label": "Fecha Inicio",
            "default": frappe.datetime.get_today()
        },
        {
            "fieldname": "to_date",
            "fieldtype": "Date",
            "label": "Fecha Fin",
            "default": frappe.datetime.get_today()
        }
    ],

    "onload": function(report) {
        // Añade el botón "Excel" al menú de la página
        report.page.add_inner_button(__("Exportar a Excel"), function() {
            const filters = report.get_filter_values();
            
            if (!filters.company) {
                frappe.throw(__("Por favor, selecciona una Compañía para generar el reporte."));
                return;
            }
            
            // Llama a la función de Python para la exportación y maneja la descarga
            frappe.call({
                method: "l10n_ve.l10n_ve.report.purchase_book.excel_builder.create_excel_file",
                args: { report_name: "Libro de Compra", filters: JSON.stringify(filters) },
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

        // Botón para generar el archivo XML de Retenciones de ISLR
        report.page.add_inner_button(__("Generar XML ISLR"), function() {
            const filters = report.get_filter_values();
            
            if (!filters.company) {
                frappe.throw(__("Por favor, selecciona una Compañía para generar el XML."));
                return;
            }

            // Llama a la función de Python que devuelve la cadena XML
            frappe.call({
                method: "l10n_ve.l10n_ve.report.purchase_book.purchase_book.generate_xml_islr_file",
                args: { filters: JSON.stringify(filters) },
                callback: function(r) {
                    if (r.message) {
                        // El servidor devolvió el XML como una cadena.
                        const xmlString = r.message;
                        const blob = new Blob([xmlString], { type: 'text/xml' });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = 'retenciones_islr.xml';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    } else {
                        frappe.msgprint(__("No se encontraron datos de retención de ISLR para los filtros seleccionados."));
                    }
                },
                error: function(r) {
                    frappe.throw(__("Ocurrió un error al generar el archivo XML. Por favor, revisa el Log de Errores."));
                }
            });
        });
    }
};