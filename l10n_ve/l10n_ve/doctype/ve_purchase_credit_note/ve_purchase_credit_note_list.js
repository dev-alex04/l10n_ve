// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["VE Purchase Credit Note"] = {
  has_indicator_for_cancelled: true,

  add_fields: [
    "supplier",
    "supplier_name",
    "grand_total",
    "return_against",
    "bill_no",
    "company",
    "currency",
  ],
  get_indicator: function (doc) {
    if (doc.docstatus === 1) {
      return [__("Aplicada"), "green", "docstatus,=,1"];
    }

    // Fallback: Draft / Cancelled (nativo)
    const status_colors = { Draft: "red", Cancelled: "red" };
    return [
      __(doc.status),
      status_colors[doc.status] || "gray",
      "status,=," + doc.status,
    ];
  },
  right_column: "grand_total",
};
