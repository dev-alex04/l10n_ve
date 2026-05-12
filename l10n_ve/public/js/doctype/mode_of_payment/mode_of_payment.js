frappe.ui.form.on('Mode of Payment', {
    refresh: function (frm) {
        frm.trigger('toggle_is_igtf_applicable');
    },

    currency: function (frm) {
        frm.trigger('toggle_is_igtf_applicable');
    },

    toggle_is_igtf_applicable: function (frm) {
        const company_currency = frappe.defaults.get_default("currency");

        if (frm.doc.currency && frm.doc.currency !== company_currency) {
            frm.set_df_property('is_igtf_applicable', 'hidden', 0);
        } else {
            frm.set_df_property('is_igtf_applicable', 'hidden', 1);
            if (frm.doc.is_igtf_applicable) {
                frm.set_value('is_igtf_applicable', 0);
            }
        }
    },

    validate: function (frm) {
        const company_currency = frappe.defaults.get_default("currency");

        if (frm.doc.currency === company_currency && frm.doc.is_igtf_applicable) {
            frm.set_value('is_igtf_applicable', 0);
            frappe.msgprint(__('El IGTF no puede aplicar a la moneda local. Se ha desmarcado automáticamente.'));
        }
    }
});