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

  before_save: function (frm) {
    // stock_qty es reqd en Purchase Invoice Item.
    (frm.doc.items || []).forEach(function (item) {
      if (!flt(item.conversion_factor)) {
        item.conversion_factor = 1;
      }
      item.stock_qty = flt(item.qty) * flt(item.conversion_factor);
    });
  },
  refresh: function (frm) {
    calculate_base_total_with_vat(frm);
    set_islr_buttons(frm);

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
            "stock_qty",
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
              if (typeof item[field] === "number") {
                new_item[field] = Math.abs(item[field]);
              } else {
                new_item[field] = item[field];
              }
            }
          });

          // stock_qty es reqd en Purchase Invoice Item
          if (!flt(new_item.conversion_factor)) {
            new_item.conversion_factor = 1;
          }
          new_item.stock_qty =
            flt(new_item.qty) * flt(new_item.conversion_factor);
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
  qty(frm, cdt, cdn) {
    // stock_qty es reqd en Purchase Invoice Item
    const row = locals[cdt][cdn];
    row.stock_qty = flt(row.qty) * flt(row.conversion_factor || 1);
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

// ------------------------------------------------------------------ //
// ISLR — Botones y diálogo para asignación manual de retención       //
// ------------------------------------------------------------------ //

function set_islr_buttons(frm) {
  if (frm.doc.docstatus !== 0 || frm.is_new() || !frm.doc.supplier) {
    return;
  }

  const has_islr = (frm.doc.taxes || []).some(
    (tax) => tax.charge_type === "ISLR",
  );

  frm.add_custom_button(
    __("Agregar ISLR"),
    function () {
      show_islr_dialog(frm);
    },
    __("Retenciones"),
  );

  if (has_islr) {
    frm.add_custom_button(
      __("Eliminar ISLR"),
      function () {
        frappe.confirm(
          "¿Está seguro de eliminar todas las retenciones de ISLR?",
          () => {
            frappe.dom.freeze("Eliminando retenciones ISLR...");
            frm
              .call("remove_islr_concept")
              .then(() => {
                frappe.dom.unfreeze();
                frm.reload_doc();
              })
              .catch(() => {
                frappe.dom.unfreeze();
              });
          },
        );
      },
      __("Retenciones"),
    );
  }
}

function show_islr_dialog(frm) {
  frappe.db
    .get_value("Supplier", frm.doc.supplier, "type_of_person")
    .then((r) => {
      const type_of_person = r.message.type_of_person;

      if (!type_of_person) {
        frappe.msgprint({
          title: __("Configuración faltante"),
          message: __(
            "El proveedor <b>{0}</b> no tiene configurado el Tipo de Persona. " +
              "Configúrelo antes de asignar retención de ISLR.",
            [frm.doc.supplier_name || frm.doc.supplier],
          ),
          indicator: "red",
        });
        return;
      }

      const type_of_person_label = __(type_of_person);

      const existing_codes = (frm.doc.taxes || [])
        .filter((tax) => tax.charge_type === "ISLR" && tax.code)
        .map((tax) => tax.code);

      const dialog = new frappe.ui.Dialog({
        title: __("Agregar Retención de ISLR"),
        fields: [
          {
            fieldtype: "HTML",
            fieldname: "islr_info",
            options: `
              <div style="padding: 10px 12px; margin-bottom: 12px;
                          border: 1px solid var(--border-color);
                          border-radius: var(--border-radius);
                          background: var(--bg-color);">
                <div style="margin-bottom: 4px;">
                  <strong>Proveedor:</strong> ${frm.doc.supplier_name || frm.doc.supplier}
                </div>
                <div style="margin-bottom: 4px;">
                  <strong>Tipo de Persona:</strong> ${type_of_person_label}
                </div>
                <div>
                  <strong>Base Imponible:</strong>
                  ${frappe.format(frm.doc.total, { fieldtype: "Currency" })}
                </div>
              </div>
            `,
          },
          {
            fieldtype: "Link",
            fieldname: "tabulator_islr",
            label: __("Concepto ISLR"),
            options: "Tabulator ISLR",
            reqd: 1,
            get_query: function () {
              return {
                query:
                  "l10n_ve.overrides.purchase_invoice.get_tabulators_by_person_type",
                filters: {
                  type_of_person: type_of_person,
                  existing_codes: existing_codes,
                },
              };
            },
          },
          {
            fieldtype: "Section Break",
            fieldname: "preview_section",
            label: __("Vista previa del cálculo"),
            depends_on: "eval:doc.tabulator_islr",
          },
          {
            fieldtype: "HTML",
            fieldname: "calculation_preview",
          },
        ],
        primary_action_label: __("Aplicar Retención"),
        primary_action(values) {
          if (!values.tabulator_islr) {
            frappe.msgprint(__("Debe seleccionar un concepto de ISLR."));
            return;
          }

          dialog.hide();
          frappe.dom.freeze(__("Calculando retención de ISLR..."));

          frm
            .call("set_islr_concept", {
              tabulator_name: values.tabulator_islr,
            })
            .then(() => {
              frappe.dom.unfreeze();
              frm.reload_doc();
            })
            .catch(() => {
              frappe.dom.unfreeze();
              frappe.msgprint({
                title: __("Error"),
                message: __(
                  "Ocurrió un error al calcular la retención. " +
                    "Verifique la configuración del tabulador e intente nuevamente.",
                ),
                indicator: "red",
              });
            });
        },
      });

      dialog.fields_dict.tabulator_islr.$input.on("change", function () {
        update_islr_preview(dialog, frm, type_of_person);
      });
      dialog.fields_dict.tabulator_islr.df.onchange = function () {
        update_islr_preview(dialog, frm, type_of_person);
      };

      dialog.show();
    });
}

function update_islr_preview(dialog, frm, type_of_person) {
  const tabulator_name = dialog.get_value("tabulator_islr");
  const preview_field = dialog.fields_dict.calculation_preview;

  if (!tabulator_name) {
    preview_field.$wrapper.html("");
    return;
  }

  frappe.call({
    method: "frappe.client.get",
    args: {
      doctype: "Tabulator ISLR",
      name: tabulator_name,
    },
    callback: function (r) {
      if (!r.message) return;

      const tabulator = r.message;
      const aliquot_info = (tabulator.aliquot || []).find(
        (aq) => aq.types_of_person === type_of_person && flt(aq.aliquot) > 0,
      );

      if (!aliquot_info) {
        preview_field.$wrapper.html(`
          <div style="padding: 10px 12px;
                      border: 1px solid var(--border-color);
                      border-radius: var(--border-radius);
                      background: var(--bg-color);
                      color: var(--orange-500);">
            No se encontró alícuota para el tipo de persona
            <b>${__(type_of_person)}</b> en este tabulador.
          </div>
        `);
        return;
      }

      const base_amount = flt(frm.doc.total);
      const tax_base = flt(
        (base_amount * flt(aliquot_info.percentage_base)) / 100,
        2,
      );
      const islr_amount = flt(
        (tax_base * flt(aliquot_info.aliquot)) / 100 -
          flt(aliquot_info.subtracting),
        2,
      );

      const amount_formatted = frappe.format(Math.max(islr_amount, 0), {
        fieldtype: "Currency",
      });

      preview_field.$wrapper.html(`
        <div style="padding: 10px 12px;
                    border: 1px solid var(--border-color);
                    border-radius: var(--border-radius);
                    background: var(--bg-color);">
          <table style="width: 100%;">
            <tr>
              <td><strong>Código:</strong></td>
              <td>${tabulator.codigo}</td>
            </tr>
            <tr>
              <td><strong>Descripción:</strong></td>
              <td>${tabulator.descripcion}</td>
            </tr>
            <tr>
              <td><strong>Base imponible:</strong></td>
              <td>${frappe.format(base_amount, { fieldtype: "Currency" })}</td>
            </tr>
            <tr>
              <td><strong>% Base:</strong></td>
              <td>${flt(aliquot_info.percentage_base)}%</td>
            </tr>
            <tr>
              <td><strong>Base fiscal:</strong></td>
              <td>${frappe.format(tax_base, { fieldtype: "Currency" })}</td>
            </tr>
            <tr>
              <td><strong>Alícuota:</strong></td>
              <td>${flt(aliquot_info.aliquot)}%</td>
            </tr>
            <tr>
              <td><strong>Sustraendo:</strong></td>
              <td>${frappe.format(flt(aliquot_info.subtracting), { fieldtype: "Currency" })}</td>
            </tr>
            <tr style="border-top: 2px solid var(--text-muted); font-size: 1.1em;">
              <td><strong>Retención ISLR:</strong></td>
              <td><strong>${amount_formatted}</strong></td>
            </tr>
          </table>
        </div>
      `);
    },
  });
}
