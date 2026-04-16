frappe.ui.form.on("Customer", {
  before_save: function (frm) {
    if (!frm.doc.customer_primary_address) {
      frappe.throw(
        __(
          "El campo 'Dirección Principal' es obligatorio. Por favor, ingrese una dirección usando el botón 'Agregar Dirección' en la parte superior derecha",
        ),
      );
    }
  },
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value("type_of_document", "");
      frm.set_value("nature_of_the_taxpayer", "");
      frm.set_value("type_of_person", "");
    }
    setup_phone_validation(frm, "mobile_no");
  },
  refresh: function (frm) {
    add_address_button(frm);
    reorganize_customer_fields(frm);

    if (frm.is_new()) {
      hidden_address_contact(frm);
    } else {
      get_address_link(frm);
      frm.toggle_display("customer_primary_contact", false);
    }

    handle_customer_field_change(frm, null);
    handle_field_change(frm, null);

    // Ocultar campos
    frm.toggle_display("account_manager", false);
    frm.toggle_display("lead_name", false);
    frm.toggle_display("opportunity_name", false);
    frm.toggle_display("prospect_name", false);

    const is_system_manager = frappe.user_roles.includes("System Manager");
    frm.toggle_display("contact_html", is_system_manager);
    if (!is_system_manager) {
      frm.fields_dict.contact_html.$wrapper.find("a").hide();
    }
  },

  nature_of_the_taxpayer: function (frm) {
    handle_field_change(frm, "nature_of_the_taxpayer");
    handle_customer_field_change(frm, "nature_of_the_taxpayer");
  },

  type_of_person: function (frm) {
    handle_field_change(frm, "type_of_person");
    handle_customer_field_change(frm, "type_of_person");
  },

  type_of_document: function (frm) {
    handle_field_change(frm, "type_of_document");
    handle_customer_field_change(frm, "type_of_document");
  },

  tax_id: function (frm) {
    build_tax_id(frm);
  },

  is_special_taxpayer: function (frm) {
    handle_customer_field_change(frm, "is_special_taxpayer");
  },

  validate: function (frm) {
    // validate_phone_format(frm, "mobile_no");
    validate_party_emails(frm);
  },
});

function handle_customer_field_change(frm, fieldname) {
  const doc_type = frm.doc.type_of_document;

  if (doc_type === "Cedula" || doc_type === "Passport") {
    frm.toggle_display("is_special_taxpayer", false);
    frm.toggle_display("tabulator_islr", false);
    frm.set_value("is_special_taxpayer", 0);
    frm.set_value("tabulator_islr", "");
    frm.set_value("tax_withholding_category", "");
    frm.set_df_property("tax_withholding_category", "reqd", 0);
    frm.toggle_display("tax_withholding_category", false);
  } else {
    frm.toggle_display("is_special_taxpayer", true);
    frm.toggle_display("tabulator_islr", true);

    const is_special = frm.doc.is_special_taxpayer;
    frm.toggle_display("tax_withholding_category", is_special);
    frm.set_df_property("tax_withholding_category", "reqd", is_special ? 1 : 0);
    if (!is_special) {
      frm.set_value("tax_withholding_category", "");
    }
  }
}

function reorganize_customer_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id").$wrapper;
  let type_of_person_field_wrapper = frm.get_field("type_of_person").$wrapper;
  let customer_type_field_wrapper = frm.get_field("customer_type").$wrapper;
  let customer_name_field_wrapper = frm.get_field("customer_name").$wrapper;
  let type_of_document_field_wrapper =
    frm.get_field("type_of_document").$wrapper;
  let nature_of_the_taxpayer_field_wrapper = frm.get_field(
    "nature_of_the_taxpayer",
  ).$wrapper;

  // Solo organizamos los campos de la pestaña de Detalles
  customer_type_field_wrapper.insertAfter(customer_name_field_wrapper);
  type_of_document_field_wrapper.insertAfter(customer_type_field_wrapper);
  nature_of_the_taxpayer_field_wrapper.insertAfter(
    type_of_document_field_wrapper,
  );
  type_of_person_field_wrapper.insertAfter(
    nature_of_the_taxpayer_field_wrapper,
  );
  tax_id_field_wrapper.insertAfter(type_of_person_field_wrapper);

  let is_special_taxpayer_field_wrapper = frm.get_field(
    "is_special_taxpayer",
  ).$wrapper;
  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category",
  ).$wrapper;
  let tabulator_islr_field_wrapper = frm.get_field("tabulator_islr").$wrapper;

  tax_withholding_category_field_wrapper.insertAfter(
    is_special_taxpayer_field_wrapper,
  );
  tabulator_islr_field_wrapper.insertAfter(
    tax_withholding_category_field_wrapper,
  );
}
