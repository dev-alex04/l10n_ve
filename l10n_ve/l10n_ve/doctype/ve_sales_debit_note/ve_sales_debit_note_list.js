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
        if (doc.is_void) {
            return [__("Anulado"), "red", "is_void,=,1"];
        }
        if (doc.docstatus === 1 && doc.status === "Paid") {
            return [__("Pago"), "green", "status,=,Paid"];
        }
        if (doc.docstatus === 1 && doc.status === "Overdue") {
            return [__("Vencido"), "red", "status,=,Overdue"];
        }
        if (doc.bill_no && doc.docstatus === 1) {
            return [__("Emitida"), "blue", "bill_no,!=,"];
        }
        const status_colors = {
            Draft: "red",
            Submitted: "blue",
            Cancelled: "red",
        };
        return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
    },
    right_column: "grand_total",
};
