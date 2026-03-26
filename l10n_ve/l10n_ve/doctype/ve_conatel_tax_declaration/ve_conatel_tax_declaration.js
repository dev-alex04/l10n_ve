// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Conatel Tax Declaration", {
    onload: function (frm) {
        if (frm.is_new()) {
            let today = frappe.datetime.nowdate();
            let year = frappe.datetime.get_today().split("-")[0];

            if (!frm.doc.company) {
                frm.set_value("company", frappe.defaults.get_default("company"));
            }
            if (frm.doc.company) {
                frm.trigger("company");
            }
            if (!frm.doc.declaration_year) {
                frm.set_value("declaration_year", year);
            }
            if (!frm.doc.declaration_date) {
                frm.set_value("declaration_date", today);
            }
        }
    },
    company: function (frm) {
        if (frm.doc.company) {
            frappe.db.get_value("Company", frm.doc.company,
                ["tax_id", "legal_representative", "custom_company_primary_address", "default_currency"],
                (r) => {
                    if (r) {
                        if (r.tax_id) frm.set_value("tax_id", r.tax_id);
                        if (r.legal_representative) frm.set_value("legal_representative", r.legal_representative);
                        if (r.default_currency) frm.set_value("currency", r.default_currency);

                        if (r.custom_company_primary_address) {
                            frappe.db.get_value("Address", r.custom_company_primary_address, "address_line1", (addr) => {
                                if (addr && addr.address_line1) {
                                    frm.set_value("fiscal_address", addr.address_line1);
                                }
                            });
                        }
                    }
                });
        }
    },
    refresh: function (frm) {
        frm.set_query("item_code", "items", function () {
            return {
                filters: [
                    ["Item", "is_conatel_service", "=", 1]
                ]
            };
        });

        frm.set_query("branch", function () {
            return {
                filters: {
                    company: frm.doc.company
                }
            };
        });

        frm.set_query("tax_payable_account", function () {
            return {
                filters: {
                    company: frm.doc.company,
                    is_group: 0
                }
            };
        });

        frm.set_query("tax_expense_account", function () {
            return {
                filters: {
                    company: frm.doc.company,
                    is_group: 0
                }
            };
        });

        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Obtener Datos de Ingresos"), function () {
                if (!frm.doc.company || !frm.doc.from_date || !frm.doc.to_date) {
                    frappe.msgprint(__("Por favor, seleccione Empresa, Fecha Desde y Fecha Hasta."));
                    return;
                }

                frappe.call({
                    method: "l10n_ve.l10n_ve.doctype.ve_conatel_tax_declaration.ve_conatel_tax_declaration.get_conatel_data",
                    args: {
                        company: frm.doc.company,
                        from_date: frm.doc.from_date,
                        to_date: frm.doc.to_date,
                        branch: frm.doc.branch
                    },
                    callback: function (r) {
                        if (r.message) {
                            let data = r.message;

                            frm.clear_table("items");
                            frm.clear_table("taxes");

                            (data.items || []).forEach(item => {
                                let row = frm.add_child("items");
                                row.item_code = item.item_code;
                                row.item_name = item.item_name;
                                row.invoice_count = item.invoice_count;
                                row.taxable_base = item.taxable_base;
                            });

                            // Totales
                            frm.set_value("total_taxable_base", data.total_taxable_base);

                            (data.taxes || []).forEach(tax => {
                                let row = frm.add_child("taxes");
                                row.tax_type = tax.tax_type;
                                row.aliquot = tax.aliquot;
                                row.amount = tax.amount;
                            });

                            calculate_total_to_pay(frm);
                            frm.refresh_fields();
                        }
                    }
                });
            });
        }

        if (frm.doc.docstatus === 1) {
            if (frm.doc.status === "Declarado" && !frm.doc.journal_entry) {
                frm.add_custom_button(__("Crear Asiento Contable"), function () {
                    frm.call("make_journal_entry").then(r => {
                        if (r.message) {
                            frappe.msgprint(__("Asiento contable creado: ") + r.message);
                            frm.reload_doc();
                        }
                    });
                }, __("Acciones"));
            }

            if (frm.doc.journal_entry) {
                frm.add_custom_button(__("Cancelar Asiento Contable"), function () {
                    frappe.confirm(__("\u00bfEst\u00e1 seguro de que desea cancelar el asiento contable asociado?"), function () {
                        frm.call("cancel_journal_entry").then(r => {
                            frappe.msgprint(__("Asiento contable cancelado y desvinculado."));
                            frm.reload_doc();
                        });
                    });
                }, __("Acciones"));
            }
        }
    },

    declaration_year: function (frm) {
        if (frm.doc.declaration_year) {
            let year = frm.doc.declaration_year;
            if (!frm.doc.from_date) {
                frm.set_value("from_date", year + "-01-01");
            }
            if (!frm.doc.to_date) {
                frm.set_value("to_date", year + "-12-31");
            }
        }
    },

    num_declaration: function (frm) {
        check_declared_status(frm);
    },

    declaration_document: function (frm) {
        check_declared_status(frm);
    }
});

frappe.ui.form.on("VE Conatel Tax Declaration Tax", {
    tax_type: function (frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.tax_type) {
            frappe.db.get_value("VE Conatel Tax Type", row.tax_type, "aliquot", (r) => {
                if (r && r.aliquot !== undefined) {
                    frappe.model.set_value(cdt, cdn, "aliquot", r.aliquot);

                    let base = flt(frm.doc.total_taxable_base);
                    let amount = base * (flt(r.aliquot) / 100);
                    frappe.model.set_value(cdt, cdn, "amount", flt(amount, 2));
                }
            });
        }
    },
    amount: function (frm) {
        calculate_total_to_pay(frm);
    },
    taxes_remove: function (frm) {
        calculate_total_to_pay(frm);
    },
    taxes_add: function (frm) {
        calculate_total_to_pay(frm);
    }
});

function calculate_total_to_pay(frm) {
    let total = 0;
    (frm.doc.taxes || []).forEach(row => {
        total += flt(row.amount);
    });
    frm.set_value("total_to_pay", flt(total, 2));
    check_declared_status(frm);
}

function check_declared_status(frm) {
    if (frm.doc.num_declaration && frm.doc.declaration_document) {
        frm.set_value("status", "Declarado");
    } else if (frm.doc.total_taxable_base > 0) {
        frm.set_value("status", "Por Declarar");
    } else {
        frm.set_value("status", "Por Procesar");
    }
}
