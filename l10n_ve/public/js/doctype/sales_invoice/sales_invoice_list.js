// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

// render
frappe.listview_settings["Sales Invoice"] = {
  has_indicator_for_cancelled: true,
  add_fields: [
    "customer",
    "customer_name",
    "base_grand_total",
    "outstanding_amount",
    "due_date",
    "company",
    "currency",
    "is_return",
    "is_debit_note",
    "is_void",
  ],
  get_indicator: function (doc) {
    let status = "";
    let indicator = "blue";
    const status_colors = {
      Draft: "red",
      Unpaid: "orange",
      Paid: "green",
      Return: "gray",
      "Credit Note Issued": "gray",
      "Unpaid and Discounted": "orange",
      "Partly Paid and Discounted": "yellow",
      "Overdue and Discounted": "red",
      Overdue: "red",
      "Partly Paid": "yellow",
      "Internal Transfer": "darkgrey",
      Cancelled: "red",
    };
    status = __(doc.status);
    indicator = status_colors[doc.status];

    if (doc.is_debit_note) {
      status = "Nota de Debito";
      indicator = "gray";
    }
    if (doc.is_return) {
      status = "Nota de Credito";
      indicator = "gray";
    }

    if (doc.is_void) {
      status = "Anulado";
      indicator = "red";
    }

    return [status, indicator];
  },
  right_column: "grand_total",

  onload: function (listview) {
    if (frappe.model.can_create("Delivery Note")) {
      listview.page.add_action_item(__("Delivery Note"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Delivery Note"
        );
      });
    }

    if (frappe.model.can_create("Payment Entry")) {
      listview.page.add_action_item(__("Payment"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Payment Entry"
        );
      });
    }
  },
};
