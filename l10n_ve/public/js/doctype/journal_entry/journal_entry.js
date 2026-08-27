frappe.ui.form.on("Journal Entry", {
    validate: function(frm) {
        var errors = [];
        $.each(frm.doc.accounts || [], function(i, d) {
            if (flt(d.debit) > 0 && flt(d.credit) > 0) {
                errors.push("Fila " + d.idx + ": No se permite registrar montos tanto en el Debe como en el Haber simultáneamente en la misma cuenta contable.");
            }
        });
        if (errors.length > 0) {
            frappe.msgprint({
                title: "Error de Validación",
                indicator: "red",
                message: errors.join("<br>")
            });
            frappe.validated = false;
        }
    }
});

frappe.ui.form.on("Journal Entry Account", {
    account: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        var selected_account = d.account;
        if (selected_account) {
            frappe.db.get_value("Account", selected_account, "account_number", function(r) {
                if (!locals[cdt] || !locals[cdt][cdn] || locals[cdt][cdn].account !== selected_account) {
                    return;
                }
                frappe.model.set_value(cdt, cdn, "account_number", (r && r.account_number) || "");
            });
        } else {
            frappe.model.set_value(cdt, cdn, "account_number", "");
        }
    },

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
