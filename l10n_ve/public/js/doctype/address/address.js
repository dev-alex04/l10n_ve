frappe.ui.form.on('Address', {
    refresh: function (frm) {
        reorganize_address_fields(frm);
        filter_data(frm);
        get_address_name(frm);
    },

    phone: function (frm) {
        let phone_value = frm.doc.phone;

        if (phone_value) {
            let formatted_value = phone_value.replace(/[^\d+\s\-()]/g, "");

            if (formatted_value.lastIndexOf("+") > 0) {
                formatted_value = formatted_value[0] + formatted_value.substring(1).replace(/\+/g, "");
            }

            if (formatted_value.length > 25) {
                formatted_value = formatted_value.substring(0, 25);
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

    let clean_phone = phone.replace(/[\s\-()]/g, "");

    if (!/^\+?\d{10,15}$/.test(clean_phone)) {
        frappe.throw({
            message: __("El número de teléfono debe contener entre 10 y 15 dígitos. Puede incluir símbolos como (), -, espacios y el prefijo internacional (+)."),
            title: __("Error de Validación de Teléfono"),
            field: 'phone'
        });
    }

    let normalized = clean_phone;
    if (normalized.startsWith("+58")) {
        normalized = "0" + normalized.substring(3);
    } else if (normalized.startsWith("58") && normalized.length > 10) {
        normalized = "0" + normalized.substring(2);
    }

    if (normalized.startsWith("04")) {
        const VENEZUELAN_MOBILE_PREFIXES = ["0412", "0414", "0416", "0424", "0426", "0422"];
        const mobile_regex = new RegExp(`^(${VENEZUELAN_MOBILE_PREFIXES.join("|")})\\d{7}$`);
        if (!mobile_regex.test(normalized)) {
            frappe.throw({
                message: __("Los números de celular venezolanos (04xx) deben tener exactamente 11 dígitos y un prefijo válido."),
                title: __("Error de Validación de Teléfono"),
                field: 'phone'
            });
        }
    }

    // Validar prefijos locales venezolanos (02...)
    if (normalized.startsWith("02")) {
        if (normalized.length < 10) {
            frappe.throw({
                message: __("Los números locales (02xx) deben tener al menos 10 dígitos."),
                title: __("Error de Validación de Teléfono"),
                field: 'phone'
            });
        }
    } else if (normalized.startsWith("0")) {
        frappe.throw({
            message: __("El número de teléfono no es un formato venezolano (02xx, 04xx) ni internacional válido."),
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