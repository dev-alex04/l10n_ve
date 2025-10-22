// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Municipaly", {
    refresh: function(frm) {
        frm.set_query('state', function() {
            return {
                filters: {
                    'country': frm.doc.country
                }
            };
        });
    },

    country: function(frm) {
        frm.set_value('state', null);
    }
});
