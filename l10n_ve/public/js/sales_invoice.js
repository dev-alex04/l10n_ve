frappe.ui.form.on('Sales Invoice', {

refresh: function(frm) {
    let field_to_show = 'vat_withholding_voucher_number';
    let customer = frm.doc.customer;
        
    // Oculta el campo por defecto
    frm.toggle_display(field_to_show, false);
    if (customer) {
        frappe.db.get_value('Customer', customer, 'is_special_taxpayer')
            .then(r => {
                let is_special = r.message.is_special_taxpayer;
                
                if (is_special) {
                    frm.toggle_display(field_to_show, true);
                }
            });
    }
}
});
