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
