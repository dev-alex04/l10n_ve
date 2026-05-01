// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("ISLR Withholding Voucher", {
  refresh: function (frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__("Imprimir"), function () {
        const printWindow = window.open("", "_blank");
        if (!printWindow) {
          frappe.msgprint(__("Por favor, deshabilite el bloqueador de ventanas emergentes para este sitio."));
          return;
        }

        frappe.call({
          method:
            "l10n_ve.l10n_ve.report.islr_withholding_voucher_purchase.islr_withholding_voucher_purchase.generate_islr_report",
          args: {
            voucher_name: frm.doc.name,
          },
          callback: function (r) {
            if (r.message) {
              printWindow.document.write(r.message);
              printWindow.document.close();
              printWindow.onload = function () {
                printWindow.print();
              };

            } else {
              printWindow.close();
              if (r.exc) {
                frappe.throw(__("Error al generar el comprobante."));
              }
            }
          },
        });
      });

      if (frm.doc.docstatus === 0 && !frm.is_new()) {
        frm.add_custom_button(__("Obtener Facturas"), function () {
          load_invoices(frm);
        });
      }

      const fields = ["start_date", "end_date", "empresa", "supplier", "islr_withholding_voucher_item"];
      fields_read_only(frm, fields);
    }

    if (frm.doc.docstatus === 1 && !frm.doc.is_declared) {
      frm.add_custom_button(__('Marcar como Declarado'), function () {
        frappe.confirm(__('¿Estás seguro de marcar este comprobante como declarado? Esta acción no se puede deshacer.'), () => {
          frm.call("mark_as_declared").then(() => {
            frm.reload_doc();
            frappe.msgprint({
              title: __('Éxito'),
              indicator: 'green',
              message: __('Comprobante actualizado correctamente')
            });
          });
        });
      }).addClass('btn-primary');
    }

    // Indicador de estado de emisión digital (HKA)
    if (frm.doc.docstatus !== 2 || frm.doc.digital_invoice_status === "Voided") {
      const hka_status_map = {
        Sent: ["Emitido", "green"],
        Error: ["Error en emisión", "red"],
        Pending: ["Pendiente de emisión", "orange"],
        Voided: ["Anulado", "red"],
      };
      const hka_info = hka_status_map[frm.doc.digital_invoice_status];
      if (hka_info) {
        frm.page.set_indicator(hka_info[0], hka_info[1]);
      }
    }

    // Mensaje informativo sobre emisión digital
    if (frm.doc.docstatus === 1) {
      if (!frm.doc.digital_invoice_status || frm.doc.digital_invoice_status === "Error") {
        frm.set_intro(
          __("Este comprobante será emitido automáticamente por el sistema en los próximos minutos. "
            + "Si desea emitirlo de inmediato, use el botón <b>\"Emitir\"</b> en el menú Factura Digital."),
          "blue"
        );
      } else if (frm.doc.digital_invoice_status === "Sent") {
        frm.set_intro(
          __("Comprobante emitido exitosamente ante la imprenta fiscal digital."),
          "green"
        );
      }
    }

    // Botón de envío/reenvío manual a HKA
    if (
      frm.doc.docstatus === 1 &&
      (!frm.doc.digital_invoice_status ||
        frm.doc.digital_invoice_status === "Error")
    ) {
      frm.add_custom_button(__("Emitir"), function () {
        frappe.confirm(
          __("¿Desea enviar este comprobante de retención ISLR a la imprenta fiscal digital?"),
          () => {
            frappe.call({
              method:
                "l10n_ve.digital_invoice.islr_withholding_integration.send_islr_voucher_manually",
              args: { voucher_name: frm.doc.name },
              freeze: true,
              freeze_message: __("Enviando a HKA..."),
              callback: function () {
                frm.reload_doc();
              },
            });
          },
        );
      });
    }

    // Botón "Anular Comprobante" (solo cuando está emitido a HKA)
    if (frm.doc.docstatus === 1 && frm.doc.digital_invoice_status === "Sent") {
      frm.add_custom_button(
        __("Anular Comprobante"),
        function () {
          const today = frappe.datetime.get_today();
          const now = frappe.datetime.now_time();

          const dialog = new frappe.ui.Dialog({
            title: __("Anular Comprobante ISLR en HKA"),
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

              // Convertir YYYY-MM-DD → DD/MM/YYYY (formato TFHKA)
              const date_parts = values.void_date.split("-");
              const formatted_date = `${date_parts[2]}/${date_parts[1]}/${date_parts[0]}`;

              frappe.call({
                method:
                  "l10n_ve.digital_invoice.islr_withholding_integration.void_islr_voucher",
                args: {
                  voucher_name: frm.doc.name,
                  reason: values.reason,
                  void_date: formatted_date,
                  void_time: values.void_time,
                },
                freeze: true,
                freeze_message: __("Anulando en HKA y sistema..."),
                callback(r) {
                  if (!r.exc) {
                    frappe.show_alert({
                      message: __(
                        "Comprobante anulado correctamente en HKA y en el sistema.",
                      ),
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

    // Vista previa del documento fiscal HKA
    render_islr_fiscal_preview(frm);
  },

  onload: function (frm) {
    if (frm.doc.__islocal && !frm.doc.amended_from) {
      const company_name = frm.doc.empresa;
      const today = frappe.datetime.get_today();

      if (company_name) {
        frm
          .call("get_withholding_correlative", {
            company_name: company_name,
            voucher_type: "islr",
          })
          .then((r) => {
            if (r.message) {
              frm.set_value("voucher_number", r.message.voucher_number);
              frm.set_value("start_date", today);
              frm.set_value("end_date", today);
            }
          });
      }
    }

    // Limpiar campos HKA al enmendar para garantizar un documento limpio
    if (frm.doc.__islocal && frm.doc.amended_from) {
      frm.set_value("digital_invoice_status", "");
      frm.set_value("hka_response", "");
      frm.set_value("bill_control", "");
      frm.set_value("voucher_number", "");
    }
  },

  start_date: function (frm) {
    if (frm.doc.start_date && frm.doc.end_date) {
      validar_fechas(frm, "start_date");
    }

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  end_date: function (frm) {
    if (frm.doc.start_date && frm.doc.end_date) {
      validar_fechas(frm, "end_date");
    }

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  supplier: function (frm) {
    frm.clear_table("islr_withholding_voucher_item");
    frm.refresh_field("islr_withholding_voucher_item");

    frm.set_value("supplier_address", "");
    frm.refresh_field("supplier_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  empresa: function (frm) {
    frm.clear_table("islr_withholding_voucher_item");
    frm.refresh_field("islr_withholding_voucher_item");

    frm.set_value("company_address", "");
    frm.refresh_field("company_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },
});

function validar_fechas(frm, campo) {
  try {
    const startDate = new Date(frm.doc.start_date);
    const endDate = new Date(frm.doc.end_date);

    if (endDate < startDate) {
      frm.set_value(campo, null);
      frm.clear_table("islr_withholding_voucher_item");
      frm.refresh_field("islr_withholding_voucher_item");

      throw new Error(
        "La fecha de fin no puede ser menor que la fecha de inicio."
      );
    }
  } catch (e) {
    frappe.throw(e.message);
  }
}

frappe.ui.form.on('ISLR Withholding Voucher Item', {
  islr_withholding_voucher_item_remove(frm, cdt, cdn) {
    calculate_totals(frm);
  }
});

function load_invoices(frm) {
  if (
    !frm.doc.supplier ||
    !frm.doc.start_date ||
    !frm.doc.end_date ||
    !frm.doc.empresa
  ) {
    return;
  }

  frm.clear_table("islr_withholding_voucher_item");

  frappe.call({
    method:
      "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher.get_valid_invoices",
    args: {
      supplier: frm.doc.supplier,
      start_date: frm.doc.start_date,
      end_date: frm.doc.end_date,
      company: frm.doc.empresa,
    },
    callback: function (r) {
      frm.doc.totals_islr_base_amount = 0;
      frm.doc.totals_islr_amount = 0;
      frm.doc.totals_grand_total = 0;
      frm.doc.totals_paid_amount = 0;

      if (r.message && r.message.length > 0) {
        r.message.forEach((invoice) => {
          let new_row = frm.add_child("islr_withholding_voucher_item");
          new_row.purchase_invoice = invoice.purchase_invoice;
          new_row.doc_no = invoice.doc_no;
          new_row.doc_type = invoice.doc_type;
          new_row.bill_control = invoice.bill_control;
          new_row.posting_date = invoice.posting_date;
          new_row.grand_total = invoice.grand_total;
          new_row.islr_base_amount = invoice.islr_base_amount;
          new_row.paid_amount = invoice.paid_amount;
          new_row.rate = invoice.rate;
          new_row.subtracting = invoice.subtracting;
          new_row.code = invoice.code;
          new_row.islr_amount = invoice.islr_amount;

          frm.doc.totals_islr_base_amount += invoice.islr_base_amount || 0;
          frm.doc.totals_islr_amount += invoice.islr_amount || 0;
          frm.doc.totals_grand_total += invoice.grand_total || 0;
          frm.doc.totals_paid_amount += invoice.paid_amount || 0;
        });

        frm.refresh_fields();
      } else {
        frm.clear_table("islr_withholding_voucher_item");
        frm.refresh_field("islr_withholding_voucher_item");

        frm.doc.totals_islr_base_amount = 0;
        frm.doc.totals_islr_amount = 0;
        frm.refresh_fields();

        frappe.show_alert({
          message: __(
            "No se encontraron facturas de compra que cumplan con los criterios."
          ),
          indicator: "orange",
        });
      }
    },
  });
}

function calculate_totals(frm) {
  let total_islr_base = 0;
  let total_islr_amount = 0;
  let total_grand_total = 0;
  let total_paid_amount = 0;

  frm.doc.islr_withholding_voucher_item.forEach(item => {
    total_islr_base += item.islr_base_amount || 0;
    total_islr_amount += item.islr_amount || 0;
    total_grand_total += item.grand_total || 0;
    total_paid_amount += item.paid_amount || 0;
  });

  frm.doc.totals_islr_base_amount = total_islr_base;
  frm.doc.totals_islr_amount = total_islr_amount;
  frm.doc.totals_grand_total = total_grand_total;
  frm.doc.totals_paid_amount = total_paid_amount;

  frm.refresh_fields([
    "totals_islr_base_amount",
    "totals_islr_amount",
    "totals_grand_total",
    "totals_paid_amount"
  ]);
};

function fields_read_only(frm, fields) {
  fields.forEach(field => {
    frm.set_df_property(field, 'read_only', true);
  });
}

/**
 * Renderiza la vista previa del documento fiscal HKA en el comprobante ISLR.
 * Utiliza el helper compartido frappe.l10n_ve.render_fiscal_preview.
 */
function render_islr_fiscal_preview(frm) {
  frappe.l10n_ve.render_fiscal_preview(frm, {
    doctype: "ISLR Withholding Voucher",
    title: "Comprobante Fiscal Digital (ISLR)",
  });
}