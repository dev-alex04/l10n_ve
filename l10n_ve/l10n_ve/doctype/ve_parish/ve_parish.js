// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on('VE Parish', {
    refresh: function(frm) {
        frm.set_query('state', function() {
            return {
                filters: {
                    'country': frm.doc.country
                }
            };
        });

        frm.set_query('municipaly', function() {
            return {
                filters: {
                    'state': frm.doc.state
                }
            };
        });
    },

    country: function(frm) {
        frm.set_value('state', null);
        frm.set_value('municipaly', null);
    },

    state: function(frm) {
        frm.set_value('municipaly', null);
    }
});