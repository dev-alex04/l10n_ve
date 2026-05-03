frappe.listview_settings["Purchase Invoice"] = {
  has_indicator_for_cancelled: true,
  hide_name_column: true,
  add_fields: [
    "supplier",
    "supplier_name",
    "base_grand_total",
    "outstanding_amount",
    "due_date",
    "company",
    "currency",
    "is_return",
    "is_debit_note",
    "bill_no",
  ],

  get_indicator: function (doc) {
    // ── Cancelado ──
    if (doc.docstatus === 2) {
      return [__("Cancelado"), "red", "docstatus,=,2"];
    }

    // ── Borrador ──
    if (doc.docstatus === 0) {
      return [__("Borrador"), "red", "docstatus,=,0"];
    }

    // ── NC / ND internas (is_return / is_debit_note en Purchase Invoice) ──
    if (doc.is_return) {
      return [__("Nota de Crédito"), "gray", "is_return,=,1"];
    }
    if (doc.is_debit_note) {
      return [__("Nota de Débito"), "gray", "is_debit_note,=,1"];
    }

    // ── docstatus === 1: indicador por status ──
    const status = doc.status || "";

    if (status === "Paid") {
      return [__("Pago"), "green", "status,=,Paid"];
    }

    if (status === "Credit Note Issued") {
      return [__("NC Aplicada"), "gray", "status,=,Credit Note Issued"];
    }

    if (status === "Debit Note Issued") {
      return [__("ND Aplicada"), "gray", "status,=,Debit Note Issued"];
    }

    if (status === "Partly Paid") {
      return [__("Pago Parcial"), "yellow", "status,=,Partly Paid"];
    }

    if (status === "Overdue") {
      return [__("Atrasado"), "red", "status,=,Overdue"];
    }

    if (status === "Unpaid") {
      return [__("Por Pagar"), "orange", "status,=,Unpaid"];
    }

    if (status === "Internal Transfer") {
      return [__("Transferencia Interna"), "darkgrey", "status,=,Internal Transfer"];
    }

    // Fallback
    return [__(status), "orange"];
  },

  right_column: "grand_total",

  onload: function (listview) {
    if (frappe.model.can_create("Purchase Receipt")) {
      listview.page.add_action_item(__("Purchase Receipt"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Purchase Invoice",
          "Purchase Receipt"
        );
      });
    }

    if (frappe.model.can_create("Payment Entry")) {
      listview.page.add_action_item(__("Payment"), () => {
        erpnext.bulk_transaction_processing.create(
          listview,
          "Purchase Invoice",
          "Payment Entry"
        );
      });
    }

    // Columnas personalizadas: bill_no como Subject, supplier_name, status
    const get_df = frappe.meta.get_docfield.bind(null, "Purchase Invoice");
    listview.columns = [
      { type: "Subject", df: get_df("bill_no") || { label: __("Factura de proveedor No."), fieldname: "bill_no" } },
      { type: "Tag" },
      { type: "Status" },
      { type: "Field", df: get_df("supplier_name") || { label: __("Proveedor"), fieldname: "supplier_name" } },
      { type: "Field", df: get_df("posting_date") || { label: __("Fecha de Contabilización"), fieldname: "posting_date" } },
    ];
    listview.render_header(true);
  },
};