// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("ISLR Withholding Voucher", {
	refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__('Imprimir Comprobante'), function() {
                window.open(
                    frappe.urllib.get_full_url(
                        "/printview?doctype=" + frm.doctype +
                        "&name=" + frm.doc.name +
                        "&format=" + encodeURIComponent("COMPROBANTE DE RETENCIÓN DE ISLR EN COMPRA")
                    )
                );
            });
        }
        return
    },

    onload: function(frm) {
        if (frm.doc.__islocal) {
            const company_name = frm.doc.empresa;
            const today = new Date();

            if (company_name) {
                frappe.call({
                    method: "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher.get_vat_correlative",
                    args: {
                        company_name: company_name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.set_value('voucher_number', r.message);
                        }
                    }
                });
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
        frm.clear_table('islr_withholding_voucher_item');
        frm.add_child('islr_withholding_voucher_item');
        frm.refresh_field('islr_withholding_voucher_item');

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
        frm.clear_table('islr_withholding_voucher_item');
        frm.add_child('islr_withholding_voucher_item');
        frm.refresh_field('islr_withholding_voucher_item');

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
            frm.clear_table('islr_withholding_voucher_item');
            frm.add_child('islr_withholding_voucher_item');
            frm.refresh_field('islr_withholding_voucher_item');
            
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

    frm.clear_table('islr_withholding_voucher_item');

    frappe.call({
        method: "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher.get_valid_invoices",
        args: {
            supplier: frm.doc.supplier,
            start_date: frm.doc.start_date,
            end_date: frm.doc.end_date,
            company: frm.doc.empresa
        },
        callback: function(r) {
            frm.doc.totals_total_exempt = 0;
            frm.doc.totals_tax_amount = 0;

            if (r.message && r.message.length > 0) {
                r.message.forEach(invoice => {
                    console.log(invoice);
                    let new_row = frm.add_child('islr_withholding_voucher_item');
                    new_row.purchase_invoice = invoice.purchase_invoice;
                    new_row.doc_no = invoice.doc_no;
                    new_row.doc_type = invoice.doc_type;
                    new_row.bill_control = invoice.bill_control;
                    new_row.posting_date = invoice.posting_date;
                    new_row.grand_total = invoice.grand_total;
                    new_row.payment_entry_name = invoice.payment_entry_name || '';

                    if (invoice.taxes) {
                        let tax_item = invoice.taxes;
                        new_row.total_exempt = invoice.total_exempt;
                        new_row.amount_paid = invoice.grand_total;
                        new_row.rate = tax_item.rate; 
                        new_row.subtracting = tax_item.subtracting; 
                        new_row.code = tax_item.code; 
                        new_row.tax_amount = tax_item.tax_amount;
                    }

                    let negative = invoice.is_return ? -1 : 1;
                    
                    frm.doc.totals_total_exempt += invoice.total_exempt * negative || 0;
                    frm.doc.totals_tax_amount += invoice.tax_amount * negative || 0;
                });
                
                frm.refresh_fields([
                    'totals_total_exempt',
                    'totals_tax_amount'
                ]);
                
                frm.refresh_fields();
            } else {
                frm.clear_table('islr_withholding_voucher_item');
                frm.add_child('islr_withholding_voucher_item');
                frm.refresh_field('islr_withholding_voucher_item');

                frm.doc.totals_total_exempt = 0;
                frm.doc.totals_tax_amount = 0;
                frm.refresh_fields();

                frappe.show_alert({
                    message: __("No se encontraron facturas de compra que cumplan con los criterios."),
                    indicator: 'orange'
                });
            }
        }
    });
}
