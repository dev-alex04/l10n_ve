// // Copyright (c) 2025, DominaERP and contributors
// // For license information, please see license.txt

frappe.ui.form.on("VAT Withholding Voucher", {
  refresh: function (frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__("Imprimir"), function () {
        frappe.call({
          method:
            "l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase.generate_vat_report",
          args: {
            voucher_name: frm.doc.name,
          },
          callback: function (r) {
            if (r.message) {
              var w = window.open("about:blank");
              w.document.write(r.message);
              w.document.close();
              w.print();
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
        "start_date",
        "end_date",
        "empresa",
        "supplier",
        "fiscal_period",
        "issue_date",
        "vat_withholding_voucher_item",
      ];
      fields_read_only(frm, fields);
    }

    if (frm.doc.docstatus === 1 && !frm.doc.is_declared) {
      frm
        .add_custom_button(__("Marcar como Declarado"), function () {
          frappe.confirm(
            __(
              "¿Estás seguro de marcar este comprobante como declarado? Esta acción no se puede deshacer.",
            ),
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
    // Solo mostrar en documentos activos; si está cancelado, dejar el indicador estándar de Frappe
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

    // Botón de envío/reenvío manual a HKA (cuando no se ha enviado o hay error)
    if (
      frm.doc.docstatus === 1 &&
      (!frm.doc.digital_invoice_status ||
        frm.doc.digital_invoice_status === "Error")
    ) {
      frm.add_custom_button(__("Emitir"), function () {
        frappe.confirm(
          __(
            "¿Desea reenviar este comprobante de retención a la imprenta fiscal digital?",
          ),
          () => {
            frappe.call({
              method:
                "l10n_ve.digital_invoice.retention_integration.send_retention_voucher_manually",
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
            title: __("Anular Comprobante en HKA"),
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
                  "l10n_ve.digital_invoice.retention_integration.void_retention_voucher",
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
    render_retention_fiscal_preview(frm);
  },

  onload: function (frm) {
    if (frm.doc.__islocal && !frm.doc.amended_from) {
      const company_name = frm.doc.empresa;
      const today = new Date();

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
    frm.clear_table("vat_withholding_voucher_item");
    frm.refresh_field("vat_withholding_voucher_item");

    frm.set_value("supplier_address", "");
    frm.refresh_field("supplier_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  empresa: function (frm) {
    frm.clear_table("vat_withholding_voucher_item");
    frm.refresh_field("vat_withholding_voucher_item");

    frm.set_value("company_address", "");
    frm.refresh_field("company_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },
});

frappe.ui.form.on("VAT Withholding Voucher Item", {
  vat_withholding_voucher_item_remove(frm, cdt, cdn) {
    calculate_totals(frm);
  },
});

function validar_fechas(frm, campo) {
  try {
    const startDate = new Date(frm.doc.start_date);
    const endDate = new Date(frm.doc.end_date);

    if (endDate < startDate) {
      frm.set_value(campo, null);
      frm.clear_table("vat_withholding_voucher_item");
      frm.refresh_field("vat_withholding_voucher_item");

      throw new Error(
        "La fecha de fin no puede ser menor que la fecha de inicio.",
      );
    }
  } catch (e) {
    frappe.throw(e.message);
  }
}

function load_invoices(frm) {
  if (
    !frm.doc.supplier ||
    !frm.doc.start_date ||
    !frm.doc.end_date ||
    !frm.doc.empresa
  ) {
    return;
  }

  frm.clear_table("vat_withholding_voucher_item");

  frm.call({
    method: "get_valid_invoices",
    args: {
      supplier: frm.doc.supplier,
      start_date: frm.doc.start_date,
      end_date: frm.doc.end_date,
      company: frm.doc.empresa,
    },
    callback: function (r) {
      frm.doc.totals_grand_total = 0;
      frm.doc.totals_total_exempt = 0;
      frm.doc.totals_total = 0;
      frm.doc.totals_taxes_and_charges_added = 0;
      frm.doc.totals_tax_amount_vat = 0;

      if (r.message && r.message.length > 0) {
        r.message.forEach((invoice) => {
          let new_row = frm.add_child("vat_withholding_voucher_item");
          new_row.purchase_invoice = invoice.purchase_invoice;
          new_row.bill_no = invoice.bill_no;
          new_row.bill_control = invoice.bill_control;
          new_row.posting_date = invoice.posting_date;
          new_row.rate = invoice.rate;
          new_row.withholding_rate = invoice.withholding_rate;
          new_row.grand_total = invoice.grand_total;
          new_row.total_exempt = invoice.total_exempt;
          new_row.total = invoice.total;
          new_row.taxes_and_charges_added = invoice.taxes_and_charges_added;
          new_row.tax_amount_vat = invoice.tax_amount_vat;
          new_row.credit_note_no = invoice.credit_note_no;
          new_row.debit_note_no = invoice.debit_note_no;
          new_row.affected_invoice_number = invoice.affected_invoice_number;
          new_row.tax_amount = invoice.tax_amount;

          let negative = invoice.is_return ? -1 : 1;

          frm.doc.totals_grand_total += (invoice.grand_total || 0) * negative;
          frm.doc.totals_total_exempt += (invoice.total_exempt || 0) * negative;
          frm.doc.totals_total += (invoice.total || 0) * negative;
          frm.doc.totals_taxes_and_charges_added +=
            (invoice.taxes_and_charges_added || 0) * negative;
          frm.doc.totals_tax_amount_vat +=
            (invoice.tax_amount_vat || 0) * negative;
        });

        frm.refresh_fields();
      } else {
        frm.clear_table("vat_withholding_voucher_item");
        frm.refresh_field("vat_withholding_voucher_item");

        frm.doc.totals_grand_total = 0;
        frm.doc.totals_total_exempt = 0;
        frm.doc.totals_total = 0;
        frm.doc.totals_taxes_and_charges_added = 0;
        frm.doc.totals_tax_amount_vat = 0;
        frm.refresh_fields();

        frappe.show_alert({
          message: __(
            "No se encontraron facturas de compra que cumplan con los criterios.",
          ),
          indicator: "orange",
        });
      }
    },
  });
}

function calculate_totals(frm) {
  let total_grand_total = 0;
  let total_total_exempt = 0;
  let total_total = 0;
  let total_taxes_and_charges_added = 0;
  let total_tax_amount_vat = 0;

  frm.doc.vat_withholding_voucher_item.forEach((item) => {
    let negative = item.credit_note_no ? -1 : 1;

    total_grand_total += (item.grand_total || 0) * negative;
    total_total_exempt += (item.total_exempt || 0) * negative;
    total_total += (item.total || 0) * negative;
    total_taxes_and_charges_added +=
      (item.taxes_and_charges_added || 0) * negative;
    total_tax_amount_vat += (item.tax_amount_vat || 0) * negative;
  });

  frm.doc.totals_grand_total = total_grand_total;
  frm.doc.totals_total_exempt = total_total_exempt;
  frm.doc.totals_total = total_total;
  frm.doc.totals_taxes_and_charges_added = total_taxes_and_charges_added;
  frm.doc.totals_tax_amount_vat = total_tax_amount_vat;

  frm.refresh_fields([
    "totals_grand_total",
    "totals_total_exempt",
    "totals_total",
    "totals_taxes_and_charges_added",
    "totals_tax_amount_vat",
  ]);
}

function fields_read_only(frm, fields) {
  fields.forEach((field) => {
    frm.set_df_property(field, "read_only", true);
  });
}

/**
 * Renderiza la vista previa del documento fiscal HKA en el comprobante de retención.
 * Lee los datos desde hka_response (a diferencia de Sales Invoice que usa remarks).
 */
function render_retention_fiscal_preview(frm) {
  const wrapper = frm.fields_dict["hka_preview"];
  if (!wrapper || frm.is_new()) return;

  const raw = frm.doc.hka_response || "";
  if (!raw || !raw.includes('"urlConsulta"')) {
    wrapper.$wrapper.html("");
    return;
  }

  let hka;
  try {
    const data = JSON.parse(raw);
    const resultado = (data && data.resultado) || {};
    hka = {
      url_consulta: resultado.urlConsulta || "",
      numero_control: resultado.numeroControl || "",
      numero_documento: resultado.numeroDocumento || "",
    };
  } catch (e) {
    wrapper.$wrapper.html("");
    return;
  }

  if (!hka.numero_documento) {
    wrapper.$wrapper.html("");
    return;
  }

  const esc = frappe.utils.escape_html;
  wrapper.$wrapper.html(`
    <div class="fiscal-preview">
      <div class="fiscal-preview__header"
        onclick="this.parentElement.querySelector('.fiscal-preview__body').classList.toggle('fiscal-preview--collapsed')">
        <div class="fiscal-preview__header-left">
          <svg class="fiscal-preview__icon" width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="1" y="1" width="14" height="14" rx="2" stroke-width="1.5" fill="none"/>
            <path d="M4 5h8M4 8h6M4 11h4" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
          <span class="fiscal-preview__title">Comprobante Fiscal Digital</span>
        </div>
        <div class="fiscal-preview__header-right">
          ${hka.numero_documento ? `<span class="fiscal-preview__meta">Doc: <strong>${esc(hka.numero_documento)}</strong></span>` : ""}
          ${hka.numero_control ? `<span class="fiscal-preview__meta">Control: <strong>${esc(hka.numero_control)}</strong></span>` : ""}
          ${
            hka.url_consulta
              ? `<a href="${esc(hka.url_consulta)}"
              class="fiscal-preview__open-link"
              target="_blank" rel="noopener noreferrer"
              title="Abrir en nueva pestaña"
              onclick="event.stopPropagation();">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M9 6.5v3a1 1 0 01-1 1H2.5a1 1 0 01-1-1V4a1 1 0 011-1H5.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
                <path d="M7 1.5h3.5V5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M5 7l5.5-5.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
              </svg>
              Abrir
            </a>`
              : ""
          }
        </div>
      </div>
      <div class="fiscal-preview__body">
        <div class="fiscal-preview__loading">
          <div class="spinner-border text-muted" role="status"></div>
          <span>Descargando comprobante fiscal desde TFHKA...</span>
        </div>
      </div>
    </div>
  `);

  frappe.call({
    method: "l10n_ve.digital_invoice.tfhka_client.get_fiscal_invoice_pdf",
    args: { invoice_name: frm.doc.name, doctype: "VAT Withholding Voucher" },
    callback: function (r) {
      const body = wrapper.$wrapper.find(".fiscal-preview__body");
      if (!r.message || !r.message.base64) {
        body.html(`
          <div class="fiscal-preview__fallback">
            <p>${r.message ? r.message.error : "No se pudo cargar la vista previa."}</p>
            ${
              hka.url_consulta
                ? `<a href="${esc(hka.url_consulta)}" target="_blank" rel="noopener noreferrer">
                Ver comprobante en el portal de TFHKA →
              </a>`
                : ""
            }
          </div>
        `);
        return;
      }

      body.html(`
        <iframe
          src="data:application/pdf;base64,${r.message.base64}"
          style="width: 100%; height: 600px; border: none; display: block;"
        ></iframe>
      `);
    },
    error: function () {
      const body = wrapper.$wrapper.find(".fiscal-preview__body");
      body.html(`
        <div class="fiscal-preview__fallback">
          <p>Error al conectar con TFHKA.</p>
          ${
            hka.url_consulta
              ? `<a href="${esc(hka.url_consulta)}" target="_blank" rel="noopener noreferrer">
              Ver comprobante en el portal de TFHKA →
            </a>`
              : ""
          }
        </div>
      `);
    },
  });
}
