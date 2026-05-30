frappe.ui.form.on("Journal Entry", {
    validate: function(frm) {
        var has_error = false;
        $.each(frm.doc.accounts || [], function(i, d) {
            if (flt(d.debit) > 0 && flt(d.credit) > 0) {
                frappe.msgprint(__("Fila {0}: No se permite registrar montos tanto en el Debe como en el Haber simultáneamente en la misma cuenta contable.", [d.idx]));
                has_error = true;
            }
        });
        if (has_error) {
            frappe.validated = false;
        }
    }
});

frappe.ui.form.on("Journal Entry Account", {
    debit_in_account_currency: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        if (flt(d.debit_in_account_currency) > 0) {
            frappe.model.set_value(cdt, cdn, "credit_in_account_currency", 0);
            frappe.model.set_value(cdt, cdn, "credit", 0);
        }
    },
    credit_in_account_currency: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        if (flt(d.credit_in_account_currency) > 0) {
            frappe.model.set_value(cdt, cdn, "debit_in_account_currency", 0);
            frappe.model.set_value(cdt, cdn, "debit", 0);
        }
    },
    debit: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        if (flt(d.debit) > 0) {
            frappe.model.set_value(cdt, cdn, "credit_in_account_currency", 0);
            frappe.model.set_value(cdt, cdn, "credit", 0);
        }
    },
    credit: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        if (flt(d.credit) > 0) {
            frappe.model.set_value(cdt, cdn, "debit_in_account_currency", 0);
            frappe.model.set_value(cdt, cdn, "debit", 0);
        }
    }
});
