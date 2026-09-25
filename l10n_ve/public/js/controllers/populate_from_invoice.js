/**
 * populate_from_invoice.js
 *
 * Utilidad compartida para NC (VE Sales Credit Note) y ND (VE Sales Debit Note).
 * Extrae los datos de la factura original (Sales Invoice) seleccionada en
 * `return_against` y los aplica al formulario actual.
 *
 * Uso en el doctype JS:
 *   return_against: function (frm) {
 *     populate_from_sales_invoice(frm);
 *   }
 */

/**
 * Enlace a la factura original de una nota, rotulado con su número de factura (bill_no).
 *
 * El ID interno (ACC-SINV-…, ACC-PINV-…) no le dice nada a quien lee el aviso: la factura
 * se conoce por su número. El ID solo se muestra si la factura todavía no tiene número.
 *
 * @param {string} doctype - "Sales Invoice" o "Purchase Invoice"
 * @param {string} name - ID de la factura original (return_against)
 * @returns {Promise<string>} HTML del enlace
 */
function original_invoice_link(doctype, name) {
  const route = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
  return frappe.db.get_value(doctype, name, "bill_no").then((r) => {
    const number = r && r.message && r.message.bill_no;
    const label = number
      ? __("N° {0}", [frappe.utils.escape_html(number)])
      : frappe.utils.escape_html(name);
    return `<a href="${route}">${label}</a>`;
  });
}

function populate_from_sales_invoice(frm) {
  if (!frm.doc.return_against) return;

  frappe.call({
    method: "frappe.client.get",
    args: { doctype: "Sales Invoice", name: frm.doc.return_against },
    callback: function (r) {
      if (!r.message) return;
      const si = r.message;

      _set_header_fields(frm, si);
      _set_items(frm, si);
      _set_taxes(frm, si);
      _set_totals(frm, si);

      recalculate_ve_document(frm);

      frappe.show_alert({
        message: __("Ítems cargados desde {0}", [frm.doc.return_against]),
        indicator: "blue",
      });
    },
  });
}

/**
 * Copia los campos del encabezado desde la SI al formulario.
 *
 * La tasa se copia para ambas notas: en la NC es invariante (el servidor la
 * re-aplica en cada validate y el campo va read_only) y en la ND es solo el
 * valor por defecto, que el usuario puede reexpresar cambiando posting_date.
 * El read_only lo fija el refresh de cada doctype, no este controlador.
 */
function _set_header_fields(frm, si) {
  if (si.customer && !frm.doc.customer) {
    frm.set_value("customer", si.customer);
  }

  if (si.branch) {
    frm.set_value("branch", si.branch);
  }

  if (si.debit_to) {
    frm.set_value("debit_to", si.debit_to);
  }

  if (si.taxes_and_charges) {
    frm.set_value("taxes_and_charges", si.taxes_and_charges);
  }

  if (si.currency) {
    frm.set_value("currency", si.currency);
  }
  if (si.selling_price_list) {
    frm.set_value("selling_price_list", si.selling_price_list);
  }
  if (si.price_list_currency) {
    frm.set_value("price_list_currency", si.price_list_currency);
  }

  if (si.conversion_rate) {
    frm.set_value("conversion_rate", si.conversion_rate);
  }
  if (si.plc_conversion_rate) {
    frm.set_value("plc_conversion_rate", si.plc_conversion_rate);
  }
}

/**
 * Copia los ítems desde la SI al formulario en valores absolutos (positivos).
 */
function _set_items(frm, si) {
  frm.clear_table("items");

  (si.items || []).forEach(function (item) {
    let row = frm.add_child("items");

    row.item_code = item.item_code;
    row.item_name = item.item_name;
    row.description = item.description;
    row.uom = item.uom;
    row.stock_uom = item.stock_uom;
    row.income_account = item.income_account;
    row.cost_center = item.cost_center;
    row.warehouse = item.warehouse;
    row.sales_invoice_item = item.name;

    row.qty = Math.abs(item.qty);
    row.stock_qty = Math.abs(item.stock_qty || item.qty);
    row.rate = Math.abs(item.rate);

    row.uom_conversion_factor = item.uom_conversion_factor || 1;
    row.conversion_factor = item.conversion_factor || 1;
    row.amount = Math.abs(item.amount || item.qty * item.rate);
    row.base_rate = Math.abs(item.base_rate || item.rate);
    row.base_amount = Math.abs(item.base_amount || item.amount);
    row.net_rate = Math.abs(item.net_rate || item.rate);
    row.net_amount = Math.abs(item.net_amount || item.amount);
    row.base_net_rate = Math.abs(
      item.base_net_rate || item.base_rate || item.rate,
    );
    row.base_net_amount = Math.abs(
      item.base_net_amount || item.base_amount || item.amount,
    );

    row.item_tax_template = item.item_tax_template;
    row.tax_rate = item.tax_rate;
    row.vat_exempt = item.vat_exempt || 0;
  });

  frm.refresh_field("items");
}

/**
 * Copia los totales del encabezado desde la SI.
 * El servidor los recalcula en validate(), pero el cliente los necesita
 * para pasar la validación de campos obligatorios.
 */
function _set_totals(frm, si) {
  frm.doc.grand_total = Math.abs(si.grand_total || 0);
  frm.doc.base_grand_total = Math.abs(si.base_grand_total || 0);
  frm.doc.net_total = Math.abs(si.net_total || 0);
  frm.doc.base_net_total = Math.abs(si.base_net_total || 0);
  frm.doc.total = Math.abs(si.total || 0);
  frm.doc.base_total = Math.abs(si.base_total || 0);
  frm.doc.total_taxes_and_charges = Math.abs(
    si.total_taxes_and_charges || 0,
  );
  frm.doc.base_total_taxes_and_charges = Math.abs(
    si.base_total_taxes_and_charges || 0,
  );
  frm.doc.outstanding_amount = 0;
}

/**
 * Copia los impuestos (incluyendo retenciones) desde la SI al formulario.
 */
function _set_taxes(frm, si) {
  frm.clear_table("taxes");

  (si.taxes || []).forEach(function (tax) {
    let row = frm.add_child("taxes");

    row.charge_type = tax.charge_type;
    row.account_head = tax.account_head;
    row.description = tax.description;
    row.included_in_print_rate = tax.included_in_print_rate || 0;
    row.cost_center = tax.cost_center;
    row.rate = tax.rate || 0;

    row.tax_amount = Math.abs(tax.tax_amount || 0);
    row.base_tax_amount = Math.abs(tax.base_tax_amount || 0);
    row.tax_amount_after_discount_amount = Math.abs(
      tax.tax_amount_after_discount_amount || tax.tax_amount || 0
    );
    row.base_tax_amount_after_discount_amount = Math.abs(
      tax.base_tax_amount_after_discount_amount || tax.base_tax_amount || 0
    );

    row.total = Math.abs(tax.total || 0);
    row.base_total = Math.abs(tax.base_total || 0);

    row.is_tax_withholding_account = tax.is_tax_withholding_account || 0;
    row.percentage_base = tax.percentage_base;
    row.subtracting = tax.subtracting;
  });

  frm.refresh_field("taxes");
}
