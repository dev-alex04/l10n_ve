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
    },

    before_save: function(frm) {
        validate_phone(frm);
    }
});

function validate_phone(frm) {
    let phone = frm.doc.phone;

    if (phone) {
        let clean_phone = phone.replace(/[^0-9]/g, '');

        if (clean_phone !== phone) {
            frappe.throw({
                message: __("El campo Teléfono solo puede contener números (0-9)."),
                title: __("Error de Validación de Teléfono"),
                field: 'phone'
            });
        }

        if (clean_phone.length !== 11) {
            frappe.throw({
                message: __("El número de teléfono debe tener exactamente 11 dígitos."),
                title: __("Error de Validación de Teléfono"),
                field: 'phone'
            });
        }
    }
}