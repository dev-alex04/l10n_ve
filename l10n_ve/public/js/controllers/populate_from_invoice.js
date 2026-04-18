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
      _set_totals(frm, si);

      frappe.show_alert({
        message: __("Ítems cargados desde {0}", [frm.doc.return_against]),
        indicator: "blue",
      });
    },
  });
}

/**
 * Copia los campos del encabezado desde la SI al formulario.
 */
function _set_header_fields(frm, si) {
  if (si.customer && !frm.doc.customer) {
    frm.set_value("customer", si.customer);
  }

  if (si.posting_date) {
    frm.set_value("posting_date", si.posting_date);
  }
  if (si.due_date) {
    frm.set_value("due_date", si.due_date);
  }

  if (si.branch) {
    frm.set_value("branch", si.branch);
    frm.set_df_property("branch", "read_only", 1);
  } else {
    frm.set_df_property("branch", "read_only", 0);
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
