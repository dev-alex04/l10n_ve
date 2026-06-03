// -*- coding: utf-8 -*-
// Client script for VE Deposit DocType Form.
// Fully written in English for frontend logic/comments.

frappe.ui.form.on('VE Deposit', {
    setup: function(frm) {
        // Set dynamic filters for Destination Account (Cash or Bank accounts only)
        frm.set_query('destination_account', function() {
            return {
                filters: {
                    company: frm.doc.company,
                    account_type: ['in', ['Bank', 'Cash']],
                    is_group: 0
                }
            };
        });

        // Set dynamic filters for Source Account (Must belong to the selected company)
        frm.set_query('source_account', function() {
            return {
                filters: {
                    company: frm.doc.company,
                    is_group: 0
                }
            };
        });
    },

    onload: function(frm) {
        if (frm.is_new()) {
            frm.set_value('posting_date', frappe.datetime.get_today());
            if (!frm.doc.company) {
                frm.set_value('company', frappe.defaults.get_user_default('company'));
            }
        }
    },

    company: function(frm) {
        frm.trigger('fetch_exchange_rate');
    },

    posting_date: function(frm) {
        frm.trigger('fetch_exchange_rate');
    },

    currency: function(frm) {
        if (frm.doc.currency === 'VEF') {
            frm.set_value('exchange_rate', 1.0);
        } else {
            frm.trigger('fetch_exchange_rate');
        }
    },

    amount: function(frm) {
        frm.trigger('calculate_base_amount');
    },

    exchange_rate: function(frm) {
        frm.trigger('calculate_base_amount');
    },

    fetch_exchange_rate: function(frm) {
        if (frm.doc.currency === 'USD' && frm.doc.posting_date) {
            frappe.call({
                method: 'l10n_ve.utils.utils.get_exchange_rate',
                args: {
                    date: frm.doc.posting_date,
                    from_currency: 'USD'
                },
                callback: function(r) {
                    if (r.message) {
                        frm.set_value('exchange_rate', flt(r.message));
                    } else {
                        frm.set_value('exchange_rate', 1.0);
                    }
                    frm.trigger('calculate_base_amount');
                }
            });
        } else {
            frm.set_value('exchange_rate', 1.0);
            frm.trigger('calculate_base_amount');
        }
    },

    calculate_base_amount: function(frm) {
        let amount = flt(frm.doc.amount);
        let rate = flt(frm.doc.exchange_rate) || 1.0;
        if (frm.doc.currency === 'USD') {
            frm.set_value('amount_in_base_currency', amount * rate);
        } else {
            frm.set_value('amount_in_base_currency', amount);
        }
    }
});
