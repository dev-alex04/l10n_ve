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
        },
        {
            "fieldname": "fiscal_year",
            "fieldtype": "Link",
            "label": "Año Fiscal",
            "options": "Fiscal Year",
            "reqd": 0,
            "default": frappe.defaults.get_user_default("Fiscal Year")
        },
        {
            "fieldname": "fiscal_month",
            "fieldtype": "Select",
            "label": "Mes",
            "options": "\nEnero\nFebrero\nMarzo\nAbril\nMayo\nJunio\nJulio\
            nAgosto\nSeptiembre\nOctubre\nNoviembre\nDiciembre",
            "reqd": 0
        }
    ],

   "onload": function(report) {
        // Añade el botón "Excel"
        report.page.add_inner_button(__("Exportar a Excel"), function() {
            frappe.dom.freeze();

            const filters = report.get_filter_values();
           
            if (!filters.company) {
                frappe.dom.unfreeze();
                frappe.throw(__("Por favor, selecciona una Compañía para generar el reporte."));
                return;
            }
           
            frappe.call({
                method: "l10n_ve.l10n_ve.report.purchase_book.excel_builder.create_excel_file",
                args: { report_name: "Libro de Compra", filters: JSON.stringify(filters) },
                callback: function(r) {
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
                            message: __("Reporte Excel generado y descargado correctamente."),
                            indicator: 'green'
                        });
                    } else {
                        frappe.throw(__("No se pudo generar el archivo de Excel."));
                    }
                    frappe.dom.unfreeze();
                },
                error: function(r) {
                    frappe.dom.unfreeze();
                    frappe.throw(__("Ocurrió un error al generar el archivo. Por favor, revisa el Log de Errores."));
                }
            });
        });

        // Añade el botón para generar el archivo XML de Retenciones de ISLR
        report.page.add_inner_button(__("Generar XML ISLR"), function() {
            const filters = report.get_filter_values();

            if (!filters.company) {
                frappe.throw(__("Por favor, selecciona una Compañía para generar el XML."));
                return;
            }

            frappe.call({
                method: "l10n_ve.l10n_ve.report.purchase_book.purchase_book.generate_xml_islr_file",
                args: { filters: JSON.stringify(filters) },
                callback: function(r) {
                    if (r.message) {
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
                        frappe.show_alert({
                            message: __("Reporte XML ISLR generado correctamente "),
                            indicator: 'green'
                        });
                    } else {
                        frappe.msgprint(__("No se encontraron datos de retención de ISLR para los filtros seleccionados."));
                    }
                },
                error: function(r) {
                    frappe.throw(__("Ocurrió un error al generar el archivo XML. Por favor, revisa el Log de Errores."));
                }
            });
        });

        // Añade el botón "Descargar TXT"
        report.page.add_inner_button(__("Descargar TXT"), function() {
            // Deshabilitar la UI para evitar clics múltiples y mostrar carga
            frappe.dom.freeze();

            const filters = report.get_filter_values();
           
            frappe.call({
                method: "l10n_ve.l10n_ve.report.purchase_book.purchase_book.generate_txt_file",
                args: {
                    filters: JSON.stringify(filters)
                },
                callback: function(r) {
                    if (r.message && r.message.type === 'download') {
                        // Lógica para manejar la descarga directa de un archivo
                        const filename = r.message.filename;
                        const filecontent = r.message.filecontent;
                       
                        // Decodificar el contenido base64
                        const byteCharacters = atob(filecontent);
                        const byteNumbers = new Array(byteCharacters.length);
                        for (let i = 0; i < byteCharacters.length; i++) {
                            byteNumbers[i] = byteCharacters.charCodeAt(i);
                        }
                        const byteArray = new Uint8Array(byteNumbers);
                        const blob = new Blob([byteArray], { type: "text/plain;charset=utf-8" });
                       
                        // Crear un enlace temporal para la descarga
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
                            message: __("Archivo TXT generado y descargado con éxito."),
                            indicator: "green"
                        }, 5);

                    } else if (r.message && typeof r.message === 'string') {
                        // Lógica original para manejar una URL (si el servidor la devuelve)
                        const file_url = r.message;
                        if (file_url) {
                            window.open(file_url);
                        } else {
                            frappe.show_alert({
                                message: __("No se encontró el archivo."),
                                indicator: "red"
                            }, 5);
                        }
                    } else {
                        // Manejar cualquier otro tipo de respuesta inesperada
                        frappe.show_alert({
                            message: __("Ocurrió un error inesperado al generar el archivo."),
                            indicator: "red"
                        }, 5);
                    }
                    // Quitar el "freeze" de la UI
                    frappe.dom.unfreeze();
                },
                error: function(err) {
                    frappe.dom.unfreeze();
                    console.error("Error calling generate_txt_file:", err);
                    frappe.throw(__("Error al comunicarse con el servidor para generar el archivo."));
                }
            });
        });
    }
};