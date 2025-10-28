frappe.ui.form.on("Supplier", {
  refresh: function (frm) {
    reorganize_supplier_fields(frm);

    if (frm.is_new()) {
      frm.set_value('type_of_document', '');
      frm.set_value('nature_of_the_taxpayer', '');
      frm.set_value('type_of_person', '');
      hidden_address_contact(frm);
    } else {
      get_address_link(frm);
    }

    handle_supplier_field_change(frm, null);
  },

  nature_of_the_taxpayer: function (frm) {
    handle_supplier_field_change(frm, "nature_of_the_taxpayer");
  },

  type_of_person: function (frm) {
    handle_supplier_field_change(frm, "type_of_person");
  },

  type_of_document: function (frm) {
    handle_supplier_field_change(frm, "type_of_document");
  },

  tax_id: function (frm) {
    build_tax_id(frm);
  },
});

function handle_supplier_field_change(frm, fieldname) {
  // Llama a la función centralizada de utils.js
  handle_field_change(frm, fieldname);

  // Lógica específica para Supplier
  const doc_type = frm.doc.type_of_document;

  if (doc_type === "RIF") {
    // Para RIF, mostrar el campo y hacerlo requerido
    frm.toggle_display("tax_withholding_category", true);
    frm.set_df_property("tax_withholding_category", "reqd", 1);
  } else {
    // Para Cédula, Pasaporte u otro, ocultar el campo y no hacerlo requerido
    frm.toggle_display('tax_withholding_category', false);
    frm.set_value('tax_withholding_category', '');
    frm.set_df_property("tax_withholding_category", "reqd", 0);
  }
}

function reorganize_supplier_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id").$wrapper;
  let type_of_person_field_wrapper = frm.get_field("type_of_person").$wrapper;
  let supplier_type_field_wrapper = frm.get_field("supplier_type").$wrapper;
  let supplier_name_field_wrapper = frm.get_field("supplier_name").$wrapper;
  let is_transporter_field_wrapper = frm.get_field("is_transporter").$wrapper;
  let country_field_wrapper = frm.get_field("country").$wrapper;
  let supplier_group_field_wrapper = frm.get_field("supplier_group").$wrapper;
  let type_of_document_field_wrapper = frm.get_field("type_of_document").$wrapper;
  let nature_of_the_taxpayer_field_wrapper = frm.get_field("nature_of_the_taxpayer").$wrapper;


  let default_price_list_field_wrapper =
    frm.get_field("default_price_list").$wrapper;

  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category"
  ).$wrapper;

  supplier_type_field_wrapper.insertAfter(supplier_name_field_wrapper);
  type_of_document_field_wrapper.insertAfter(supplier_type_field_wrapper);
  nature_of_the_taxpayer_field_wrapper.insertAfter(type_of_document_field_wrapper);
  type_of_person_field_wrapper.insertAfter(nature_of_the_taxpayer_field_wrapper);
  tax_id_field_wrapper.insertAfter(type_of_person_field_wrapper);
  tax_withholding_category_field_wrapper.insertAfter(tax_id_field_wrapper);
  country_field_wrapper.insertAfter(supplier_group_field_wrapper);
  is_transporter_field_wrapper.insertAfter(default_price_list_field_wrapper);
}
