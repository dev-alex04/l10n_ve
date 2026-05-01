// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Purchase Credit Note", {
  onload: function (frm) {
    // Solo PIs aprobadas, sin NC previa, de la misma empresa y proveedor
    frm.set_query("return_against", function () {
      return {
        query:
          "l10n_ve.l10n_ve.doctype.ve_purchase_credit_note.ve_purchase_credit_note.query_available_purchase_invoices",
        filters: {
          company: frm.doc.company,
          supplier: frm.doc.supplier || "",
        },
      };
    });

    // Cuenta AP: solo tipo Payable
    frm.set_query("credit_to", function () {
      return {
        filters: {
          account_type: "Payable",
          is_group: 0,
          company: frm.doc.company,
        },
      };
    });
  },

  refresh: function (frm) {
    calculate_base_total_with_vat(frm);

    // Vista previa del asiento contable
    erpnext.accounts.ledger_preview.show_accounting_ledger_preview(frm);

    // Banner azul: enlace a la PI original (pendiente)
    if (frm.doc.return_against && !frm.doc.bill_no) {
      frm.set_intro(
        __("Nota de Crédito aplicada a la factura: {0}", [
          `<a href="/app/purchase-invoice/${frm.doc.return_against}">${frm.doc.return_against}</a>`,
        ]),
        "blue",
      );
    }

    // Botón rápido: ir a la factura original (solo documentos guardados)
    if (
      frm.doc.docstatus >= 0 &&
      frm.doc.return_against &&
      !frm.doc.__islocal
    ) {
      frm.add_custom_button(__("Ver Factura Original"), function () {
        frappe.set_route("Form", "Purchase Invoice", frm.doc.return_against);
      });
    }

    // ── Grupo "Ver": asiento contable (docstatus >= 1) ─────────────────────
    if (frm.doc.docstatus >= 1) {
      frm.add_custom_button(
        __("Asiento Contable"),
        function () {
          frappe.route_options = {
            voucher_no: frm.doc.name,
            from_date: frm.doc.posting_date,
            to_date: frm.doc.posting_date,
            company: frm.doc.company,
            show_cancelled_entries: frm.doc.docstatus === 2,
          };
          frappe.set_route("query-report", "General Ledger");
        },
        __("Ver"),
      );
    }
  },

  // Al seleccionar la factura original: auto-poblar datos desde la PI
  return_against: function (frm) {
    if (!frm.doc.return_against) {
      return;
    }

    frappe.call({
      method: "frappe.client.get",
      args: {
        doctype: "Purchase Invoice",
        name: frm.doc.return_against,
      },
      callback: function (r) {
        if (!r.message) return;
        const pi = r.message;

        // Datos del proveedor
        frm.set_value("supplier", pi.supplier);
        frm.set_value("supplier_name", pi.supplier_name);
        frm.set_value("supplier_address", pi.supplier_address);

        // Cuenta y moneda
        frm.set_value("credit_to", pi.credit_to);
        frm.set_value("currency", pi.currency);
        frm.set_value("conversion_rate", pi.conversion_rate);
        frm.set_value("plc_conversion_rate", pi.plc_conversion_rate);
        frm.set_value("buying_price_list", pi.buying_price_list);
        frm.set_value("price_list_currency", pi.price_list_currency);

        // Fechas
        frm.set_value("posting_date", pi.posting_date);

        // Nro. Factura Afectada
        frm.set_value("affected_invoice_number", pi.bill_no || "");

        // Taxes and charges template
        frm.set_value("taxes_and_charges", pi.taxes_and_charges);

        // Copiar ítems (todos en positivo)
        frm.clear_table("items");
        (pi.items || []).forEach(function (item) {
          const new_item = frm.add_child("items");
          // Copiar campos clave del ítem
          const fields_to_copy = [
            "item_code",
            "item_name",
            "description",
            "item_group",
            "qty",
            "uom",
            "stock_uom",
            "conversion_factor",
            "rate",
            "price_list_rate",
            "base_rate",
            "base_amount",
            "amount",
            "net_rate",
            "net_amount",
            "base_net_rate",
            "base_net_amount",
            "warehouse",
            "expense_account",
            "cost_center",
            "project",
            "income_account",
            "discount_percentage",
            "discount_amount",
            "is_fixed_asset",
            "asset_category",
            "vat_exempt",
          ];
          fields_to_copy.forEach(function (field) {
            if (item[field] !== undefined && item[field] !== null) {
              new_item[field] = Math.abs(item[field]) || item[field];
              // Solo aplicar abs a números
              if (typeof item[field] === "number") {
                new_item[field] = Math.abs(item[field]);
              } else {
                new_item[field] = item[field];
              }
            }
          });
        });
        frm.refresh_field("items");

        // Copiar impuestos (sin retenciones, que se agregarán vía controller)
        frm.clear_table("taxes");
        (pi.taxes || []).forEach(function (tax) {
          // Solo copiar impuestos base (no retenciones)
          if (tax.is_tax_withholding_account) return;

          const new_tax = frm.add_child("taxes");
          const tax_fields = [
            "charge_type",
            "account_head",
            "description",
            "rate",
            "tax_amount",
            "total",
            "base_tax_amount",
            "base_total",
            "cost_center",
            "category",
            "add_deduct_tax",
            "included_in_print_rate",
            "included_in_paid_amount",
            "is_tax_withholding_account",
          ];
          tax_fields.forEach(function (field) {
            if (tax[field] !== undefined && tax[field] !== null) {
              new_tax[field] = tax[field];
            }
          });
        });
        frm.refresh_field("taxes");

        // Recalcular totales
        frm.trigger("calculate_taxes_and_totals");
      },
    });
  },
});

// ------------------------------------------------------------------ //
// Child table: recálculo al cambiar qty, rate o descuento
// ------------------------------------------------------------------ //

frappe.ui.form.on("VE Purchase Credit Note Item", {
  qty(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
  rate(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
  price_list_rate(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
  discount_percentage(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
  discount_amount(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
  items_remove(frm) {
    frm.trigger("calculate_taxes_and_totals");
  },
});
