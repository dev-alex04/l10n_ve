frappe.ui.form.on("Purchase Invoice", {
  onload: function(frm) {
    toggle_purchase_type_fields(frm);

    const return_against_field = 'return_against';
    if (frm.get_docfield(return_against_field).label !== "Factura Afectada") {
      frm.set_df_property(return_against_field, 'label', "Factura Afectada");
    }
  },
  refresh: function(frm) {
    set_purchase_invoice_buttons(frm);
    toggle_return_against(frm);
    toggle_purchase_type_fields(frm);
  },

  is_debit_note: function(frm) {
    if (frm.doc.is_debit_note) {
      frm.set_value('is_return', 0);
    }
    toggle_return_against(frm);
    toggle_purchase_type_fields(frm);
  },
  is_return: function(frm) {
    if (frm.doc.is_return) {
      frm.set_value('is_debit_note', 0);
    }
    toggle_return_against(frm);
    toggle_purchase_type_fields(frm);
  }
});

function set_purchase_invoice_buttons(frm) {
  if (frm.doc.docstatus == 0) {
    frm.add_custom_button(__("Agregar concepto de ISLR"), function () {
      l10n_ve.controllers.taxes_and_totals.set_islr_concept(frm);
    });
  }
}

function toggle_return_against(frm) {
  const return_against_field = 'return_against';
  let should_show = frm.doc.is_return || frm.doc.is_debit_note;

  frm.toggle_display(return_against_field, should_show);

  if (!should_show) {
      frm.set_value(return_against_field, null);
  }

  frm.refresh_field(return_against_field);
}

function toggle_purchase_type_fields(frm) {
    const is_debit_note = frm.doc.is_debit_note;
    const is_return = frm.doc.is_return;

    if (frm.is_new() || (!is_debit_note && !is_return)) {
      frm.toggle_display(['bill_no'], !is_debit_note && !is_return);
      frm.toggle_display(['debit_note_no', 'credit_note_no', 'affected_invoice_number'], false);

      if (is_debit_note) {
        frm.toggle_display(['debit_note_no', 'affected_invoice_number'], is_debit_note);
        frm.set_value('bill_no', '');
        frm.set_value('bill_control', '');
        frm.set_value('credit_note_no', '');
      }

      if (is_return) {
        frm.toggle_display(['credit_note_no', 'affected_invoice_number'], is_return);
        frm.set_value('bill_no', '');
        frm.set_value('bill_control', '');
        frm.set_value('debit_note_no', '');
      }

      frm.toggle_display('is_return', !is_debit_note);
      frm.toggle_display('is_debit_note', !is_return);
    } else {
      if (is_return) {
        frm.toggle_display(['credit_note_no'], is_return);
      }
    }
}

frappe.ui.form.on('Purchase Invoice Item', {
    item_code: function(frm, cdt, cdn) {
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
    }
});