frappe.ui.form.on("Supplier", {
  before_save: function (frm) {
    if (!frm.doc.supplier_primary_address) {
      frappe.throw(
        __(
          "El campo 'Dirección Principal' es obligatorio. Por favor, ingrese una dirección usando el botón 'Agregar Dirección' en la parte superior derecha"
        )
      );
    }
  },
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value('supplier_primary_address', '');
    }
    setup_phone_validation(frm, "mobile_no");
  },
  refresh: function (frm) {
    add_address_button(frm);
    reorganize_supplier_fields(frm);

    if (frm.is_new()) {
      frm.set_value('type_of_document', '');
      frm.set_value('nature_of_the_taxpayer', '');
      frm.set_value('type_of_person', '');
      frm.set_value('supplier_primary_address', '');
      hidden_address_contact(frm);
    } else {
      get_address_link(frm);
      frm.toggle_display("supplier_primary_contact", false);
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

  validate: function (frm) {
    validate_phone_format(frm, "mobile_no");
    validate_party_emails(frm);
  },
});

function handle_supplier_field_change(frm, fieldname) {
  // Llama a la función centralizada de utils.js
  handle_field_change(frm, fieldname);

  // Lógica específica para Supplier
  const doc_type = frm.doc.type_of_document;

  // La categoria de retencion queda SIEMPRE visible y editable: un proveedor no
  // juridico igual puede ser contribuyente ordinario del IVA (factura con IVA) y
  // corresponderle retencion. Antes se ocultaba Y se vaciaba para todo lo que no
  // fuera RIF, asi que no habia forma de asignarsela: set_tax_withholding_ve lee la
  // categoria DEL PROVEEDOR, y sin ella nunca se calculaba la retencion.
  // Solo cambia la obligatoriedad: requerida para RIF, opcional para el resto.
  frm.toggle_display("tax_withholding_category", true);
  // frm.set_df_property("tax_withholding_category", "reqd", doc_type === "RIF" ? 0 : 0);
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
