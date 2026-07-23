// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["VE Purchase Debit Note"] = {
    has_indicator_for_cancelled: true,
    add_fields: [
        "supplier",
        "supplier_name",
        "grand_total",
        "outstanding_amount",
        "return_against",
        "bill_no",
        "company",
        "currency",
    ],
    get_indicator: function (doc) {
        if (doc.docstatus === 2) {
            return [__("Cancelled"), "red", "docstatus,=,2"];
        }
        if (doc.docstatus === 0) {
            return [__("Draft"), "red", "docstatus,=,0"];
        }

        // Submitted
        const outstanding = flt(doc.outstanding_amount);
        if (outstanding <= 0) {
            return [__("Paid"), "green", "docstatus,=,1"];
        }
        if (outstanding < flt(doc.grand_total)) {
            return [__("Partly Paid"), "orange", "docstatus,=,1"];
        }
        return [__("Unpaid"), "orange", "docstatus,=,1"];
    },
    right_column: "grand_total",
};
