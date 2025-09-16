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

erpnext.taxes_and_totals.prototype.get_current_tax_amount = function (
  item,
  tax,
  item_tax_map
) {
  var tax_rate = this._get_tax_rate(tax, item_tax_map);
  var current_tax_amount = 0.0;

  // To set row_id by default as previous row.
  if (
    ["On Previous Row Amount", "On Previous Row Total"].includes(
      tax.charge_type
    )
  ) {
    if (tax.idx === 1) {
      frappe.throw(
        __(
          "Cannot select charge type as 'On Previous Row Amount' or 'On Previous Row Total' for first row"
        )
      );
    }
    if (!tax.row_id) {
      tax.row_id = tax.idx - 1;
    }
  }
  if (tax.charge_type == "Actual") {
    // distribute the tax amount proportionally to each item row
    var actual = flt(tax.tax_amount, precision("tax_amount", tax));
    current_tax_amount = this.frm.doc.net_total
      ? (item.net_amount / this.frm.doc.net_total) * actual
      : 0.0;
  } else if (tax.charge_type == "On Net Total") {
    current_tax_amount = (tax_rate / 100.0) * item.net_amount;
  } else if (tax.charge_type == "On Previous Row Amount") {
    current_tax_amount =
      (tax_rate / 100.0) *
      this.frm.doc["taxes"][cint(tax.row_id) - 1].tax_amount_for_current_item;
  } else if (tax.charge_type == "On Previous Row Total") {
    current_tax_amount =
      (tax_rate / 100.0) *
      this.frm.doc["taxes"][cint(tax.row_id) - 1].grand_total_for_current_item;
  } else if (tax.charge_type == "On Item Quantity") {
    current_tax_amount = tax_rate * item.qty;
  } else if (tax.charge_type == "ISLR") {
    tax_base = (this.frm.doc.total * tax.percentage_base) / 100;
    tax_amount = (tax_base * tax.rate) / 100 - tax.subtracting;

    current_tax_amount = tax_amount > 0 ? tax_amount : 0;
  } else if (tax.charge_type == "VAT Withholding") {
    tax_base = this.frm.doc["taxes"][cint(tax.idx) - 2].tax_amount;

    current_tax_amount = (tax_base * tax.rate) / 100;

    console.log(current_tax_amount);
  }

  if (!tax.dont_recompute_tax) {
    this.set_item_wise_tax(item, tax, tax_rate, current_tax_amount);
  }

  return current_tax_amount;
};
