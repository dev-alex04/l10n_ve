// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["VE Sales Credit Note"] = {
    add_fields: [
        "customer",
        "customer_name",
        "grand_total",
        "outstanding_amount",
        "return_against",
        "credit_note_no",
        "company",
        "currency",
    ],
    get_indicator: function (doc) {
        // NC ya emitida ante HKA → verde
        if (doc.credit_note_no) {
            return [__("Emitida"), "green", "credit_note_no,!=,"];
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
