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
    frm.custom.currency_symbol = currency;
    return currency;
  }
}

erpnext.TransactionController.prototype.company = function () {
  var me = this;
  var set_pricing = function () {
    if (me.frm.doc.company && me.frm.fields_dict.currency) {
      frappe.run_serially([
        // Se desactiva esa función para obtener automáticamente
        // la moneda de la lista de precios
        // () => get_party_currency()
        () => me.update_item_tax_map(),
        () => me.apply_default_taxes(),
        () => me.apply_pricing_rule(),
        () => set_terms(),
        () => set_letter_head(),
      ]);
    }
  };

  var get_party_currency = function () {
    if (me.is_a_mapped_document()) {
      return;
    }

    var party_type = frappe.meta.has_field(me.frm.doc.doctype, "customer")
      ? "Customer"
      : "Supplier";
    var party_name = me.frm.doc[party_type.toLowerCase()];
    if (party_name) {
      frappe.call({
        method: "frappe.client.get_value",
        args: {
          doctype: party_type,
          filters: { name: party_name },
          fieldname: "default_currency",
        },
        callback: function (r) {
          if (r.message) {
            set_currency(r.message.default_currency);
          }
        },
      });
    } else {
      set_currency();
    }
  };

  var set_currency = function (party_default_currency) {
    var company_currency = me.get_company_currency();
    var currency = party_default_currency || company_currency;
    if (me.frm.doc.currency != currency) {
      me.frm.set_value("currency", currency);
    }

    if (me.frm.doc.currency == company_currency) {
      me.frm.set_value("conversion_rate", 1.0);
    }
    if (me.frm.doc.price_list_currency == company_currency) {
      me.frm.set_value("plc_conversion_rate", 1.0);
    }

    me.frm.script_manager.trigger("currency");
  };

  var set_terms = function () {
    if (
      frappe.meta.has_field(me.frm.doc.doctype, "tc_name") &&
      !me.frm.doc.tc_name
    ) {
      var company_doc = frappe.get_doc(":Company", me.frm.doc.company);
      var selling_doctypes = [
        "Quotation",
        "Sales Order",
        "Delivery Note",
        "Sales Invoice",
      ];
      var company_terms_fieldname = selling_doctypes.includes(
        me.frm.doc.doctype
      )
        ? "default_selling_terms"
        : "default_buying_terms";
      if (company_doc && company_doc[company_terms_fieldname]) {
        me.frm.set_value("tc_name", company_doc[company_terms_fieldname]);
      }
    }
  };

  var set_letter_head = function () {
    if (me.frm.fields_dict.letter_head) {
      var company_doc = frappe.get_doc(":Company", me.frm.doc.company);
      if (company_doc && company_doc.default_letter_head) {
        me.frm.set_value("letter_head", company_doc.default_letter_head);
      }
    }
  };

  var set_party_account = function (set_pricing) {
    if (["Sales Invoice", "Purchase Invoice"].includes(me.frm.doc.doctype)) {
      if (me.frm.doc.doctype == "Sales Invoice") {
        var party_type = "Customer";
        var party_account_field = "debit_to";
      } else {
        var party_type = "Supplier";
        var party_account_field = "credit_to";
      }

      var party = me.frm.doc[frappe.model.scrub(party_type)];
      if (party && me.frm.doc.company) {
        return frappe.call({
          method: "erpnext.accounts.party.get_party_account",
          args: {
            company: me.frm.doc.company,
            party_type: party_type,
            party: party,
          },
          callback: function (r) {
            if (!r.exc && r.message) {
              me.frm.set_value(party_account_field, r.message);
              set_pricing();
            }
          },
        });
      } else {
        set_pricing();
      }
    } else {
      set_pricing();
    }
  };

  if (
    frappe.meta.get_docfield(this.frm.doctype, "shipping_address") &&
    ["Purchase Order", "Purchase Receipt", "Purchase Invoice"].includes(
      this.frm.doctype
    )
  ) {
    let is_drop_ship = me.frm.doc.items.some(
      (item) => item.delivered_by_supplier
    );

    if (!is_drop_ship) {
      erpnext.utils.get_shipping_address(this.frm, function () {
        set_party_account(set_pricing);
      });
    }
  } else {
    set_party_account(set_pricing);
  }

  if (this.frm.doc.company) {
    erpnext.last_selected_company = this.frm.doc.company;
  }
};

