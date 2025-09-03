frappe.ui.form.on('Sales Invoice', {
    refresh: function(frm) {
        let custom_field_to_show = 'vat_withholding_voucher_number';
        let customer_name = frm.doc.customer;
        
        // Oculta el campo por defecto
        frm.toggle_display(custom_field_to_show, false);
        if (customer_name) {
            frappe.db.get_value('Customer', customer_name, 'is_special_taxpayer')
                .then(r => {
                    let is_special = r.message.is_special_taxpayer;
                    
                    // Si el cliente es un contribuyente especial, muestra el campo
                    if (is_special) {
                        frm.toggle_display(custom_field_to_show, true);
                    }
                });
        }
    }
});