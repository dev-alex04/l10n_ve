frappe.ui.form.on('Address', {
    refresh: function (frm) {
        reorganize_address_fields(frm);
        filter_data(frm);
        get_address_name(frm);
    },

    phone: function (frm) {
        let phone_value = frm.doc.phone;

        if (phone_value) {
            let formatted_value = phone_value.replace(/[^\d+]/g, "");

            if (formatted_value.lastIndexOf("+") > 0) {
                formatted_value = formatted_value[0] + formatted_value.substring(1).replace(/\+/g, "");
            }

            if (formatted_value.length > 20) {
                formatted_value = formatted_value.substring(0, 20);
            }

            if (frm.doc.phone !== formatted_value) {
                frm.set_value('phone', formatted_value);
            }
        }
    },

    before_save: function (frm) {
        validate_phone(frm);
        get_address_name(frm);
    },

    country: function (frm) {
        frm.set_value('state', null);
        frm.set_value('city', null);
        frm.set_value('county', null);
        frm.set_value('parish', null);
    },

    state: function (frm) {
        frm.set_value('city', null);
        frm.set_value('county', null);
        frm.set_value('parish', null);
    },

    county: function (frm) {
        frm.set_value('parish', null);
    },
});

function validate_phone(frm) {
    const phone = frm.doc.phone;
    if (!phone) return;

    const phone_regex = /^\+?\d{7,20}$/;
    if (!phone_regex.test(phone)) {
        frappe.throw({
            message: __("El número de teléfono debe contener entre 7 y 20 dígitos.\nSolo puede incluir números y el signo '+' al principio."),
            title: __("Error de Validación de Teléfono"),
            field: 'phone'
        });
    }
}

function get_address_name(frm) {
    const links = frm.doc.links

    if (links && links.length > 0) {
        frm.set_value('address_title', links[0].link_name);
    } else {
        if (frm.doc.address_line1) {
            frm.set_value('address_title', frm.doc.address_line1);
        } else {
            frm.set_value('address_title', 'Nueva Dirección');
        }
    }
}

function get_conditional_filter(filter_key, selected_value) {
    if (selected_value) {
        return {
            filters: {
                [filter_key]: selected_value
            }
        };
    } else {
        return {
            filters: {
                [filter_key]: ['is', 'not set']
            }
        };
    }
}

function filter_data(frm) {
    frm.set_query('state', function () {
        return get_conditional_filter('country', frm.doc.country);
    });

    frm.set_query('county', function () {
        return get_conditional_filter('state', frm.doc.state);
    });

    frm.set_query('parish', function () {
        return get_conditional_filter('municipality', frm.doc.county);
    });

    frm.set_query('city', function () {
        return get_conditional_filter('state', frm.doc.state);
    });
}

function reorganize_address_fields(frm) {
    const address_line1_field_wrapper = frm.get_field("address_line1").$wrapper;
    const country_field_wrapper = frm.get_field("country").$wrapper;
    const state_field_wrapper = frm.get_field("state").$wrapper;
    const city_field_wrapper = frm.get_field("city").$wrapper;
    const county_field_wrapper = frm.get_field("county").$wrapper;
    const parish_field_wrapper = frm.get_field("parish").$wrapper;

    country_field_wrapper.insertAfter(address_line1_field_wrapper);
    state_field_wrapper.insertAfter(country_field_wrapper);
    city_field_wrapper.insertAfter(state_field_wrapper);
    county_field_wrapper.insertAfter(city_field_wrapper);
    parish_field_wrapper.insertAfter(county_field_wrapper);
}