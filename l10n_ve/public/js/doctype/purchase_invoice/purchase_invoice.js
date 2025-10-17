frappe.ui.form.on("Purchase Invoice", {
  onload: function (frm) {
    if (frm.is_new() && (frm.doc.is_return || frm.doc.is_debit_note)) {
      frm.set_value("bill_control", "");
    }

    toggle_purchase_type_fields(frm);

    const return_against_field = "return_against";
    if (frm.get_docfield(return_against_field).label !== "Factura Afectada") {
      frm.set_df_property(return_against_field, "label", "Factura Afectada");
    }
  },
  refresh: function (frm) {
    toggle_purchase_type_fields(frm);
  },

  is_debit_note: function (frm) {
    if (frm.doc.is_debit_note) {
      frm.set_value("is_return", 0);
      frm.set_value("bill_control", "");
    }
    toggle_purchase_type_fields(frm);
  },

  is_return: function (frm) {
    if (frm.doc.is_return) {
      frm.set_value("is_debit_note", 0);
      frm.set_value("bill_control", "");
    }
    toggle_purchase_type_fields(frm);
  },
});

function toggle_purchase_type_fields(frm) {
  const is_debit_note = frm.doc.is_debit_note;
  const is_return = frm.doc.is_return;

  // Establecer la obligatoriedad de los campos según el tipo de documento
  frm.toggle_reqd("bill_no", !is_debit_note && !is_return);
  frm.toggle_reqd("credit_note_no", is_return);
  frm.toggle_reqd("debit_note_no", is_debit_note);

  if (frm.is_new() || (!is_debit_note && !is_return)) {
    frm.toggle_display(["bill_no"], !is_debit_note && !is_return);
    frm.toggle_display(
      [
        "debit_note_no",
        "credit_note_no",
        "affected_invoice_number",
        "return_against",
      ],
      false
    );

    if (is_debit_note) {
      frm.toggle_display(
        ["debit_note_no", "affected_invoice_number", "return_against"],
        is_debit_note
      );
      frm.set_value("bill_no", "");
      frm.set_value("credit_note_no", "");
    } else if (is_return) {
      frm.toggle_display(
        ["credit_note_no", "affected_invoice_number", "return_against"],
        is_return
      );
      frm.set_value("bill_no", "");
      frm.set_value("debit_note_no", "");
    }
  } else {
    if (is_return) {
      frm.toggle_display(["debit_note_no", "bill_no", "is_debit_note"], false);
      frm.toggle_display(
        ["credit_note_no", "affected_invoice_number", "return_against"],
        is_return
      );
      frm.set_value("bill_no", "");
    } else if (is_debit_note) {
      frm.toggle_display(["credit_note_no", "bill_no", "is_return"], false);
      frm.toggle_display(
        ["debit_note_no", "affected_invoice_number", "return_against"],
        is_debit_note
      );
      frm.set_value("bill_no", "");
    }
  }
}

frappe.ui.form.on("Purchase Invoice Item", {
  item_code: function (frm, cdt, cdn) {
    var row = frappe.get_doc(cdt, cdn);

    if (row.item_code && !row.vat_exempt) {
      frappe.db.get_value(
        "Item",
        row.item_code,
        "vat_exempt",
        function (value) {
          if (value.vat_exempt) {
            frappe.model.set_value(cdt, cdn, "vat_exempt", 1);
          }
        }
      );
    }
  },
});
