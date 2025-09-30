frappe.ui.form.on("Supplier", {
  refresh: function (frm) {
    reorganize_supplier_fields(frm);
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
