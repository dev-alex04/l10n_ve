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

        if (doc.docstatus !== 1) {
            const status_colors = {
                Draft: "red",
                Cancelled: "red",
            };
            return [__(doc.status), status_colors[doc.status] || "gray", "status,=," + doc.status];
        }

        // Estado fiscal
        let fiscal_label = doc.bill_no ? __("Emitida") : __("Aplicada");

        // Estado de pago
        let payment_label = "";
        let color = "orange";

        if (flt(doc.outstanding_amount) === 0) {
            payment_label = __("Pagado");
            color = "green";
        } else {
            payment_label = __("Por Cobrar");
            color = doc.bill_no ? "blue" : "orange";
        }

        return [`${fiscal_label} - ${payment_label}`, color, "docstatus,=,1"];
    },
    right_column: "grand_total",
};
