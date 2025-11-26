frappe.ui.form.on("Customer", {
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value("type_of_document", "");
      frm.set_value("nature_of_the_taxpayer", "");
      frm.set_value("type_of_person", "");
    }
  },
  refresh: function (frm) {
    add_address_button(frm);
    reorganize_customer_fields(frm);

    if (frm.is_new()) {
      hidden_address_contact(frm);
    } else {
      get_address_link(frm);
    }

    handle_customer_field_change(frm, null);
    handle_field_change(frm, null);
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
});

function handle_customer_field_change(frm, fieldname) {
  const doc_type = frm.doc.type_of_document;

  if (doc_type === "Cedula" || doc_type === "Passport") {
    frm.toggle_display("is_special_taxpayer", false);
    frm.set_value("is_special_taxpayer", 0);
    frm.set_value("tax_withholding_category", "");
    frm.set_df_property("tax_withholding_category", "reqd", 0);
    frm.toggle_display("tax_withholding_category", false);
  } else {
    frm.toggle_display("is_special_taxpayer", true);

    // Lógica para Contribuyente Especial
    const is_special = frm.doc.is_special_taxpayer;
    frm.toggle_display("tax_withholding_category", false);
    frm.set_df_property("tax_withholding_category", "reqd", 0);
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
    "nature_of_the_taxpayer"
  ).$wrapper;
  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category"
  ).$wrapper;
  let is_special_taxpayer_field_wrapper = frm.get_field(
    "is_special_taxpayer"
  ).$wrapper;

  tax_withholding_category_field_wrapper.insertAfter(
    is_special_taxpayer_field_wrapper
  );
  customer_type_field_wrapper.insertAfter(customer_name_field_wrapper);
  type_of_document_field_wrapper.insertAfter(customer_type_field_wrapper);
  nature_of_the_taxpayer_field_wrapper.insertAfter(
    type_of_document_field_wrapper
  );
  type_of_person_field_wrapper.insertAfter(
    nature_of_the_taxpayer_field_wrapper
  );
  tax_id_field_wrapper.insertAfter(type_of_person_field_wrapper);
}
