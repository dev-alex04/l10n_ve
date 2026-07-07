// ------------------------------------------------------------------ //
// Override del cálculo de impuestos para localización venezolana
// ------------------------------------------------------------------ //

const __VE_DOCTYPES_JS__ = [
  "Quotation",
  "Sales Order",
  "Sales Invoice",
  "Delivery Note",
  "VE Sales Credit Note",
  "VE Sales Debit Note",
  "Purchase Order",
  "Purchase Invoice",
  "Purchase Receipt",
  "VE Purchase Credit Note",
  "VE Purchase Debit Note",
];

// ------------------------------------------------------------------ //
// get_current_tax_amount — Override existente (tipos de cargo VE)
// ------------------------------------------------------------------ //

erpnext.taxes_and_totals.prototype.get_current_tax_amount = function (
  item,
  tax,
  item_tax_map,
) {
  var tax_rate = this._get_tax_rate(tax, item_tax_map);
  var current_tax_amount = 0.0;

  // To set row_id by default as previous row.
  if (
    ["On Previous Row Amount", "On Previous Row Total"].includes(
      tax.charge_type,
    )
  ) {
    if (tax.idx === 1) {
      frappe.throw(
        __(
          "Cannot select charge type as 'On Previous Row Amount' or 'On Previous Row Total' for first row",
        ),
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
    let tax_amount = 0;
    if (item.idx === 1) {
      let tax_base = (this.frm.doc.total * flt(tax.percentage_base)) / 100;
      tax_amount = (tax_base * tax.rate) / 100 - flt(tax.subtracting);
    }
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

  // ERPNext v15 destructures this as an Array `[current_tax_amount, item_tax_amount]`
  let res = new Number(current_tax_amount);
  res[Symbol.iterator] = function* () {
    yield current_tax_amount;
    yield current_tax_amount; // item_tax_amount
  };

  return res;
};

// ------------------------------------------------------------------ //
// set_cumulative_total — Override existente (retenciones VE)
// ------------------------------------------------------------------ //

erpnext.taxes_and_totals.prototype.set_cumulative_total = function (
  row_idx,
  tax,
) {
  var tax_amount = tax.tax_amount_after_discount_amount;

  let tax_base = 0;

  if (row_idx == 0) {
    tax_base = this.frm.doc.net_total;
  } else {
    tax_base = this.frm.doc["taxes"][row_idx - 1].total;
  }

  if (tax.is_tax_withholding_account) {
    //  Se resta la retención de IVA e ISLR

    if (
      ["VAT Withholding", "ISLR"].includes(tax.charge_type) &&
      __VE_DOCTYPES_JS__.includes(this.frm.doc.doctype)
    ) {
      //  Se asegura que la retención siempre reste, independientemente de su signo original
      tax.total = flt(tax_base - Math.abs(tax_amount), precision("total"));
    } else {
      tax.total = tax_base;
    }
  } else {
    tax.total = flt(tax_base + tax_amount, precision("total"));
  }
};

// ------------------------------------------------------------------ //
// calculate_taxes — Recálculo de montos base VEF (metodología VE)
// ------------------------------------------------------------------ //

const _original_calculate_taxes =
  erpnext.taxes_and_totals.prototype.calculate_taxes;

erpnext.taxes_and_totals.prototype.calculate_taxes = function () {
  _original_calculate_taxes.call(this);
  this._recalculate_base_tax_amounts_ve();
};

erpnext.taxes_and_totals.prototype._is_multicurrency = function () {
  if (!this.frm || !this.frm.doc.company) return false;
  const company_currency = frappe.get_doc(
    ":Company",
    this.frm.doc.company,
  )?.default_currency;
  return this.frm.doc.currency !== company_currency;
};

erpnext.taxes_and_totals.prototype._recalculate_base_tax_amounts_ve =
  function () {
    if (!this._is_multicurrency()) return;
    if (!this.frm.doc.taxes || !this.frm.doc.taxes.length) return;

    const conversion_rate = flt(this.frm.doc.conversion_rate);
    if (!conversion_rate) return;

    // Base imponible VEF (excluyendo ítems exentos)
    let base_taxable_vef = 0;
    (this.frm.doc.items || []).forEach((item) => {
      if (!item.vat_exempt) {
        base_taxable_vef += flt(item.base_net_amount);
      }
    });

    for (let i = 0; i < this.frm.doc.taxes.length; i++) {
      const tax = this.frm.doc.taxes[i];

      if (tax.charge_type === "VAT" && !tax.is_tax_withholding_account) {
        tax.base_tax_amount = flt(
          (base_taxable_vef * flt(tax.rate)) / 100,
          precision("base_tax_amount", tax),
        );
      } else if (tax.charge_type === "On Net Total") {
        tax.base_tax_amount = flt(
          (base_taxable_vef * flt(tax.rate)) / 100,
          precision("base_tax_amount", tax),
        );
      } else if (tax.charge_type === "VAT Withholding") {
        let total_vat_base = 0;
        for (let t of this.frm.doc.taxes) {
          if (t.charge_type === "VAT") {
            total_vat_base += flt(t.base_tax_amount);
          }
        }
        tax.base_tax_amount = flt(
          (total_vat_base * flt(tax.rate)) / 100,
          precision("base_tax_amount", tax),
        );
      } else if (tax.charge_type === "ISLR") {
        const base_islr_base =
          (flt(this.frm.doc.base_total) * flt(tax.percentage_base)) / 100;
        const base_islr =
          (base_islr_base * flt(tax.rate)) / 100 - flt(tax.subtracting);
        tax.base_tax_amount = flt(
          Math.max(base_islr, 0),
          precision("base_tax_amount", tax),
        );
      } else if (tax.charge_type === "On Previous Row Amount") {
        const prev_idx = cint(tax.row_id) - 1;
        if (prev_idx >= 0 && prev_idx < this.frm.doc.taxes.length) {
          const prev_tax = this.frm.doc.taxes[prev_idx];
          tax.base_tax_amount = flt(
            (prev_tax.base_tax_amount * flt(tax.rate)) / 100,
            precision("base_tax_amount", tax),
          );
        }
      } else if (tax.charge_type === "On Previous Row Total") {
        const prev_idx = cint(tax.row_id) - 1;
        if (prev_idx >= 0 && prev_idx < this.frm.doc.taxes.length) {
          const prev_tax = this.frm.doc.taxes[prev_idx];
          tax.base_tax_amount = flt(
            (prev_tax.base_total * flt(tax.rate)) / 100,
            precision("base_tax_amount", tax),
          );
        }
      }

      // Actualizar monto after discount proporcionalmente
      if (
        flt(tax.tax_amount) &&
        flt(tax.tax_amount) !== flt(tax.tax_amount_after_discount_amount)
      ) {
        const discount_ratio =
          flt(tax.tax_amount_after_discount_amount) / flt(tax.tax_amount);
        tax.base_tax_amount_after_discount_amount = flt(
          tax.base_tax_amount * discount_ratio,
          precision("base_tax_amount_after_discount_amount", tax),
        );
      } else {
        tax.base_tax_amount_after_discount_amount = tax.base_tax_amount;
      }

      // Recalcular base_total acumulado (misma lógica que set_cumulative_total)
      let base_tax_base = 0;
      if (i === 0) {
        base_tax_base = flt(this.frm.doc.base_net_total);
      } else {
        base_tax_base = this.frm.doc.taxes[i - 1].base_total;
      }

      let base_tax_for_total = tax.base_tax_amount_after_discount_amount;

      // Valuación: no suma al total
      if (tax.category === "Valuation") {
        base_tax_for_total = 0;
      }
      // Deducción: resta
      if (tax.add_deduct_tax === "Deduct") {
        base_tax_for_total *= -1;
      }

      if (tax.is_tax_withholding_account) {
        if (
          ["VAT Withholding", "ISLR"].includes(tax.charge_type) &&
          __VE_DOCTYPES_JS__.includes(this.frm.doc.doctype)
        ) {
          tax.base_total = flt(
            base_tax_base + base_tax_for_total,
            precision("base_total", tax),
          );
        } else {
          tax.base_total = base_tax_base;
        }
      } else {
        tax.base_total = flt(
          base_tax_base + base_tax_for_total,
          precision("base_total", tax),
        );
      }

      // Recalcular item_wise_tax_detail
      this._recalculate_item_wise_tax_detail_ve(tax, base_taxable_vef);
    }
  };

erpnext.taxes_and_totals.prototype._recalculate_item_wise_tax_detail_ve =
  function (tax, base_taxable_vef) {
    let tax_detail = tax.item_wise_tax_detail;

    if (typeof tax_detail === "string") {
      try {
        tax_detail = JSON.parse(tax_detail);
        tax.item_wise_tax_detail = tax_detail;
      } catch (e) {
        return;
      }
    }

    if (!tax_detail || typeof tax_detail !== "object") return;

    if (tax.charge_type === "VAT") {
      // Per-item: cada ítem no exento tiene su base_net_amount × rate
      const item_base_by_key = {};
      (this.frm.doc.items || []).forEach((item) => {
        if (item.vat_exempt) return;
        const key = item.item_code || item.item_name;
        item_base_by_key[key] =
          (item_base_by_key[key] || 0) + flt(item.base_net_amount);
      });

      for (const key in tax_detail) {
        const rate_info = tax_detail[key];
        if (!Array.isArray(rate_info) || rate_info.length < 2) continue;
        const base_amount = item_base_by_key[key] || 0;
        rate_info[1] = flt((base_amount * flt(rate_info[0])) / 100);
      }
    } else if (tax.charge_type === "On Net Total") {
      // Todo el impuesto va al primer key
      let assigned = false;
      for (const key in tax_detail) {
        const rate_info = tax_detail[key];
        if (!Array.isArray(rate_info) || rate_info.length < 2) continue;
        if (!assigned) {
          rate_info[1] = flt((base_taxable_vef * flt(rate_info[0])) / 100);
          assigned = true;
        } else {
          rate_info[1] = 0;
        }
      }
    }
  };

// ------------------------------------------------------------------ //
// calculate_totals — Recálculo de base_grand_total VE
// ------------------------------------------------------------------ //

const _original_calculate_totals =
  erpnext.taxes_and_totals.prototype.calculate_totals;

erpnext.taxes_and_totals.prototype.calculate_totals = function () {
  _original_calculate_totals.call(this);

  // Recalcular Total Base + IVA en cada cambio de montos (qty, rate, etc.)
  calculate_base_total_with_vat(this.frm);

  if (!this._is_multicurrency()) return;

  if (this.frm.doc.taxes && this.frm.doc.taxes.length) {
    const last_tax = this.frm.doc.taxes[this.frm.doc.taxes.length - 1];
    this.frm.doc.base_grand_total = flt(
      last_tax.base_total,
      precision("base_grand_total"),
    );
  }

  this.frm.doc.base_total_taxes_and_charges = flt(
    this.frm.doc.base_grand_total - this.frm.doc.base_net_total,
    precision("base_total_taxes_and_charges"),
  );

  if (
    frappe.meta.get_docfield(
      this.frm.doc.doctype,
      "rounded_total",
      this.frm.doc.name,
    )
  ) {
    this.frm.doc.base_rounded_total = flt(
      this.frm.doc.base_grand_total,
      precision("base_rounded_total"),
    );
    this.frm.doc.base_rounding_adjustment = 0;
  }
};

// ------------------------------------------------------------------ //
// calculate_outstanding_amount — Override para NC/ND venezolanas
// ------------------------------------------------------------------ //

const _original_calculate_outstanding_amount =
  erpnext.taxes_and_totals.prototype.calculate_outstanding_amount;

erpnext.taxes_and_totals.prototype.calculate_outstanding_amount = function (
  update_paid_amount,
) {
  const ve_invoice_doctypes = [
    "VE Sales Credit Note",
    "VE Sales Debit Note",
    "VE Purchase Credit Note",
    "VE Purchase Debit Note",
  ];

  if (!ve_invoice_doctypes.includes(this.frm.doc.doctype)) {
    return _original_calculate_outstanding_amount.call(
      this,
      update_paid_amount,
    );
  }

  // No calcular para documentos ya aprobados (se calcula desde GL entries)
  if (this.frm.doc.docstatus > 0) return;

  frappe.model.round_floats_in(this.frm.doc, [
    "grand_total",
    "total_advance",
    "write_off_amount",
  ]);

  let grand_total = this.frm.doc.rounded_total || this.frm.doc.grand_total;
  let base_grand_total =
    this.frm.doc.base_rounded_total || this.frm.doc.base_grand_total;

  let total_amount_to_pay;
  if (this.frm.doc.party_account_currency == this.frm.doc.currency) {
    total_amount_to_pay = flt(
      grand_total - this.frm.doc.total_advance,
      precision("grand_total"),
    );
  } else {
    total_amount_to_pay = flt(
      flt(base_grand_total, precision("base_grand_total")) -
        this.frm.doc.total_advance,
      precision("base_grand_total"),
    );
  }

  this.frm.doc.outstanding_amount = flt(
    total_amount_to_pay,
    precision("outstanding_amount"),
  );
};

// ------------------------------------------------------------------ //
// Override de calculate_taxes_and_totals
// ------------------------------------------------------------------ //

const _original_calculate_taxes_and_totals =
  erpnext.taxes_and_totals.prototype.calculate_taxes_and_totals;

erpnext.taxes_and_totals.prototype.calculate_taxes_and_totals = async function (
  update_paid_amount,
) {
  await _original_calculate_taxes_and_totals.call(this, update_paid_amount);

  const ve_invoice_doctypes = [
    "VE Sales Credit Note",
    "VE Sales Debit Note",
    "VE Purchase Credit Note",
    "VE Purchase Debit Note",
  ];
  if (
    ve_invoice_doctypes.includes(this.frm.doc.doctype) &&
    this.frm.doc.docstatus < 2
  ) {
    this.calculate_total_advance(update_paid_amount);
  }
};

// ------------------------------------------------------------------ //

function recalculate_ve_document(frm) {
  // Aplica para VE Sales Credit Note y VE Sales Debit Note
  // Usado por VE Sales Credit Note Item y VE Sales Debit Note Item
  try {
    if (frm.cscript && frm.cscript.calculate_taxes_and_totals) {
      frm.cscript.calculate_taxes_and_totals();
    } else {
      const calc = new erpnext.taxes_and_totals({ frm: frm });
      // Fallback methods que taxes_and_totals espera del TransactionController
      calc.get_company_currency = function () {
        return erpnext.get_currency(this.frm.doc.company);
      };
      calc.shipping_rule = function () {
        return Promise.resolve();
      };

      // Fallback variables
      if (!frappe.flags.round_off_applicable_accounts) {
        frappe.flags.round_off_applicable_accounts = [];
      }

      calc
        .calculate_taxes_and_totals()
        .then(() => {
          frm.refresh_fields();
        })
        .catch((e) => {
          console.error("Error en calculate_taxes_and_totals async:", e);
        });
    }
  } catch (err) {
    console.error("Error en recalculate_ve_document:", err);
  }
}

// ------------------------------------------------------------------ //
// Cálculo del campo "Total Base + IVA (Bs)" — usado por SI, NC y ND
// ------------------------------------------------------------------ //

/**
 * Asigna el Total Base + IVA en moneda de la compañía (Bs).
 * Toma el valor de base_total de la fila con charge_type === 'VAT',
 * que ya fue calculado por ERPNext (base_net_total + IVA).
 * Si no hay IVA, usa base_net_total como fallback.
 * @param {object} frm - Instancia del formulario (Sales Invoice, NC o ND)
 */
function calculate_base_total_with_vat(frm) {
  let result = flt(frm.doc.base_net_total);

  for (const tax_row of frm.doc.taxes || []) {
    if (tax_row.charge_type === "VAT") {
      result = flt(tax_row.base_total);
      break;
    }
  }

  frm.doc.base_total_with_vat = result;
  frm.refresh_field("base_total_with_vat");
}

// ------------------------------------------------------------------ //
// Método de cálculo de impuestos (Venezuela Account Settings)
// "Desde el total de la factura": ancla el carril Bs al total comercial
// redondeado x tasa. Espejo de _anchor_item_base_amounts_ve (Python) —
// mantener en sync. Los precios y plantillas NO cambian.
// ------------------------------------------------------------------ //

const __ve_original_calculate_net_total =
  erpnext.taxes_and_totals.prototype.calculate_net_total;

erpnext.taxes_and_totals.prototype.calculate_net_total = function () {
  this._anchor_item_base_amounts_ve();
  __ve_original_calculate_net_total.apply(this);
};

erpnext.taxes_and_totals.prototype._anchor_item_base_amounts_ve = function () {
  if (!this._is_multicurrency()) return;

  // El método viaja en el boot (se refresca al recargar la página)
  if (frappe.boot.tax_calculation_method !== "Desde el total de la factura") {
    return;
  }

  const conversion_rate = flt(this.frm.doc.conversion_rate);
  if (!conversion_rate) return;

  // Tasa de IVA efectiva del documento (filas VAT aditivas, no retención)
  let vat_rate = 0;
  (this.frm.doc.taxes || []).forEach((tax) => {
    if (
      tax.charge_type === "VAT" &&
      !cint(tax.is_tax_withholding_account) &&
      (tax.add_deduct_tax || "Add") !== "Deduct" &&
      (tax.category || "Total") !== "Valuation"
    ) {
      vat_rate += flt(tax.rate);
    }
  });
  if (!vat_rate) return;

  const factor = 1 + vat_rate / 100.0;

  (this.frm.doc.items || []).forEach((item) => {
    if (cint(item.vat_exempt)) return;

    [
      ["amount", "base_amount", "base_rate"],
      ["net_amount", "base_net_amount", "base_net_rate"],
    ].forEach(([src, base_field, base_rate_field]) => {
      const amount_usd = flt(item[src]);
      // Total comercial del ítem redondeado (25,86 x 1,16 = 29,9976 -> 30,00)
      const total_usd = flt(amount_usd * factor, precision(src, item));
      const total_bs = flt(total_usd * conversion_rate, precision(base_field, item));
      item[base_field] = flt(total_bs / factor, precision(base_field, item));
      if (item.qty) {
        item[base_rate_field] = flt(
          item[base_field] / item.qty,
          precision(base_rate_field, item),
        );
      }
    });
  });
};
