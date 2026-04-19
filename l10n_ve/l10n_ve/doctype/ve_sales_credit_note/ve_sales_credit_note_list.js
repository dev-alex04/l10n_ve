// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["VE Sales Credit Note"] = {
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
    if (doc.docstatus === 1 && doc.bill_no) {
      return [__("Emitida"), "blue", "bill_no,!=,"];
    }
    if (doc.docstatus === 1 && flt(doc.outstanding_amount) === 0) {
      return [__("Aplicada"), "green", "outstanding_amount,=,0"];
    }
    if (doc.docstatus === 1) {
      return [__("Pendiente"), "orange", "docstatus,=,1"];
    }
    const status_colors = {
      Draft: "red",
      Cancelled: "red",
    };
    return [
      __(doc.status),
      status_colors[doc.status] || "gray",
      "status,=," + doc.status,
    ];
  },
  right_column: "grand_total",
};

