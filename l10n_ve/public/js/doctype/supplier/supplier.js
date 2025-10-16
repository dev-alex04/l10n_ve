frappe.ui.form.on("Supplier", {
  refresh: function (frm) {
    reorganize_supplier_fields(frm);
  },

  nature_of_the_taxpayer: function (frm) {
    set_person_type_filter(frm);
    sync_taxpayer_fields(frm, 'nature_of_the_taxpayer');
    build_rif(frm);
  },

  type_of_person: function(frm) {
    sync_taxpayer_fields(frm, 'type_of_person');
  },

  tax_id: function (frm) {
    build_rif(frm);
  },
});

function reorganize_supplier_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id").$wrapper;
  let country_field_wrapper = frm.get_field("country").$wrapper;
  let is_transporter_field_wrapper = frm.get_field("is_transporter").$wrapper;

  let default_price_list_field_wrapper =
    frm.get_field("default_price_list").$wrapper;

  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category"
  ).$wrapper;

  tax_id_field_wrapper.insertAfter(country_field_wrapper);
  is_transporter_field_wrapper.insertAfter(default_price_list_field_wrapper);
  tax_withholding_category_field_wrapper.insertAfter(tax_id_field_wrapper);
}
