frappe.ui.form.on("Journal Entry", {
    refresh: function(frm) {
        // Asegurar que todas las filas existentes muestren su número de cuenta en una sola consulta por lote
        var accounts = [...new Set((frm.doc.accounts || [])
            .filter(function(row) { return row.account && !row.account_number; })
            .map(function(row) { return row.account; }))];

        if (accounts.length > 0) {
            frappe.db.get_list("Account", {
                filters: { name: ["in", accounts] },
                fields: ["name", "account_number"],
                limit: accounts.length
            }).then(function(results) {
                var by_name = {};
                (results || []).forEach(function(r) { by_name[r.name] = r.account_number; });
                (frm.doc.accounts || []).forEach(function(row) {
                    if (row.account && !row.account_number && by_name[row.account]) {
                        frappe.model.set_value(row.doctype, row.name, "account_number", by_name[row.account]);
                    }
                });
            });
        }
    },

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
