frappe.ui.form.on("Journal Entry", {
    setup: function(frm) {
        set_reference_name_query(frm);
    },

    refresh: function(frm) {
        set_reference_name_query(frm);

        // Asegurar que todas las filas existentes muestren su número de cuenta en una sola consulta por lote
        var accounts = [...new Set((frm.doc.accounts || [])
            .filter(function(row) { return row.account && !row.account_number; })
            .map(function(row) { return row.account; }))];

        if (accounts.length > 0) {
            frappe.db.get_list("Account", {
                filters: { name: ["in", accounts] },
                fields: ["name", "account_number"],
                page_length: accounts.length
            }).then(function(results) {
                var by_name = {};
                (results || []).forEach(function(r) { by_name[r.name] = r.account_number; });
                var grid = frm.fields_dict.accounts && frm.fields_dict.accounts.grid;
                (frm.doc.accounts || []).forEach(function(row) {
                    if (row.account && !row.account_number && by_name[row.account]) {
                        row.account_number = by_name[row.account];
                        if (locals[row.doctype] && locals[row.doctype][row.name]) {
                            locals[row.doctype][row.name].account_number = by_name[row.account];
                        }
                        if (grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[row.name]) {
                            grid.grid_rows_by_docname[row.name].refresh_field("account_number");
                        }
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
    reference_name: function(frm, cdt, cdn) {
        var d = locals[cdt][cdn];
        // Si el usuario ya había colocado un monto en el Débito (ajuste de reapertura),
        // evitamos que get_outstanding de ERPNext lo sobrescriba con 0 al seleccionar una factura saldada.
        // get_outstanding es un frappe.call sin duración garantizada: en vez de una sola
        // comprobación a los 600ms (pierde la carrera si el servidor tarda más), reintenta
        // cada 200ms hasta 3s o hasta que el valor deje de estar en cero.
        if (flt(d.debit_in_account_currency) > 0 || flt(d.debit) > 0) {
            var prev_debit = flt(d.debit_in_account_currency) || flt(d.debit);
            var attempts = 0;
            var restore_if_cleared = function() {
                var current = locals[cdt] && locals[cdt][cdn];
                if (!current) return;
                if (!flt(current.debit_in_account_currency) && !flt(current.debit)) {
                    frappe.model.set_value(cdt, cdn, "debit_in_account_currency", prev_debit);
                    frappe.model.set_value(cdt, cdn, "debit", prev_debit);
                }
                attempts += 1;
                if (attempts < 15) {
                    setTimeout(restore_if_cleared, 200);
                }
            };
            setTimeout(restore_if_cleared, 200);
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

function set_reference_name_query(frm) {
    frm.set_query("reference_name", "accounts", function (doc, cdt, cdn) {
        var jvd = frappe.get_doc(cdt, cdn);

        // Journal Entry contra Journal Entry
        if (jvd.reference_type === "Journal Entry") {
            frappe.model.validate_missing(jvd, "account");
            return {
                query: "erpnext.accounts.doctype.journal_entry.journal_entry.get_against_jv",
                filters: {
                    account: jvd.account,
                    party: jvd.party,
                },
            };
        }

        var out = {
            filters: [[jvd.reference_type, "docstatus", "=", 1]],
        };

        if (["Sales Invoice", "Purchase Invoice"].includes(jvd.reference_type)) {
            // En ERPNext estándar se fuerza `outstanding_amount != 0`.
            // Para permitir ajustes contables o reaperturas (ej. reverso de retenciones no aplicadas):
            // - Sales Invoice: solo se exige saldo != 0 si es un pago/abono (crédito). Si es un débito o no tiene monto aún, se permite seleccionar facturas con saldo 0.
            // - Purchase Invoice: solo se exige saldo != 0 si es un pago/abono (débito). Si es un crédito o no tiene monto aún, se permite seleccionar facturas con saldo 0.
            var is_payment = false;
            if (jvd.reference_type === "Sales Invoice") {
                is_payment = flt(jvd.credit) > 0 || flt(jvd.credit_in_account_currency) > 0;
            } else if (jvd.reference_type === "Purchase Invoice") {
                is_payment = flt(jvd.debit) > 0 || flt(jvd.debit_in_account_currency) > 0;
            }

            // En un asiento de diferencia en cambio el ajuste cae sobre facturas ya saldadas: su saldo
            // no dice si el ajuste corresponde, así que ahí tampoco se exige.
            var is_exchange_adjustment = doc && doc.voucher_type === "Exchange Gain Or Loss";

            if (is_payment && !is_exchange_adjustment) {
                out.filters.push([jvd.reference_type, "outstanding_amount", "!=", 0]);
            }

            // Filtro por Centro de Costos si está definido en la fila
            if (jvd.cost_center) {
                out.filters.push([jvd.reference_type, "cost_center", "in", ["", jvd.cost_center]]);
            }

            // Filtro por Cuenta Contable (debit_to en facturas de venta, credit_to en compras)
            frappe.model.validate_missing(jvd, "account");
            var party_account_field = jvd.reference_type === "Sales Invoice" ? "debit_to" : "credit_to";
            out.filters.push([jvd.reference_type, party_account_field, "=", jvd.account]);
        }

        if (["Sales Order", "Purchase Order"].includes(jvd.reference_type)) {
            frappe.model.validate_missing(jvd, "party_type");
            frappe.model.validate_missing(jvd, "party");
            out.filters.push([jvd.reference_type, "per_billed", "<", 100]);
        }

        if (jvd.party_type && jvd.party) {
            let party_field = "";
            if (jvd.reference_type.indexOf("Sales") === 0) {
                party_field = "customer";
            } else if (jvd.reference_type.indexOf("Purchase") === 0) {
                party_field = "supplier";
            }

            if (party_field) {
                out.filters.push([jvd.reference_type, party_field, "=", jvd.party]);
            }
        }

        return out;
    });
}

