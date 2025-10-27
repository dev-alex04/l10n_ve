frappe.ui.form.on('Address', {
    refresh: function(frm) {
        reorganize_customer_fields(frm);
        filter_data(frm);
        get_address_name(frm);
    },

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
        get_address_name(frm);
    },

    country: function(frm) {
        frm.set_value('state', null);
        frm.set_value('city', null);
        frm.set_value('county', null);
        frm.set_value('parish', null);
    },

    state: function(frm) {
        frm.set_value('city', null);
        frm.set_value('county', null);
        frm.set_value('parish', null);
    },

    county: function(frm) {
        frm.set_value('parish', null);
    },
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
    frm.set_query('state', function() {
        return get_conditional_filter('country', frm.doc.country);
    });

    frm.set_query('county', function() {
        return get_conditional_filter('state', frm.doc.state);
    });

    frm.set_query('parish', function() {
        return get_conditional_filter('municipality', frm.doc.county);
    });

    frm.set_query('city', function() {
        return get_conditional_filter('state', frm.doc.state);
    });
}

function reorganize_customer_fields(frm) {
  let address_line1_field_wrapper = frm.get_field("address_line1").$wrapper;
  let country_field_wrapper = frm.get_field("country").$wrapper;
  let state_field_wrapper = frm.get_field("state").$wrapper;
  let city_field_wrapper = frm.get_field("city").$wrapper;
  let county_field_wrapper = frm.get_field("county").$wrapper;
  let parish_field_wrapper = frm.get_field("parish").$wrapper;

  country_field_wrapper.insertAfter(address_line1_field_wrapper);
  state_field_wrapper.insertAfter(country_field_wrapper);
  city_field_wrapper.insertAfter(state_field_wrapper);
  county_field_wrapper.insertAfter(city_field_wrapper);
  parish_field_wrapper.insertAfter(county_field_wrapper);
}