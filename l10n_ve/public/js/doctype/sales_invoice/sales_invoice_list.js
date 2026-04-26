// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.listview_settings["Sales Invoice"] = {
  has_indicator_for_cancelled: true,
  hide_name_column: true,
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
    "bill_no",
    "total_withholding",
    "vat_withholding_voucher_number",
  ],

  get_indicator: function (doc) {
    const result = compute_ve_billing_indicator(doc, {
      doc_type: "sales_invoice",
    });

    if (result) {
      let label = result.label;
      if (result.withholding_warning) label += " ⚠️";
      const filter = doc.is_void ? "is_void,=,1" : "docstatus,=,1";
      return [label, result.color, filter];
    }

    // Estados no-VE (compute retornó null)
    if (doc.docstatus === 2) {
      return [__("Cancelado"), "red", "docstatus,=,2"];
    }
    if (doc.docstatus === 0) {
      return [__("Borrador"), "red", "docstatus,=,0"];
    }
    if (doc.is_return) {
      return [__("Nota de Crédito"), "gray", "is_return,=,1"];
    }
    if (doc.is_debit_note) {
      return [__("Nota de Débito"), "gray", "is_debit_note,=,1"];
    }
  },

  right_column: "grand_total",

  onload: function (listview) {
    if (frappe.model.can_create("Delivery Note")) {
      listview.page.add_action_item(__("Delivery Note"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Delivery Note",
        );
      });
    }

    if (frappe.model.can_create("Payment Entry")) {
      listview.page.add_action_item(__("Payment"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Sales Invoice",
          "Payment Entry",
        );
      });
    }

    // Forzar columnas: Subject (bill_no), customer_name, bill_control, status
    const get_df = frappe.meta.get_docfield.bind(null, "Sales Invoice");
    listview.columns = [
      { type: "Subject", df: get_df("bill_no") || { label: __("Número de Factura"), fieldname: "bill_no" } },
      { type: "Tag" },
      { type: "Status" },
      { type: "Field", df: get_df("customer_name") || { label: __("Cliente"), fieldname: "customer_name" } },
      { type: "Field", df: get_df("bill_control") || { label: __("Número de Control"), fieldname: "bill_control" } },
    ];
    listview.render_header(true);

    // Tooltip para el ⚠️ de comprobante faltante
    const original_render = listview.render_list;
    listview.render_list = function () {
      original_render.call(this);
      this.$result
        .find(".indicator-pill")
        .filter(function () {
          return $(this).text().includes("⚠️");
        })
        .attr("title", "Falta comprobante de retención de IVA");
    };
  },
};
