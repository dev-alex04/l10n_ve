frappe.ui.form.on('Address', {
    phone: function(frm) {
        let phone_value = frm.doc.phone;

        if (phone_value) {
            let clean_phone = phone_value.replace(/[^0-9]/g, '');

            if (clean_phone.length > 11) {
                clean_phone = clean_phone.substring(0, 11);

                frappe.show_alert({
                    message: __("El número de teléfono debe tener un máximo de 11 dígitos."),
                    indicator: 'orange'
                }, 3);
            }

            if (frm.doc.phone !== clean_phone) {
                frm.set_value('phone', clean_phone);
            }
        }
    }
});