// Override del reporte Accounts Receivable (Cuentas por Cobrar)
// Añade filtros "Desde" (from_date) y "Hasta" (to_date) ademas del
// filtro "Sucursal VE" (ve_branch). Este archivo se carga globalmente
// via app_include_js; si el reporte aun no esta definido (pagina no
// cargada todavia), intercepta la asignacion con Object.defineProperty.

(function () {
    const define_report_override = (report) => {
        if (!report || !report.filters) return;

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

        // Oculta el "Posting Date" estandar; usamos nuestro Desde/Hasta en su lugar.
        const report_date_idx = report.filters.findIndex(f => f.fieldname === "report_date");
        if (report_date_idx !== -1) {
            report.filters[report_date_idx].hidden = 1;
        }

        const has_from_date = report.filters.some(f => f.fieldname === "from_date");
        if (!has_from_date) {
            // Insertar Desde justo en el lugar del report_date oculto para que
            // quede junto a Hasta.
            const insert_idx = report_date_idx !== -1 ? report_date_idx : report.filters.length;
            report.filters.splice(insert_idx, 0, {
                fieldname: "from_date",
                label: __("Desde"),
                fieldtype: "Date",
                default: frappe.datetime.month_start(),
                placeholder: __("Desde"),
            });
        }

        const has_to_date = report.filters.some(f => f.fieldname === "to_date");
        if (!has_to_date) {
            // Hasta justo despues de Desde (y del report_date oculto).
            const from_date_idx = report.filters.findIndex(f => f.fieldname === "from_date");
            const insert_idx = from_date_idx !== -1 ? from_date_idx + 1 : report.filters.length;
            report.filters.splice(insert_idx, 0, {
                fieldname: "to_date",
                label: __("Hasta"),
                fieldtype: "Date",
                default: frappe.datetime.month_end(),
                placeholder: __("Hasta"),
            });
        }

        const has_withholding_filter = report.filters.some(f => f.fieldname === "withholding_voucher_status");
        if (!has_withholding_filter) {
            const to_date_idx = report.filters.findIndex(f => f.fieldname === "to_date");
            const insert_idx = to_date_idx !== -1 ? to_date_idx + 1 : report.filters.length;
            report.filters.splice(insert_idx, 0, {
                fieldname: "withholding_voucher_status",
                label: __("Comprobantes"),
                fieldtype: "Select",
                options: [
                    "",
                    "Con Comprobantes Pendientes",
                    "Pendiente IVA",
                    "Pendiente ISLR",
                    "Con Comprobantes Registrados",
                    "No aplica"
                ],
                default: "",
                ignore_permissions: 1,
            });
        }
    };

    const patch_query_report_prototype = () => {
        if (
            frappe.views &&
            frappe.views.QueryReport &&
            frappe.views.QueryReport.prototype &&
            typeof frappe.views.QueryReport.prototype.setup_filters === "function" &&
            !frappe.views.QueryReport._ar_ve_patched
        ) {
            const original_setup_filters = frappe.views.QueryReport.prototype.setup_filters;
            frappe.views.QueryReport.prototype.setup_filters = function () {
                if (this.report_name === "Accounts Receivable" && this.report_settings) {
                    define_report_override(this.report_settings);
                }
                return original_setup_filters.apply(this, arguments);
            };
            frappe.views.QueryReport._ar_ve_patched = true;
        }
    };

    let report = frappe.query_reports["Accounts Receivable"];
    if (report) {
        define_report_override(report);
    } else {
        let current_val = undefined;
        Object.defineProperty(frappe.query_reports, "Accounts Receivable", {
            get: function () {
                return current_val;
            },
            set: function (val) {
                current_val = val;
                define_report_override(current_val);
            },
            configurable: true,
            enumerable: true,
        });
    }

    // Parchear prototipo inmediatamente o al estar listo el desk
    patch_query_report_prototype();
    if (typeof $ !== "undefined" && $(document).on) {
        $(document).on("app_ready page-change", patch_query_report_prototype);
    }
})();
