// Override del reporte Libro Mayor General
// Traduce las opciones de "Categorize by" al español
// Este archivo carga después del general_ledger.js de ERPNext, por lo que
// frappe.query_reports["General Ledger"] ya está definido en este punto.

(function () {
    const define_report_override = (report) => {
        if (!report) return;

        if (report.filters) {
            for (const filter of report.filters) {
                if (filter.fieldname === "categorize_by") {
                    filter.label = __("Categorizar por");
                    filter.options = [
                        "",
                        {
                            label: __("Por Comprobante"),
                            value: "Categorize by Voucher",
                        },
                        {
                            label: __("Por Comprobante (Consolidado)"),
                            value: "Categorize by Voucher (Consolidated)",
                        },
                        {
                            label: __("Por Cuenta"),
                            value: "Categorize by Account",
                        },
                        {
                            label: __("Por Tercero"),
                            value: "Categorize by Party",
                        },
                    ];
                    filter.default = "Categorize by Voucher (Consolidated)";
                }
                if (filter.fieldname === "show_remarks") {
                    filter.label = __("Mostrar Descripción");
                    filter.default = 1;
                }
            }

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

            const has_bill_filter = report.filters.some(f => f.fieldname === "only_invoices_with_bill_no_control");
            if (!has_bill_filter) {
                const company_idx = report.filters.findIndex(f => f.fieldname === "company");
                const insert_idx = company_idx !== -1 ? company_idx + 1 : report.filters.length;
                report.filters.splice(insert_idx, 0, {
                    fieldname: "only_invoices_with_bill_no_control",
                    label: __("Solo facturas con N° de control y factura"),
                    fieldtype: "Check",
                    default: 0,
                });
            }
        }
    };

    let report = frappe.query_reports["General Ledger"];
    if (report) {
        define_report_override(report);
    } else {
        let current_val = undefined;
        Object.defineProperty(frappe.query_reports, "General Ledger", {
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

    // Global prototype override to ensure translation of voucher_type cell values
    if (frappe.views && frappe.views.QueryReport) {
        const original_prepare_columns = frappe.views.QueryReport.prototype.prepare_columns;
        frappe.views.QueryReport.prototype.prepare_columns = function (columns) {
            const cols = original_prepare_columns.call(this, columns);
            
            if (this.report_name === "General Ledger" && cols) {
                const translation_map = {
                    "Sales Invoice": "Factura de venta",
                    "Purchase Invoice": "Factura de compra",
                    "Payment Entry": "Registro de pago",
                    "Journal Entry": "Asiento de diario",
                    "VE Sales Credit Note": "Nota de crédito de venta",
                    "VE Sales Debit Note": "Nota de débito de venta",
                    "VE Purchase Credit Note": "Nota de crédito de compra",
                    "VE Purchase Debit Note": "Nota de débito de compra"
                };

                cols.forEach((col) => {
                    const fieldname = col.fieldname || col.id || col.field;
                    if (fieldname === "voucher_type") {
                        const original_format = col.format;
                        col.format = function (value, row, column, data, filter) {
                            let val = original_format ? original_format(value, row, column, data, filter) : value;
                            const raw_val = data ? data[fieldname] : null;
                            if (raw_val) {
                                const translated = translation_map[raw_val] || __(raw_val);
                                if (translated !== raw_val) {
                                    if (typeof val === "string" && val.includes("<a")) {
                                        return val.replace(">" + raw_val + "<", ">" + translated + "<");
                                    }
                                    return translated;
                                }
                            }
                            return val;
                        };
                    }
                });
            }
            
            return cols;
        };
    }
})();

