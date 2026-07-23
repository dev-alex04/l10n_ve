// Copyright (c) 2026, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Sales Credit Note", {
  onload: function (frm) {
    // NC nunca requiere fecha de vencimiento
    frm.toggle_reqd("due_date", false);

    // La tasa de la NC es SIEMPRE la de la factura original: bloqueamos el
    // campo para que el usuario no lo edite manualmente. La herencia se
    // garantiza en _inherit_branch_from_si (Python) y en
    // populate_from_sales_invoice (JS).
    _lock_exchange_rate_fields(frm);

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
    _lock_exchange_rate_fields(frm);
    calculate_base_total_with_vat(frm);

    // Indicador fiscal VE (centralizado en sales_billing_indicators.js)
    set_ve_form_indicator(frm, { doc_type: "credit_note" });

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
        __("Factura Digital"),
      );
    }

    // Vista previa del PDF fiscal
    render_fiscal_invoice_preview(frm, {
      field_name: "credit_note_preview",
      doctype: "VE Sales Credit Note",
    });

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
              raise_on_error: true,
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
        __("Factura Digital"),
      );
      frm.page.set_inner_btn_group_as_primary(__("Factura Digital"));
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
  //   1. Auto-carga cliente, branch e ítems en positivo. La tasa se
  //      hereda de la SI (misma tasa de la factura afectada).
  return_against: function (frm) {
    populate_from_sales_invoice(frm);
  },
});

// ------------------------------------------------------------------ //
// Child table: recálculo al cambiar qty, rate o descuento
// ------------------------------------------------------------------ //

frappe.ui.form.on("VE Sales Credit Note Item", {
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
        __("Factura Digital"),
      );
    }
  } catch (_) {}
}

/**
 * Marca los campos de tasa de cambio de la NC (conversion_rate y
 * plc_conversion_rate) como solo lectura: la tasa es SIEMPRE la de la
 * factura original, heredada vía _inherit_branch_from_si (Python) y
 * populate_from_sales_invoice (JS); el usuario la ve pero no la edita.
 * Solo aplica en borradores con factura afectada vinculada; en docs
 * submitted el control nativo de Frappe ya los bloquea.
 * @param {object} frm
 */
function _lock_exchange_rate_fields(frm) {
  const lock = frm.doc.docstatus === 0 && frm.doc.return_against;
  ["conversion_rate", "plc_conversion_rate"].forEach(function (fieldname) {
    const df = frm.get_field(fieldname);
    if (df) {
      df.read_only = lock ? 1 : 0;
    }
  });
  frm.refresh_field("conversion_rate");
  frm.refresh_field("plc_conversion_rate");
}
