frappe.ui.form.on("Customer", {
  refresh: function (frm) {
    reorganize_customer_fields(frm);
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
