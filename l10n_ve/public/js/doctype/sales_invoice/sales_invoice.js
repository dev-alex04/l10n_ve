frappe.ui.form.on("Sales Invoice", {
  refresh: function (frm) {
    // Define los campos que se ocultarán/mostrarán en conjunto
    const fields_to_toggle = [
      "vat_withholding_voucher_number",
      "withholding_date",
    ];

    const customer = frm.doc.customer;

    // Oculta ambos campos por defecto
    frm.toggle_display(fields_to_toggle, false);

    if (customer) {
      frappe.db
        .get_value("Customer", customer, "is_special_taxpayer")
        .then((r) => {
          const is_special = r.message.is_special_taxpayer;

          if (is_special) {
            // Si el cliente es contribuyente especial, muestra ambos campos
            frm.toggle_display(fields_to_toggle, true);
          }
        });
    }
  },
});
