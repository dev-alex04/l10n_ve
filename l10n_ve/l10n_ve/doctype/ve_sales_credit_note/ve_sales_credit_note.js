// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Sales Credit Note", {
  onload: function (frm) {
    // NC nunca requiere fecha de vencimiento
    frm.toggle_reqd("due_date", false);

    // Solo SI aprobadas, sin NC/ND previa, de la misma empresa y cliente
    frm.set_query("return_against", function () {
      return {
        query:
          "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.query_available_sales_invoices",
        filters: {
          company: frm.doc.company,
          customer: frm.doc.customer || "",
        },
      };
    });

    // Cuenta AR: solo tipo Receivable
    frm.set_query("debit_to", function () {
      return {
        filters: {
          account_type: "Receivable",
          is_group: 0,
          company: frm.doc.company,
        },
      };
    });
  },

  refresh: function (frm) {
    frm.toggle_reqd("due_date", false);

    // Vista previa del asiento contable (idéntica a Factura de Venta)
    // Solo disponible en borradores ya guardados — usa el mismo motor
    // que la SI nativa: make_gl_entries() con rollback automático
    erpnext.accounts.ledger_preview.show_accounting_ledger_preview(frm);

    // Banner azul: enlace a la SI original (pendiente de emisión HKA)
    if (frm.doc.return_against && !frm.doc.bill_no) {
      frm.set_intro(
        __("Nota de Crédito aplicada a la factura: {0}", [
          `<a href="/app/sales-invoice/${frm.doc.return_against}">${frm.doc.return_against}</a>`,
        ]),
        "blue",
      );
    }

    // Banner verde: NC emitida en HKA (solo documentos activos/submit)
    if (frm.doc.bill_no && frm.doc.docstatus === 1) {
      frm.set_intro(
        __(
          "✅ Emitida ante HKA con número: <b>{0}</b> | Factura original: {1}",
          [
            frm.doc.bill_no,
            `<a href="/app/sales-invoice/${frm.doc.return_against}">${frm.doc.return_against}</a>`,
          ],
        ),
        "green",
      );
    }

    // Banner rojo: NC anulada en HKA — bloquear Amend
    if (frm.doc.bill_no && frm.doc.docstatus === 2) {
      frm.set_intro(
        __(
          "🚫 Esta Nota de Crédito fue <b>anulada ante HKA</b> (N° {0}). " +
            "No puede ser corregida ni enmendada. " +
            "Cree una nueva Nota de Crédito si es necesario.",
          [frm.doc.bill_no],
        ),
        "red",
      );
      // Frappe adds "Amend" as the primary button for cancelled docs.
      // Hide it so the user cannot amend a document already voided in HKA.
      frm.page.btn_primary.hide();
    }

    // Botón rápido: ir a la factura original (solo documentos guardados)
    if (
      frm.doc.docstatus >= 0 &&
      frm.doc.return_against &&
      !frm.doc.__islocal
    ) {
      frm.add_custom_button(__("Ver Factura Original"), function () {
        frappe.set_route("Form", "Sales Invoice", frm.doc.return_against);
      });
    }

    // Botón: generar borrador de factura de reemplazo
    // Visible solo cuando la NC está aprobada y tiene factura original vinculada.
    if (frm.doc.docstatus === 1 && frm.doc.return_against) {
      frm.add_custom_button(__("Generar Factura de Reemplazo"), function () {
        frappe.model.open_mapped_doc({
          method:
            "l10n_ve.l10n_ve.doctype.ve_sales_credit_note" +
            ".ve_sales_credit_note.make_replacement_invoice",
          frm: frm,
        });
      });
    }

    // Button: void NC in HKA + Frappe (only when submitted and has HKA document number)
    if (frm.doc.docstatus === 1 && frm.doc.bill_no) {
      frm.add_custom_button(
        __("Anular"),
        function () {
          const today = frappe.datetime.get_today();
          const now = frappe.datetime.now_time();

          const dialog = new frappe.ui.Dialog({
            title: __("Anular Nota de Crédito en HKA"),
            fields: [
              {
                label: __("Motivo de Anulación"),
                fieldname: "reason",
                fieldtype: "Small Text",
                reqd: 1,
                description: __(
                  "Indique el motivo de la anulación. Será enviado a la imprenta digital.",
                ),
              },
              {
                label: __("Fecha de Anulación"),
                fieldname: "void_date",
                fieldtype: "Date",
                default: today,
                reqd: 1,
              },
              {
                label: __("Hora de Anulación"),
                fieldname: "void_time",
                fieldtype: "Time",
                default: now,
                reqd: 1,
              },
            ],
            primary_action_label: __("Confirmar Anulación"),
            primary_action(values) {
              dialog.hide();

              // Convert YYYY-MM-DD → DD/MM/YYYY (format required by TFHKA)
              const date_parts = values.void_date.split("-");
              const formatted_date = `${date_parts[2]}/${date_parts[1]}/${date_parts[0]}`;

              frappe.call({
                method:
                  "l10n_ve.l10n_ve.doctype.ve_sales_credit_note" +
                  ".ve_sales_credit_note.void_credit_note",
                args: {
                  docname: frm.doc.name,
                  reason: values.reason,
                  void_date: formatted_date,
                  void_time: values.void_time,
                },
                freeze: true,
                freeze_message: __("Anulando en HKA y sistema..."),
                callback(r) {
                  if (!r.exc) {
                    frappe.show_alert({
                      message: __("Nota de Crédito anulada correctamente."),
                      indicator: "green",
                    });
                    frm.reload_doc();
                  }
                },
              });
            },
          });

          dialog.show();
        },
        __("Acciones"),
      );
    }

    // Botones: consultar NC en portal HKA
    _add_hka_consulta_button(frm, 1, __("Ver Factura Fiscal"));
    _add_hka_consulta_button(frm, 2, __("Ver Documento Anulado en HKA"));

    // Botón: emitir a HKA (solo submit, sin número HKA aún)
    if (frm.doc.docstatus === 1 && !frm.doc.bill_no) {
      frm.add_custom_button(
        __("Emitir a HKA"),
        function () {
          frappe.call({
            method: "l10n_ve.digital_invoice.tfhka_integration.process_invoice",
            args: {
              doc_name: frm.doc.name,
              doctype: "VE Sales Credit Note",
            },
            freeze: true,
            freeze_message: __("Enviando Nota de Crédito a HKA..."),
            callback: function (r) {
              if (!r.exc && r.message) {
                frm.reload_doc();
                frappe.show_alert({
                  message: __("Nota de Crédito emitida exitosamente ante HKA"),
                  indicator: "green",
                });
              } else if (!r.exc && r.message === false) {
                frm.reload_doc();
                frappe.msgprint({
                  title: __("Error al emitir a HKA"),
                  message: __(
                    "La Nota de Crédito no pudo ser emitida. Revise el log de facturación digital para más detalles.",
                  ),
                  indicator: "red",
                });
              }
            },
          });
        },
        __("Facturación Digital"),
      );
      frm.page.set_inner_btn_group_as_primary(__("Facturación Digital"));
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

  // Al seleccionar la factura original:
  //   1. Auto-carga cliente, branch, tasa e ítems en positivo
  return_against: function (frm) {
    if (!frm.doc.return_against) return;

    frappe.call({
      method: "frappe.client.get",
      args: { doctype: "Sales Invoice", name: frm.doc.return_against },
      callback: function (r) {
        if (!r.message) return;
        const si = r.message;

        // ── Cliente: heredar de la SI ─────────────────────────────────
        if (si.customer && !frm.doc.customer) {
          frm.set_value("customer", si.customer);
        }

        // ── Fechas: heredar de la SI ──────────────────────────────────
        if (si.posting_date) {
          frm.set_value("posting_date", si.posting_date);
        }
        if (si.due_date) {
          frm.set_value("due_date", si.due_date);
        }

        // ── Branch: heredar de la SI y bloquear si la tiene ─────────
        if (si.branch) {
          frm.set_value("branch", si.branch);
          frm.set_df_property("branch", "read_only", 1);
        } else {
          frm.set_df_property("branch", "read_only", 0);
        }

        // ── Tasa de cambio: heredar de la SI ─────────────────────────
        // La NC debe usar la MISMA tasa que la factura original para que
        // los asientos contables en VEF sean un espejo exacto.
        if (si.conversion_rate) {
          frm.set_value("conversion_rate", si.conversion_rate);
        }
        if (si.plc_conversion_rate) {
          frm.set_value("plc_conversion_rate", si.plc_conversion_rate);
        }

        // ── Ítems: copiar desde la SI en positivo ────────────────────
        frm.clear_table("items");
        si.items.forEach(function (item) {
          let row = frm.add_child("items");
          // Campos descriptivos
          row.item_code = item.item_code;
          row.item_name = item.item_name;
          row.description = item.description;
          row.uom = item.uom;
          row.stock_uom = item.stock_uom;
          row.income_account = item.income_account;
          row.cost_center = item.cost_center;
          row.warehouse = item.warehouse;

          // Cantidades y precios — siempre positivos
          row.qty = Math.abs(item.qty);
          row.stock_qty = Math.abs(item.stock_qty || item.qty);
          row.rate = Math.abs(item.rate);

          // Campos calculados obligatorios
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

          // Impuestos del ítem
          row.item_tax_template = item.item_tax_template;
          row.tax_rate = item.tax_rate;
        });

        frm.refresh_field("items");

        // Totales del encabezado — el servidor los recalcula en validate(),
        // pero el cliente los requiere para pasar la validación de campos obligatorios
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

        frappe.show_alert({
          message: __("Ítems cargados desde {0}", [frm.doc.return_against]),
          indicator: "blue",
        });
      },
    });
  },

  // Al cambiar la fecha de la NC, actualiza la tasa de cambio según
  // la misma regla fiscal que la SI: Jurídico → fecha exacta, Natural → 1ro del mes.
  posting_date: function (frm) {
    apply_ve_exchange_rate_nc(frm);
  },
});

