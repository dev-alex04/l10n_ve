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
        const result = compute_ve_billing_indicator(doc, {
            doc_type: "debit_note",
        });

        if (result) {
            const filter = doc.is_void ? "is_void,=,1" : "docstatus,=,1";
            return [result.label, result.color, filter];
        }

        // Fallback: Draft / Cancelled (nativo)
        const status_colors = { Draft: "red", Cancelled: "red" };
        return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
    },
    right_column: "grand_total",
};
