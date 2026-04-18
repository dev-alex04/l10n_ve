// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Sales Debit Note", {
  onload: function (frm) {
    // ND nunca requiere fecha de vencimiento
    frm.toggle_reqd("due_date", false);

    // Solo SI aprobadas, sin NC/ND previa, de la misma empresa y cliente
    frm.set_query("return_against", function () {
      return {
        query:
          "l10n_ve.l10n_ve.doctype.ve_sales_debit_note.ve_sales_debit_note.query_available_sales_invoices",
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

    // Vista previa del asiento contable
    erpnext.accounts.ledger_preview.show_accounting_ledger_preview(frm);

    // Banner azul: enlace a la SI original (pendiente de emisión HKA)
    if (frm.doc.return_against && !frm.doc.bill_no) {
      frm.set_intro(
        __("Nota de Débito aplicada a la factura: {0}", [
          `<a href="/app/sales-invoice/${frm.doc.return_against}">${frm.doc.return_against}</a>`,
        ]),
        "blue",
      );
    }

    // Banner verde: ND emitida en HKA (solo documentos activos/submit)
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

    // Banner rojo: ND anulada en HKA — bloquear Amend
    if (frm.doc.bill_no && frm.doc.docstatus === 2) {
      frm.set_intro(
        __(
          "🚫 Esta Nota de Débito fue <b>anulada ante HKA</b> (N° {0}). " +
            "No puede ser corregida ni enmendada. " +
            "Cree una nueva Nota de Débito si es necesario.",
          [frm.doc.bill_no],
        ),
        "red",
      );
      frm.page.btn_primary.hide();
    }

    // Botón rápido: ir a la factura original
    if (
      frm.doc.docstatus >= 0 &&
      frm.doc.return_against &&
      !frm.doc.__islocal
    ) {
      frm.add_custom_button(__("Ver Factura Original"), function () {
        frappe.set_route("Form", "Sales Invoice", frm.doc.return_against);
      });
    }

    // Botón: anular ND en HKA + Frappe (solo cuando submitted y tiene doc HKA)
    if (frm.doc.docstatus === 1 && frm.doc.bill_no) {
      frm.add_custom_button(
        __("Anular"),
        function () {
          const today = frappe.datetime.get_today();
          const now = frappe.datetime.now_time();

          const dialog = new frappe.ui.Dialog({
            title: __("Anular Nota de Débito en HKA"),
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
                read_only: 1,
              },
              {
                label: __("Hora de Anulación"),
                fieldname: "void_time",
                fieldtype: "Time",
                default: now,
                reqd: 1,
                read_only: 1,
              },
            ],
            primary_action_label: __("Confirmar Anulación"),
            primary_action(values) {
              dialog.hide();

              const date_parts = values.void_date.split("-");
              const formatted_date = `${date_parts[2]}/${date_parts[1]}/${date_parts[0]}`;

              frappe.call({
                method:
                  "l10n_ve.l10n_ve.doctype.ve_sales_debit_note" +
                  ".ve_sales_debit_note.void_debit_note",
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
                      message: __("Nota de Débito anulada correctamente."),
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

    // Vista previa del PDF fiscal
    render_fiscal_invoice_preview(frm, {
      field_name: "debit_note_preview",
      doctype: "VE Sales Debit Note",
    });

    // Botones: consultar ND en portal HKA
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
              doctype: "VE Sales Debit Note",
            },
            freeze: true,
            freeze_message: __("Enviando Nota de Débito a HKA..."),
            callback: function (r) {
              if (!r.exc && r.message) {
                frm.reload_doc();
                frappe.show_alert({
                  message: __("Nota de Débito emitida exitosamente ante HKA"),
                  indicator: "green",
                });
              } else if (!r.exc && r.message === false) {
                frm.reload_doc();
                frappe.msgprint({
                  title: __("Error al emitir a HKA"),
                  message: __(
                    "La Nota de Débito no pudo ser emitida. Revise el log de facturación digital para más detalles.",
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

  // Al seleccionar la factura original: auto-carga cliente, branch, tasa e ítems
  return_against: function (frm) {
    populate_from_sales_invoice(frm);
  },

  // Al cambiar la fecha, actualiza la tasa de cambio según regla fiscal VE
  posting_date: function (frm) {
    apply_ve_exchange_rate_nd(frm);
  },
});

// ------------------------------------------------------------------ //
// Child table: recálculo al cambiar qty, rate o descuento
// ------------------------------------------------------------------ //

frappe.ui.form.on("VE Sales Debit Note Item", {
  qty(frm) {
    recalculate_ve_document(frm);
  },
  rate(frm) {
    recalculate_ve_document(frm);
  },
  price_list_rate(frm) {
    recalculate_ve_document(frm);
  },
  discount_percentage(frm) {
    recalculate_ve_document(frm);
  },
  discount_amount(frm) {
    recalculate_ve_document(frm);
  },
  items_remove(frm) {
    recalculate_ve_document(frm);
  },
});

/**
 * Obtiene y aplica la tasa de cambio venezolana correcta para la ND.
 * Regla fiscal:
 *   Jurídico → fecha exacta del posting_date.
 *   Natural  → primer día del mes del posting_date.
 */
function apply_ve_exchange_rate_nd(frm) {
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
 * Botón para consultar el documento en el portal de HKA.
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
