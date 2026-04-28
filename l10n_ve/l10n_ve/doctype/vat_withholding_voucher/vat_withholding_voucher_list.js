frappe.listview_settings["VAT Withholding Voucher"] = {
  hide_name_column: true,
  has_indicator_for_draft: true,
  has_indicator_for_cancelled: true,

  add_fields: [
    "voucher_number",
    "supplier",
    "fiscal_period",
    "digital_invoice_status",
    "bill_control",
    "is_declared",
    "totals_tax_amount_vat",
  ],

  get_indicator(doc) {
    // Cancelados
    if (doc.docstatus === 2) {
      if (doc.digital_invoice_status === "Voided") {
        return [__("Anulado"), "red", "digital_invoice_status,=,Voided"];
      }
      return [__("Cancelado"), "red", "docstatus,=,2"];
    }

    // Borradores
    if (doc.docstatus === 0) {
      return [__("Borrador"), "grey", "docstatus,=,0"];
    }

    // Aprobados (docstatus === 1)
    if (doc.digital_invoice_status === "Sent") {
      if (doc.is_declared) {
        return [__("Declarado"), "blue", "is_declared,=,1"];
      }
      return [__("Emitido"), "green", "digital_invoice_status,=,Sent"];
    }

    if (doc.digital_invoice_status === "Error") {
      return [__("Error"), "red", "digital_invoice_status,=,Error"];
    }

    if (doc.digital_invoice_status === "Pending") {
      return [
        __("Pendiente"),
        "orange",
        "digital_invoice_status,=,Pending",
      ];
    }

    // Aprobado sin estado HKA (no emitido aún)
    return [__("Por Emitir"), "orange", "docstatus,=,1"];
  },

  onload(listview) {
    const get_df = frappe.meta.get_docfield.bind(
      null,
      "VAT Withholding Voucher",
    );
    listview.columns = [
      {
        type: "Subject",
        df: get_df("voucher_number") || {
          label: __("No. Comprobante"),
          fieldname: "voucher_number",
        },
      },
      { type: "Status" },
      {
        type: "Field",
        df: get_df("supplier") || {
          label: __("Proveedor"),
          fieldname: "supplier",
        },
      },
      {
        type: "Field",
        df: get_df("fiscal_period") || {
          label: __("Período Fiscal"),
          fieldname: "fiscal_period",
        },
      },
      {
        type: "Field",
        df: get_df("bill_control") || {
          label: __("N° Control"),
          fieldname: "bill_control",
        },
      },
    ];
    listview.render_header(true);
  },
};
