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
    if (item.idx === 1) {
      let taxable_base = 0;
      this.frm.doc.items.forEach((doc_item) => {
        if (!doc_item.vat_exempt) {
          taxable_base += doc_item.net_amount;
        }
      });
      current_tax_amount = (tax_rate / 100.0) * taxable_base;
    } else {
      current_tax_amount = 0;
    }
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
    if (item.idx === 1) {
      var tax_base = (this.frm.doc.total * tax.percentage_base) / 100;
    } else {
      var tax_base = (item.net_amount * tax.percentage_base) / 100;
    }
    let tax_amount = (tax_base * tax.rate) / 100 - tax.subtracting;
    current_tax_amount = tax_amount > 0 ? tax_amount : 0;
  } else if (tax.charge_type == "VAT" && !item.vat_exempt) {
    current_tax_amount = (item.net_amount * tax.rate) / 100;
  } else if (tax.charge_type == "VAT Withholding" && !item.vat_exempt) {
    for (let tax_row of this.frm.doc.taxes || []) {
      if (tax_row.charge_type === "VAT") {
        let vat = (item.net_amount * tax_row.rate) / 100;
        current_tax_amount = (vat * tax.rate) / 100;
        break;
      }
    }
  }

  if (!tax.dont_recompute_tax) {
    this.set_item_wise_tax(item, tax, tax_rate, current_tax_amount);
  }

  return current_tax_amount;
};

erpnext.taxes_and_totals.prototype.set_cumulative_total = function (
  row_idx,
  tax
) {
  var tax_amount = tax.tax_amount_after_discount_amount;

  let tax_base = 0;

  if (row_idx == 0) {
    tax_base = this.frm.doc.net_total;
  } else {
    tax_base = this.frm.doc["taxes"][row_idx - 1].total;
  }

  if (tax.is_tax_withholding_account) {
    //  Solo en ventas, se resta la retenciòn de IVA

    if (
      tax.charge_type == "VAT Withholding" &&
      ["Quotation", "Sales Order", "Sales Invoice", "Delivery Note"].includes(
        this.frm.doc.doctype
      )
    ) {
      //  Se multiplica por -1 para forzar la resta
      tax.total = flt(tax_base + tax_amount * -1, precision("total"));
    } else {
      tax.total = tax_base;
    }
  } else {
    tax.total = flt(tax_base + tax_amount, precision("total"));
  }
};
