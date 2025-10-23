async function get_currency_symbol(frm, currency) {
  try {
    const r = await frappe.call({
      method: "l10n_ve.controllers.transaction.get_currency_symbol",
      args: {
        currency: currency,
      },
      debounce: 2000,
    });

    if (r.message) {
      frm.custom.currency_symbol = r.message;
      return r.message;
    }
  } catch (e) {
    console.error("Error al obtener el símbolo de moneda:", e);
    frm.custom.currency_symbol = currency;
    return currency;
  }
}

erpnext.TransactionController.prototype.change_form_labels = async function (
  company_currency
) {
  let me = this;

  if (!me.frm.custom) {
    me.frm.custom = {};
  }

  if (!me.frm.custom.currency_symbol) {
    const currency = this.frm.doc.currency || company_currency;
    console.log("Currency:", currency);
    await get_currency_symbol(me.frm, currency);
  }

  this.frm.set_currency_labels(
    [
      "base_total",
      "base_net_total",
      "base_total_taxes_and_charges",
      "base_discount_amount",
      "base_grand_total",
      "base_rounded_total",
      "base_in_words",
      "base_taxes_and_charges_added",
      "base_taxes_and_charges_deducted",
      "total_amount_to_pay",
      "base_paid_amount",
      "base_write_off_amount",
      "base_change_amount",
      "base_operating_cost",
      "base_raw_material_cost",
      "base_total_cost",
      "base_scrap_material_cost",
      "base_rounding_adjustment",
    ],
    company_currency
  );

  this.frm.set_currency_labels(
    [
      "total",
      "net_total",
      "total_taxes_and_charges",
      "discount_amount",
      "grand_total",
      "taxes_and_charges_added",
      "taxes_and_charges_deducted",
      "tax_withholding_net_total",
      "rounded_total",
      "in_words",
      "paid_amount",
      "write_off_amount",
      "operating_cost",
      "scrap_material_cost",
      "rounding_adjustment",
      "raw_material_cost",
      "total_cost",
    ],
    me.frm.custom.currency_symbol
  );

  this.frm.set_currency_labels(
    ["outstanding_amount", "total_advance"],
    this.frm.doc.party_account_currency
  );

  this.frm.set_df_property(
    "conversion_rate",
    "description",
    "1 " + me.frm.custom.currency_symbol + " = [?] " + company_currency
  );

  if (
    this.frm.doc.price_list_currency &&
    this.frm.doc.price_list_currency != company_currency
  ) {
    this.frm.set_df_property(
      "plc_conversion_rate",
      "description",
      "1 " + me.frm.custom.currency_symbol + " = [?] " + company_currency
    );
  }

  // toggle fields
  this.frm.toggle_display(
    [
      "conversion_rate",
      "base_total",
      "base_net_total",
      "base_tax_withholding_net_total",
      "base_total_taxes_and_charges",
      "base_taxes_and_charges_added",
      "base_taxes_and_charges_deducted",
      "base_grand_total",
      "base_rounded_total",
      "base_in_words",
      "base_discount_amount",
      "base_paid_amount",
      "base_write_off_amount",
      "base_operating_cost",
      "base_raw_material_cost",
      "base_total_cost",
      "base_scrap_material_cost",
      "base_rounding_adjustment",
    ],
    this.frm.doc.currency != company_currency
  );

  this.frm.toggle_display(
    ["plc_conversion_rate", "price_list_currency"],
    this.frm.doc.price_list_currency != company_currency
  );

  let show =
    cint(this.frm.doc.discount_amount) ||
    (this.frm.doc.taxes || []).filter(function (d) {
      return d.included_in_print_rate === 1;
    }).length;

  if (
    this.frm.doc.doctype &&
    frappe.meta.get_docfield(this.frm.doc.doctype, "net_total")
  ) {
    this.frm.toggle_display("net_total", show);
  }

  if (
    this.frm.doc.doctype &&
    frappe.meta.get_docfield(this.frm.doc.doctype, "base_net_total")
  ) {
    this.frm.toggle_display(
      "base_net_total",
      show && me.frm.doc.currency != company_currency
    );
  }
};

erpnext.TransactionController.prototype.change_grid_labels = async function (
  company_currency
) {
  var me = this;

  if (!me.frm.custom) {
    me.frm.custom = {};
  }

  if (!me.frm.custom.currency_symbol) {
    const currency = this.frm.doc.currency || company_currency;
    await get_currency_symbol(me.frm, currency);
  }

  this.update_item_grid_labels(company_currency);

  this.toggle_item_grid_columns(company_currency);

  if (this.frm.doc.operations && this.frm.doc.operations.length > 0) {
    this.frm.set_currency_labels(
      ["operating_cost", "hour_rate"],
      this.frm.doc.currency,
      "operations"
    );
    this.frm.set_currency_labels(
      ["base_operating_cost", "base_hour_rate"],
      company_currency,
      "operations"
    );

    var item_grid = this.frm.fields_dict["operations"].grid;
    $.each(["base_operating_cost", "base_hour_rate"], function (i, fname) {
      if (frappe.meta.get_docfield(item_grid.doctype, fname))
        item_grid.set_column_disp(
          fname,
          me.frm.doc.currency != company_currency
        );
    });
  }

  if (this.frm.doc.scrap_items && this.frm.doc.scrap_items.length > 0) {
    this.frm.set_currency_labels(
      ["rate", "amount"],
      this.frm.doc.currency,
      "scrap_items"
    );
    this.frm.set_currency_labels(
      ["base_rate", "base_amount"],
      company_currency,
      "scrap_items"
    );

    var item_grid = this.frm.fields_dict["scrap_items"].grid;
    $.each(["base_rate", "base_amount"], function (i, fname) {
      if (frappe.meta.get_docfield(item_grid.doctype, fname))
        item_grid.set_column_disp(
          fname,
          me.frm.doc.currency != company_currency
        );
    });
  }

  if (this.frm.doc.taxes && this.frm.doc.taxes.length > 0) {
    this.frm.set_currency_labels(
      ["tax_amount", "total", "tax_amount_after_discount"],
      me.frm.custom.currency_symbol,
      "taxes"
    );

    this.frm.set_currency_labels(
      ["base_tax_amount", "base_total", "base_tax_amount_after_discount"],
      company_currency,
      "taxes"
    );
  }

  if (this.frm.doc.advances && this.frm.doc.advances.length > 0) {
    this.frm.set_currency_labels(
      ["advance_amount", "allocated_amount"],
      me.frm.custom.currency_symbol,
      "advances"
    );
  }

  this.update_payment_schedule_grid_labels(company_currency);
};
