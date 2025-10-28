frappe.ui.form.on("Sales Order Item", {
  item_code: function (frm, cdt, cdn) {
    var row = frappe.get_doc(cdt, cdn);

    if (row.item_code && !row.vat_exempt) {
      frappe.db.get_value(
        "Item",
        row.item_code,
        "vat_exempt",
        function (value) {
          if (value.vat_exempt) {
            frappe.model.set_value(cdt, cdn, "vat_exempt", 1);
          }
        }
      );
    }
  },
});