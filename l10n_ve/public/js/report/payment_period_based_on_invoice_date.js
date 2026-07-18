(function () {
    const define_report_override = (report) => {
        if (!report) return;

        if (report.filters) {
            const has_ve_branch = report.filters.some(f => f.fieldname === "ve_branch");
            if (!has_ve_branch) {
                const company_idx = report.filters.findIndex(f => f.fieldname === "company");
                const insert_idx = company_idx !== -1 ? company_idx + 1 : report.filters.length;
                report.filters.splice(insert_idx, 0, {
                    fieldname: "ve_branch",
                    label: __("Sucursal VE"),
                    fieldtype: "Link",
                    options: "VE Branch",
                });
            }

            const has_presentation_currency = report.filters.some(f => f.fieldname === "presentation_currency");
            if (!has_presentation_currency) {
                const branch_idx = report.filters.findIndex(f => f.fieldname === "ve_branch");
                const insert_idx = branch_idx !== -1 ? branch_idx + 1 : report.filters.length;
                report.filters.splice(insert_idx, 0, {
                    fieldname: "presentation_currency",
                    label: __("Ver en Moneda"),
                    fieldtype: "Select",
                    options: "VES\nUSD",
                    default: "VES",
                });
            }

            const has_range_filter = report.filters.some(f => f.fieldname === "aging_range");
            if (!has_range_filter) {
                const currency_idx = report.filters.findIndex(f => f.fieldname === "presentation_currency");
                const insert_idx = currency_idx !== -1 ? currency_idx + 1 : report.filters.length;
                report.filters.splice(insert_idx, 0, {
                    fieldname: "aging_range",
                    label: __("Rango de Antigüedad"),
                    fieldtype: "Select",
                    options: "\n0-30\n30-60\n60-90\nSuperior a 90",
                    default: "",
                });
            }
        }
    };

    let report = frappe.query_reports["Payment Period Based On Invoice Date"];
    if (report) {
        define_report_override(report);
    } else {
        let current_val = undefined;
        Object.defineProperty(frappe.query_reports, "Payment Period Based On Invoice Date", {
            get: function () {
                return current_val;
            },
            set: function (val) {
                current_val = val;
                define_report_override(current_val);
            },
            configurable: true,
            enumerable: true
        });
    }

    // Interceptar la preparación de columnas para cambiar la divisa de presentación en caliente
    if (frappe.views && frappe.views.QueryReport) {
        const original_prepare_columns = frappe.views.QueryReport.prototype.prepare_columns;
        frappe.views.QueryReport.prototype.prepare_columns = function (columns) {
            const cols = original_prepare_columns.call(this, columns);
            
            if (this.report_name === "Payment Period Based On Invoice Date" && cols) {
                const currency_filter = frappe.query_report.get_filter_value("presentation_currency");
                const target_currency = currency_filter === "USD" ? "USD" : "";
                
                cols.forEach((col) => {
                    if (col.fieldtype === "Currency") {
                        col.options = target_currency;
                    }
                });
            }
            
            return cols;
        };
    }

    // Interceptar el resolvedor de moneda de Frappe para devolver USD en las celdas.
    // get_field_currency es una función COMPARTIDA por todo el Desk, y frappe.query_report
    // conserva la última instancia aunque naveguemos fuera del reporte. Sin el guard de
    // ruta, tras ver este reporte en USD, cualquier campo Currency de otra vista (p.ej. un
    // formulario de Sales Invoice) se renderizaría en USD hasta recargar. Por eso limitamos
    // el override a cuando realmente estamos en la ruta de este query report.
    if (frappe.meta && frappe.meta.get_field_currency) {
        const original_get_field_currency = frappe.meta.get_field_currency;
        frappe.meta.get_field_currency = function (df, doc) {
            try {
                const route = (frappe.get_route && frappe.get_route()) || [];
                const on_this_report =
                    route[0] === "query-report" &&
                    route[1] === "Payment Period Based On Invoice Date";
                if (
                    on_this_report &&
                    df && df.fieldtype === "Currency" &&
                    frappe.query_report &&
                    frappe.query_report.report_name === "Payment Period Based On Invoice Date" &&
                    frappe.query_report.get_filter_value("presentation_currency") === "USD"
                ) {
                    return "USD";
                }
            } catch (e) {
                // Ante cualquier problema, caemos al comportamiento original de Frappe.
            }
            return original_get_field_currency.call(this, df, doc);
        };
    }
})();