/**
 * Obtiene y aplica la tasa de cambio venezolana correcta para la NC.
 *
 * Regla fiscal (igual que en VE Sales Invoice):
 *   Jurídico → fecha exacta del posting_date.
 *   Natural  → primer día del mes del posting_date.
 *
 * Solo actúa si tfhka_enabled está activo, el doc está en borrador
 * y tiene cliente + fecha + moneda extranjera.
 *
 * @param {object} frm - Instancia del formulario Frappe.
 */
function apply_ve_exchange_rate_nc(frm) {
  if (!frappe.boot.tfhka_enabled) return;
  if (frm.doc.docstatus !== 0) return;
  if (!frm.doc.customer || !frm.doc.posting_date) return;

  const company_currency = erpnext.get_currency(frm.doc.company);
  if (!frm.doc.currency || frm.doc.currency === company_currency) return;

  frappe.call({
    method: "l10n_ve.utils.utils.get_ve_exchange_rate_for_customer",
    args: {
      customer: frm.doc.customer,
      date: frm.doc.posting_date,
      from_currency: frm.doc.currency,
    },
    callback: function (r) {
      if (!r.message) return;
      const rate = flt(r.message);
      if (rate <= 0) return;

      frm.set_value("conversion_rate", rate);
      frm.set_value("plc_conversion_rate", rate);
    },
  });
}

/**
 * Agrega un botón para consultar el documento en el portal de HKA.
 * Solo se muestra si el docstatus coincide, tiene bill_no y remarks
 * contiene una urlConsulta válida.
 * @param {object} frm
 * @param {number} docstatus - 1 para emitidas, 2 para anuladas
 * @param {string} label - Texto del botón
 */
function _add_hka_consulta_button(frm, docstatus, label) {
  if (frm.doc.docstatus !== docstatus || !frm.doc.bill_no || !frm.doc.remarks) {
    return;
  }
  try {
    const hka_data = JSON.parse(frm.doc.remarks);
    const url = hka_data.resultado && hka_data.resultado.urlConsulta;
    if (url) {
      frm.add_custom_button(
        label,
        function () {
          window.open(url, "_blank");
        },
        __("Ver"),
      );
    }
  } catch (_) {}
}
