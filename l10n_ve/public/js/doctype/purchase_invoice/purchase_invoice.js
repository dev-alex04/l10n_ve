frappe.ui.form.on("Purchase Invoice", {
  onload: function (frm) {
    toggle_purchase_type_fields(frm);
  },
  refresh: function (frm) {
    set_purchase_invoice_buttons(frm);
    toggle_purchase_type_fields(frm);
  },

  is_debit_note: function (frm) {
    if (frm.doc.is_debit_note) {
      frm.set_value("is_return", 0);
    }
    toggle_purchase_type_fields(frm);
  },
  is_return: function (frm) {
    if (frm.doc.is_return) {
      frm.set_value("is_debit_note", 0);
    }
    toggle_purchase_type_fields(frm);
  },
});

function set_purchase_invoice_buttons(frm) {
  if (frm.doc.docstatus == 0) {
    frm.add_custom_button(__("Agregar concepto de ISLR"), function () {
      set_islr_concept(frm);
    });
  }
}

function toggle_purchase_type_fields(frm) {
  const is_debit_note = frm.doc.is_debit_note;
  const is_return = frm.doc.is_return;

  if (frm.is_new() || (!is_debit_note && !is_return)) {
    frm.toggle_display(["bill_no"], !is_debit_note && !is_return);
    frm.toggle_display(
      ["debit_note_no", "credit_note_no", "affected_invoice_number"],
      false
    );

    if (is_debit_note) {
      frm.toggle_display(
        ["debit_note_no", "affected_invoice_number"],
        is_debit_note
      );
      frm.set_value("bill_no", "");
      frm.set_value("bill_control", "");
      frm.set_value("credit_note_no", "");
    }

    if (is_return) {
      frm.toggle_display(
        ["credit_note_no", "affected_invoice_number"],
        is_return
      );
      frm.set_value("bill_no", "");
      frm.set_value("bill_control", "");
      frm.set_value("debit_note_no", "");
    }

    frm.toggle_display("is_return", !is_debit_note);
    frm.toggle_display("is_debit_note", !is_return);
  } else {
    if (is_return) {
      frm.toggle_display(["credit_note_no"], is_return);
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
