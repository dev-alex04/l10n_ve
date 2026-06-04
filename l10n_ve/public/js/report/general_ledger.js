// Override del reporte Libro Mayor General
// Traduce las opciones de "Categorize by" al español
// Este archivo carga después del general_ledger.js de ERPNext, por lo que
// frappe.query_reports["General Ledger"] ya está definido en este punto.

(function () {
    const report = frappe.query_reports["General Ledger"];
    if (!report || !report.filters) return;

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
})();