erpnext.TransactionController.prototype.change_form_labels = async function (
  company_currency
) {
  let me = this;

  if (!me.frm.custom) {
    me.frm.custom = {};
  }

  if (!me.frm.custom.currency_symbol) {
    const currency = this.frm.doc.currency || company_currency;
    await get_currency_symbol(me.frm, currency);
  }

  this.frm.set_currency_labels(
    [
      "base_total",
      "grand_total",
      "base_in_words",
      "base_net_total",
      "base_total_cost",
      "base_grand_total",
      "base_paid_amount",
      "base_rounded_total",
      "base_change_amount",
      "total_amount_to_pay",
      "base_operating_cost",
      "base_discount_amount",
      "base_write_off_amount",
      "base_raw_material_cost",
      "base_scrap_material_cost",
      "base_rounding_adjustment",
      "base_taxes_and_charges_added",
      "base_total_taxes_and_charges",
      "base_taxes_and_charges_deducted",
    ],
    company_currency
  );

  this.frm.set_currency_labels(
    [
      "total",
      "in_words",
      "net_total",
      "total_cost",
      "grand_total",
      "paid_amount",
      "rounded_total",
      "operating_cost",
      "discount_amount",
      "write_off_amount",
      "raw_material_cost",
      "scrap_material_cost",
      "rounding_adjustment",
      "total_taxes_and_charges",
      "taxes_and_charges_added",
      "tax_withholding_net_total",
      "taxes_and_charges_deducted",
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
      "base_total",
      "base_in_words",
      "base_net_total",
      "base_total_cost",
      "conversion_rate",
      "base_grand_total",
      "base_paid_amount",
      "base_rounded_total",
      "base_operating_cost",
      "base_discount_amount",
      "base_write_off_amount",
      "base_raw_material_cost",
      "base_scrap_material_cost",
      "base_rounding_adjustment",
      "base_total_taxes_and_charges",
      "base_taxes_and_charges_added",
      "base_taxes_and_charges_deducted",
    ],
    this.frm.doc.currency != company_currency
  );

  // `base_tax_withholding_net_total` sale de la lista de arriba a propósito. Es la base
  // sobre la que ERPNext calcula la retención (la suma de las líneas con apply_tds), que
  // en la práctica coincide con la base imponible salvo que se excluya alguna línea:
  // mostrarlo solo sumaba un monto repetido, con un rótulo traducido confuso ("Base
  // Imponible Retención Neta Total"), junto a campos que ya dicen lo mismo. Al no
  // togglearlo conserva el hidden=1 que trae de fábrica y no se muestra nunca.

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

    // Igual que los grids de arriba (operations / scrap_items) y el de ítems: las
    // columnas en moneda de la compañía solo tienen sentido si el documento está en
    // otra moneda. ERPNext rotula estas columnas pero nunca las alterna —solo alterna
    // las del grid de ítems—, así que el impuesto en Bs quedaba escondido dentro de la
    // fila. Los campos se declaran como columna (in_list_view) vía Property Setter.
    var taxes_grid = this.frm.fields_dict["taxes"].grid;
    $.each(
      ["base_tax_amount", "base_total", "base_tax_amount_after_discount"],
      function (i, fname) {
        if (frappe.meta.get_docfield(taxes_grid.doctype, fname))
          taxes_grid.set_column_disp(
            fname,
            me.frm.doc.currency != company_currency
          );
      }
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
