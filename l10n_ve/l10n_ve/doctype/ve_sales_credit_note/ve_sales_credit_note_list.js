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
    const result = compute_ve_billing_indicator(doc, {
      doc_type: "credit_note",
    });

    if (result) {
      let filter = "docstatus,=,1";
      if (doc.is_void) filter = "is_void,=,1";
      else if (doc.bill_no) filter = "bill_no,!=,";
      else if (flt(doc.outstanding_amount) === 0) filter = "outstanding_amount,=,0";
      return [result.label, result.color, filter];
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

