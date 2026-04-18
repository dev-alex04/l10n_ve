// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["VE Sales Debit Note"] = {
    has_indicator_for_cancelled: true,
    add_fields: [
        "customer",
        "customer_name",
        "grand_total",
        "outstanding_amount",
        "return_against",
        "bill_no",
        "company",
        "currency",
        "is_void",
    ],
    get_indicator: function (doc) {
        // ND anulada ante HKA → rojo con etiqueta Anulado (tiene prioridad)
        if (doc.is_void) {
            return [__("Anulado"), "red", "is_void,=,1"];
        }
        // ND ya emitida ante HKA → verde
        if (doc.bill_no) {
            return [__("Emitida"), "green", "bill_no,!=,"];
        }
        const status_colors = {
            Draft: "red",
            Submitted: "blue",
            Return: "gray",
            Cancelled: "red",
        };
        return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
    },
    right_column: "grand_total",
};
