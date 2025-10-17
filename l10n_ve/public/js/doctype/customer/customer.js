frappe.ui.form.on("Customer", {
  refresh: function (frm) {
    reorganize_customer_fields(frm);
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

function reorganize_customer_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id").$wrapper;
  let customer_name_field_wrapper = frm.get_field("customer_name").$wrapper;
  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category"
  ).$wrapper;
  let is_special_taxpayer_field_wrapper = frm.get_field(
    "is_special_taxpayer"
  ).$wrapper;

  tax_id_field_wrapper.insertAfter(customer_name_field_wrapper);
  tax_withholding_category_field_wrapper.insertAfter(
    is_special_taxpayer_field_wrapper
  );
}
