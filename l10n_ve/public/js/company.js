frappe.ui.form.on('Company', {
    refresh: function(frm) {
        frm.set_query('custom_company_primary_address', function() {
            return {
                filters: {
                    link_doctype: 'Company',
                    link_name: frm.doc.name
                }
            };
        });
    }
});