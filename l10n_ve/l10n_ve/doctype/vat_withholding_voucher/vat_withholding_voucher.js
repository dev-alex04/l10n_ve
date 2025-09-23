// // Copyright (c) 2025, DominaERP and contributors
// // For license information, please see license.txt

frappe.ui.form.on('VAT Withholding Voucher', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__('Imprimir'), function() {
                frappe.call({
                    method: "l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase.generate_vat_report",
                    args: {
                        voucher_name: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            var w = window.open('about:blank');
                            w.document.write(r.message);
                            w.document.close();
                            w.print();
                        }
                    }
                });
            });
        }
    },

    onload: function(frm) {
        if (frm.doc.__islocal) {
            const company_name = frm.doc.empresa;
            const today = new Date();

            if (company_name) {
                frappe.call({
                    method: "l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher.get_vat_correlative",
                    args: {
                        company_name: company_name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.set_value('voucher_number', r.message);
                        }
                    }
                });

                frm.set_value('issue_date', today);
                frm.set_value('delivery_date', today);
            }
        }
    },

    start_date: function(frm) {
        if (frm.doc.start_date && frm.doc.end_date) {
            validar_fechas(frm, 'start_date');
        }

        if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
            load_invoices(frm);
        }
    },

    end_date: function(frm) {
        if (frm.doc.start_date && frm.doc.end_date) {
            validar_fechas(frm, 'end_date');
        }

        if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
            load_invoices(frm);
        }
    },

    supplier: function(frm) {
        frm.clear_table('vat_withholding_voucher_item');
        frm.add_child('vat_withholding_voucher_item');
        frm.refresh_field('vat_withholding_voucher_item');

        frm.set_value('supplier_address', '');
        frm.refresh_field('supplier_address');
        
        if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
            load_invoices(frm);
        }

        if (frm.doc.supplier) {
            frappe.call({
                method: "l10n_ve.utils.utils.get_supplier_address",
                args: {
                    supplier_name: frm.doc.supplier
                },
                callback: function(r) {
                    if (r.message && r.message.address_line1) {
                        const full_address = r.message.address_line1;
                        frm.set_value('supplier_address', full_address);
                    } else {
                        frm.set_value('supplier_address', '');
                    }
                }
            });
        }
    },

    empresa: function(frm) {
        frm.clear_table('vat_withholding_voucher_item');
        frm.add_child('vat_withholding_voucher_item');
        frm.refresh_field('vat_withholding_voucher_item');

        frm.set_value('company_address', '');
        frm.refresh_field('company_address');
        
        if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
            load_invoices(frm);
        }

        if (frm.doc.empresa) {
            frappe.call({
                method: "l10n_ve.utils.utils.get_company_address",
                args: {
                    company_name: frm.doc.empresa
                },
                callback: function(r) {
                    if (r.message && r.message.address_line1) {
                        const full_address = r.message.address_line1;
                        frm.set_value('company_address', full_address);
                    } else {
                        frm.set_value('company_address', '');
                    }
                }
            });
        }
    },
});

function validar_fechas(frm, campo) {
    try {
        const startDate = new Date(frm.doc.start_date);
        const endDate = new Date(frm.doc.end_date);

        if (endDate < startDate) {
            frm.set_value(campo, null);
            frm.clear_table('vat_withholding_voucher_item');
            frm.add_child('vat_withholding_voucher_item');
            frm.refresh_field('vat_withholding_voucher_item');
            
            throw new Error('La fecha de fin no puede ser menor que la fecha de inicio.');
        }
    } catch (e) {
        frappe.throw(e.message);
    }
}

function load_invoices(frm) {
    if (!frm.doc.supplier || !frm.doc.start_date || !frm.doc.end_date || !frm.doc.empresa) {
        return;
    }

    frm.clear_table('vat_withholding_voucher_item');

    frappe.call({
        method: "l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher.get_valid_invoices",
        args: {
            supplier: frm.doc.supplier,
            start_date: frm.doc.start_date,
            end_date: frm.doc.end_date,
            company: frm.doc.empresa
        },
        callback: function(r) {
            frm.doc.totals_grand_total = 0;
            frm.doc.totals_total_exempt = 0;
            frm.doc.totals_total = 0;
            frm.doc.totals_taxes_and_charges_added = 0;
            frm.doc.totals_taxes_and_charges_deducted = 0;

            if (r.message && r.message.length > 0) {
                r.message.forEach(invoice => {
                    let new_row = frm.add_child('vat_withholding_voucher_item');
                    new_row.purchase_invoice = invoice.purchase_invoice;
                    new_row.bill_no = invoice.bill_no;
                    new_row.bill_control = invoice.bill_control;
                    new_row.posting_date = invoice.posting_date;
                    new_row.rate = invoice.rate;
                    new_row.grand_total = invoice.grand_total;
                    new_row.total_exempt = invoice.total_exempt;
                    new_row.total = invoice.total;
                    new_row.taxes_and_charges_added = invoice.taxes_and_charges_added;
                    new_row.taxes_and_charges_deducted = invoice.taxes_and_charges_deducted;
                    new_row.credit_note_no = invoice.credit_note_no;
                    new_row.debit_note_no = invoice.debit_note_no;
                    new_row.affected_invoice_number = invoice.affected_invoice_number;

                    if (invoice.taxes && invoice.taxes.length > 0) {
                        let tax_item = invoice.taxes[0];
                        new_row.rate = tax_item.rate; 
                        new_row.tax_amount = tax_item.tax_amount;
                    }
                    
                    frm.doc.totals_grand_total += invoice.grand_total || 0;
                    frm.doc.totals_total_exempt += invoice.total_exempt || 0;
                    frm.doc.totals_total += invoice.total || 0;
                    frm.doc.totals_taxes_and_charges_added += invoice.taxes_and_charges_added || 0;
                    frm.doc.totals_taxes_and_charges_deducted += invoice.taxes_and_charges_deducted || 0;

                    console.log(new_row);
                });
                
                frm.refresh_fields([
                    'totals_grand_total', 
                    'totals_total_exempt', 
                    'totals_total',
                    'totals_taxes_and_charges_added',
                    'totals_taxes_and_charges_deducted'
                ]);
                
                frm.refresh_fields();
            } else {
                frm.clear_table('vat_withholding_voucher_item');
                frm.add_child('vat_withholding_voucher_item');
                frm.refresh_field('vat_withholding_voucher_item');

                frm.doc.totals_grand_total = 0;
                frm.doc.totals_totals_total_exempt = 0;
                frm.doc.totals_total = 0;
                frm.doc.totals_taxes_and_charges_added = 0;
                frm.doc.totals_taxes_and_charges_deducted = 0;
                frm.refresh_fields();

                frappe.show_alert({
                    message: __("No se encontraron facturas de compra que cumplan con los criterios."),
                    indicator: 'orange'
                });
            }
        }
    });
}