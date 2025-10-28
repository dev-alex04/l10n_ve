frappe.ui.form.on("Purchase Order", {
  supplier: function (frm) {
    get_tax_withholding_category(frm)
  },
});

function get_tax_withholding_category(frm) {
  frm.set_value('apply_tds', 0);

  frappe.db.get_value('Supplier', frm.doc.supplier, 'tax_withholding_category')
    .then(r => {
      const category = r.message.tax_withholding_category;

      if (category) {
        frm.set_value('apply_tds', 1);
      } else {
        frm.set_value('apply_tds', 0);
      }
    })
    .catch(error => {
      console.error("Error al obtener la categoría:", error);
    });
}

frappe.ui.form.on("Purchase Order Item", {
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
