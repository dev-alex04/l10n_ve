// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

// ── Constantes ──────────────────────────────────────────────────────── //

const VAT_CHILD_TABLE = "vat_withholding_voucher_item";

const VAT_ROW_FIELDS = [
  "purchase_invoice_type", "purchase_invoice", "bill_no", "bill_control",
  "posting_date", "rate", "withholding_rate", "grand_total", "total_exempt",
  "total", "taxes_and_charges_added", "tax_amount_vat", "credit_note_no",
  "debit_note_no", "affected_invoice_number", "tax_amount",
];

const VAT_TOTAL_FIELDS = [
  "totals_grand_total", "totals_total_exempt", "totals_total",
  "totals_taxes_and_charges_added", "totals_tax_amount_vat",
];

const VAT_ITEM_TOTAL_MAP = {
  totals_grand_total: "grand_total",
  totals_total_exempt: "total_exempt",
  totals_total: "total",
  totals_taxes_and_charges_added: "taxes_and_charges_added",
  totals_tax_amount_vat: "tax_amount_vat",
};

// ── Form Events ─────────────────────────────────────────────────────── //

frappe.ui.form.on("VAT Withholding Voucher", {
  refresh: function (frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__("Imprimir"), function () {
        const print_window = window.open("", "_blank");
        if (!print_window) {
          frappe.msgprint(__("Por favor, deshabilite el bloqueador de ventanas emergentes para este sitio."));
          return;
        }

        frappe.call({
          method:
            "l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase.generate_vat_report",
          args: { voucher_name: frm.doc.name },
          callback: function (r) {
            if (r.message) {
              print_window.document.write(r.message);
              print_window.document.close();
              print_window.onload = function () {
                print_window.print();
              };
            } else {
              print_window.close();
            }
          },
        });
      });

      if (frm.doc.docstatus === 0 && !frm.is_new()) {
        frm.add_custom_button(__("Obtener Facturas"), function () {
          load_invoices(frm);
        });
      }

      const fields = [
        "start_date", "end_date", "empresa", "supplier",
        "fiscal_period", "issue_date", VAT_CHILD_TABLE,
      ];
      fields_read_only(frm, fields);
      if (frm.doc.branch) {
        frm.set_df_property("branch", "read_only", true);
      } else {
        frm.set_df_property("branch", "read_only", false);
      }
    }

    if (frm.doc.docstatus === 1 && !frm.doc.is_declared) {
      frm
        .add_custom_button(__("Marcar como Declarado"), function () {
          frappe.confirm(
            __("¿Estás seguro de marcar este comprobante como declarado? Esta acción no se puede deshacer."),
            () => {
              frm.call("mark_as_declared").then(() => {
                frm.reload_doc();
                frappe.msgprint({
                  title: __("Éxito"),
                  indicator: "green",
                  message: __("Comprobante actualizado correctamente"),
                });
              });
            },
          );
        })
        .addClass("btn-primary");
    }

    // Indicador de estado de emisión digital (HKA)
    setup_hka_indicator(frm);

    // Mensaje informativo sobre emisión digital
    setup_hka_intro(frm);

    // Botón de envío/reenvío manual a HKA
    if (
      frm.doc.docstatus === 1 &&
      (!frm.doc.digital_invoice_status || frm.doc.digital_invoice_status === "Error")
    ) {
      frm.add_custom_button(__("Emitir"), function () {
        frappe.confirm(
          __("¿Desea reenviar este comprobante de retención a la imprenta fiscal digital?"),
          () => {
            frappe.call({
              method: "l10n_ve.digital_invoice.retention_integration.send_retention_voucher_manually",
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
      setup_void_button(frm, {
        title: __("Anular Comprobante en HKA"),
        method: "l10n_ve.digital_invoice.retention_integration.void_retention_voucher",
        group: __("Factura Digital"),
      });
    }

    // Ocultar opción "Eliminar" si el comprobante está cancelado
    if (frm.doc.docstatus === 2) {
      frm.page.remove_menu_item(__("Delete"));
      frm.page.menu_btn_group
        .find("a.grey-link")
        .filter(function () {
          return $(this).text().trim() === __("Delete");
        })
        .closest("li")
        .hide();
    }

    // Vista previa del documento fiscal HKA
    frappe.l10n_ve.render_fiscal_preview(frm, {
      doctype: "VAT Withholding Voucher",
      title: "Comprobante Fiscal Digital",
    });
  },

  onload: function (frm) {
    if (frm.doc.__islocal && !frm.doc.amended_from) {
      const company_name = frm.doc.empresa;
      const today = frappe.datetime.get_today();

      if (company_name) {
        frm
          .call("get_withholding_correlative", {
            company_name: company_name,
            voucher_type: "vat",
          })
          .then((r) => {
            if (r.message) {
              const { voucher_number, year, month } = r.message;
              frm.set_value("voucher_number", voucher_number);
              frm.set_value("fiscal_period", `${month}/${year}`);
              frm.set_value("issue_date", today);
              frm.set_value("delivery_date", today);
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
    maybe_load_invoices(frm);
  },

  end_date: function (frm) {
    if (frm.doc.start_date && frm.doc.end_date) {
      validar_fechas(frm, "end_date");
    }
    maybe_load_invoices(frm);
  },

  supplier: function (frm) {
    frm.clear_table(VAT_CHILD_TABLE);
    frm.refresh_field(VAT_CHILD_TABLE);
    frm.set_value("supplier_address", "");
    frm.refresh_field("supplier_address");
    maybe_load_invoices(frm);
  },

  empresa: function (frm) {
    frm.clear_table(VAT_CHILD_TABLE);
    frm.refresh_field(VAT_CHILD_TABLE);
    frm.set_value("company_address", "");
    frm.refresh_field("company_address");
    maybe_load_invoices(frm);
  },
  
  branch: function (frm) {
    frm.clear_table(VAT_CHILD_TABLE);
    frm.refresh_field(VAT_CHILD_TABLE);
    maybe_load_invoices(frm);
  },
});

frappe.ui.form.on("VAT Withholding Voucher Item", {
  vat_withholding_voucher_item_remove(frm) {
    calculate_totals(frm);
  },
});

// ── Funciones auxiliares ─────────────────────────────────────────────── //

function maybe_load_invoices(frm) {
  if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
    load_invoices(frm);
  }
}

let _load_timeout;
function load_invoices(frm) {
  clearTimeout(_load_timeout);
  _load_timeout = setTimeout(() => _do_load_invoices(frm), 300);
}

function _do_load_invoices(frm) {
  if (!frm.doc.supplier || !frm.doc.start_date || !frm.doc.end_date || !frm.doc.empresa) {
    return;
  }

  frm.clear_table(VAT_CHILD_TABLE);

  frappe.call({
    method:
      "l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher.get_valid_invoices",
    args: {
      supplier: frm.doc.supplier,
      start_date: frm.doc.start_date,
      end_date: frm.doc.end_date,
      company: frm.doc.empresa,
      exclude_voucher: frm.doc.name || "",
      branch: frm.doc.branch || "",
    },
    callback: function (r) {
      // Reset totales
      VAT_TOTAL_FIELDS.forEach((f) => { frm.doc[f] = 0; });

      if (r.message && r.message.length > 0) {
        // Auto-set branch if empty and all loaded invoices share the same branch
        const unique_branches = [...new Set(r.message.map((inv) => inv.branch).filter(Boolean))];
        if (unique_branches.length === 1 && !frm.doc.branch) {
          frm.set_value("branch", unique_branches[0]);
          if (!frm.is_new()) {
            frm.set_df_property("branch", "read_only", true);
          }
        }

        r.message.forEach((invoice) => {
          const new_row = frm.add_child(VAT_CHILD_TABLE);
          VAT_ROW_FIELDS.forEach((f) => { new_row[f] = invoice[f]; });

          // Solo NC resta en los totales del comprobante
          const sign = invoice.is_return ? -1 : 1;

          Object.entries(VAT_ITEM_TOTAL_MAP).forEach(([total_field, item_field]) => {
            frm.doc[total_field] += (invoice[item_field] || 0) * sign;
          });
        });

        frm.refresh_fields();
      } else {
        frm.clear_table(VAT_CHILD_TABLE);
        frm.refresh_fields();

        frappe.show_alert({
          message: __("No se encontraron facturas de compra que cumplan con los criterios."),
          indicator: "orange",
        });
      }
    },
  });
}

function calculate_totals(frm) {
  VAT_TOTAL_FIELDS.forEach((f) => { frm.doc[f] = 0; });

  (frm.doc[VAT_CHILD_TABLE] || []).forEach((item) => {
    // Solo NC resta en los totales del comprobante
    const sign = item.credit_note_no ? -1 : 1;

    Object.entries(VAT_ITEM_TOTAL_MAP).forEach(([total_field, item_field]) => {
      frm.doc[total_field] += (item[item_field] || 0) * sign;
    });
  });

  frm.refresh_fields(VAT_TOTAL_FIELDS);
}

// ── Funciones compartidas ────────────────────────────────────────────── //

function validar_fechas(frm, campo) {
  if (!frm.doc.start_date || !frm.doc.end_date) return;

  if (frm.doc.end_date < frm.doc.start_date) {
    frm.set_value(campo, null);
    frm.clear_table(VAT_CHILD_TABLE);
    frm.refresh_field(VAT_CHILD_TABLE);
    frappe.throw(__("La fecha de fin no puede ser menor que la fecha de inicio."));
  }
}

function fields_read_only(frm, fields) {
  fields.forEach((field) => {
    frm.set_df_property(field, "read_only", true);
  });
}

function setup_hka_indicator(frm) {
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
}

function setup_hka_intro(frm) {
  if (frm.doc.docstatus !== 1) return;

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

function setup_void_button(frm, config) {
  frm.add_custom_button(
    __("Anular Comprobante"),
    function () {
      const today = frappe.datetime.get_today();
      const now = frappe.datetime.now_time();

      const dialog = new frappe.ui.Dialog({
        title: config.title,
        fields: [
          {
            label: __("Motivo de Anulación"),
            fieldname: "reason",
            fieldtype: "Small Text",
            reqd: 1,
            description: __("Indique el motivo de la anulación. Será enviado a la imprenta digital."),
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
            method: config.method,
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
                  message: __("Comprobante anulado correctamente en HKA y en el sistema."),
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
    config.group,
  );
}
