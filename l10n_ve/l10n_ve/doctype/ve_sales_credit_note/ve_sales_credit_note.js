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
    // La NC porta siempre la tasa de la factura afectada: se muestra pero no
    // se edita (el servidor la re-aplica en cada validate del borrador).
    frm.set_df_property("conversion_rate", "read_only", 1);
    frm.set_df_property("plc_conversion_rate", "read_only", 1);
    calculate_base_total_with_vat(frm);

    // Indicador fiscal VE (centralizado en sales_billing_indicators.js)
    set_ve_form_indicator(frm, { doc_type: "credit_note" });

    // Vista previa del asiento contable (idéntica a Factura de Venta)
    // Solo disponible en borradores ya guardados — usa el mismo motor
    // que la SI nativa: make_gl_entries() con rollback automático
    erpnext.accounts.ledger_preview.show_accounting_ledger_preview(frm);

    // Banner azul: enlace a la SI original (pendiente de emisión HKA)
    if (frm.doc.return_against && !frm.doc.bill_no) {
      original_invoice_link("Sales Invoice", frm.doc.return_against).then((link) => {
        frm.set_intro(__("Nota de Crédito aplicada a la factura: {0}", [link]), "blue");
      });
    }

    // Banner verde: NC emitida en HKA (solo documentos activos/submit)
    if (frm.doc.bill_no && frm.doc.docstatus === 1) {
      original_invoice_link("Sales Invoice", frm.doc.return_against).then((link) => {
        frm.set_intro(
          __("✅ Emitida ante HKA con número: <b>{0}</b> | Factura original: {1}", [
            frappe.utils.escape_html(frm.doc.bill_no),
            link,
          ]),
          "green",
        );
      });
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

    // ── Grupo "Cargar Comprobante": Retenciones (IVA e ISLR) ──────────────
    setup_nc_withholding_buttons(frm);
    setup_nc_remove_withholding_buttons(frm);
  },

  // Al seleccionar la factura original: auto-carga cliente, branch, tasa e
  // ítems en positivo. No hay handler de posting_date: la tasa de la NC es
  // la de la factura afectada y no se re-deriva por fecha.
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

// ------------------------------------------------------------------ //
// Retenciones VE: Cargar Comprobante (IVA e ISLR)                     //
// ------------------------------------------------------------------ //

function setup_nc_withholding_buttons(frm) {
  if (frm.doc.docstatus === 2 || frm.doc.__islocal || !frm.doc.customer) {
    return;
  }

  const has_vat_withholding = frm.doc.taxes
    ? frm.doc.taxes.some((t) => t.charge_type === "VAT Withholding")
    : false;
  const has_islr_withholding = frm.doc.taxes
    ? frm.doc.taxes.some((t) => t.charge_type === "ISLR")
    : false;

  frappe.db.get_value(
    "Customer",
    frm.doc.customer,
    [
      "is_special_taxpayer",
      "tax_withholding_category",
      "tabulator_islr",
      "type_of_person",
    ],
    (customer_data) => {
      if (!customer_data) return;

      const show_vat =
        has_vat_withholding ||
        (customer_data.is_special_taxpayer &&
          customer_data.tax_withholding_category);
      const show_islr =
        has_islr_withholding ||
        (customer_data.is_special_taxpayer && customer_data.tabulator_islr);

      frm.page.remove_inner_button(
        __("Retención de IVA"),
        __("Cargar Comprobante"),
      );
      frm.page.remove_inner_button(
        __("Retención de ISLR"),
        __("Cargar Comprobante"),
      );

      if (show_vat) {
        frm.add_custom_button(
          __("Retención de IVA"),
          () => {
            if (frm.doc.docstatus === 0 || has_vat_withholding) {
              open_nc_upload_vat_modal(frm);
            } else {
              apply_nc_vat_withholding(frm, customer_data);
            }
          },
          __("Cargar Comprobante"),
        );
      }

      if (show_islr) {
        frm.add_custom_button(
          __("Retención de ISLR"),
          () => {
            if (frm.doc.docstatus === 0 || has_islr_withholding) {
              open_nc_upload_islr_modal(frm);
            } else {
              apply_nc_islr_withholding(frm, customer_data);
            }
          },
          __("Cargar Comprobante"),
        );
      }
    },
  );
}

function open_nc_upload_vat_modal(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Cargar Comprobante de Retención de IVA"),
    fields: [
      {
        label: __("Número de Comprobante"),
        fieldname: "vat_withholding_voucher_number",
        fieldtype: "Data",
        reqd: 1,
        default: frm.doc.vat_withholding_voucher_number,
      },
      {
        label: __("Fecha de registro"),
        fieldname: "withholding_date",
        fieldtype: "Date",
        default: frm.doc.withholding_date || frappe.datetime.get_today(),
        reqd: 1,
        description: __(
          "Esta fecha determina el período fiscal en el que la retención viajará al Libro de Ventas.",
        ),
      },
      {
        label: __("Fecha de Comprobante"),
        fieldname: "registration_date",
        fieldtype: "Date",
        default: frm.doc.vat_registration_date || frappe.datetime.get_today(),
        reqd: 1,
      },
      {
        label: __("Imagen/PDF del Comprobante"),
        fieldname: "voucher_image",
        fieldtype: "Attach",
        reqd: 1,
        default: frm.doc.voucher_image,
      },
    ],
    primary_action_label: __("Subir y Guardar"),
    primary_action: (values) => {
      const voucher_number = values.vat_withholding_voucher_number;
      const regex = /^\d{14}$/;
      if (!regex.test(voucher_number)) {
        frappe.msgprint({
          title: __("Error de Formato"),
          indicator: "red",
          message: __(
            "El Número de Comprobante debe tener exactamente 14 caracteres y solo puede contener números.",
          ),
        });
        return;
      }
      if (!validate_nc_voucher_file(values.voucher_image, ["pdf", "jpg", "jpeg", "png"])) {
        return;
      }

      if (frm.doc.docstatus === 0) {
        frm.set_value("vat_withholding_voucher_number", voucher_number);
        frm.set_value("withholding_date", values.withholding_date);
        frm.set_value("vat_registration_date", values.registration_date);
        frm.set_value("voucher_image", values.voucher_image);

        frm.save().then(() => {
          frappe.show_alert({
            message: __("Nota de Crédito guardada con los datos del comprobante de IVA."),
            indicator: "green",
          });
          dialog.hide();
        });
      } else {
        frappe.call({
          method: "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.upload_credit_note_voucher_data",
          args: {
            docname: frm.doc.name,
            withholding_type: "VAT",
            voucher_number: voucher_number,
            withholding_date: values.withholding_date,
            file_url: values.voucher_image,
            registration_date: values.registration_date,
          },
          freeze: true,
          freeze_message: __("Guardando comprobante..."),
          callback: function (r) {
            if (r.message && r.message.status === "success") {
              frappe.show_alert({
                message: __(r.message.msg),
                indicator: "green",
              });
              frm.reload_doc();
              dialog.hide();
            }
          },
        });
      }
    },
  });
  dialog.show();
}

function open_nc_upload_islr_modal(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Cargar Comprobante de Retención de ISLR"),
    fields: [
      {
        label: __("Número de Comprobante ISLR"),
        fieldname: "islr_receipt_number",
        fieldtype: "Data",
        reqd: 0,
        default: frm.doc.islr_receipt_number,
      },
      {
        label: __("Fecha de registro"),
        fieldname: "islr_date",
        fieldtype: "Date",
        default: frm.doc.islr_date || frappe.datetime.get_today(),
        reqd: 1,
        description: __(
          "Esta fecha determina el período fiscal de la retención.",
        ),
      },
      {
        label: __("Fecha de Comprobante ISLR"),
        fieldname: "registration_date",
        fieldtype: "Date",
        default: frm.doc.islr_registration_date || frappe.datetime.get_today(),
        reqd: 1,
      },
      {
        label: __("Imagen/PDF del Comprobante ISLR"),
        fieldname: "voucher_image_islr",
        fieldtype: "Attach",
        reqd: 1,
        default: frm.doc.voucher_image_islr,
      },
    ],
    primary_action_label: __("Subir y Guardar"),
    primary_action: (values) => {
      if (!validate_nc_voucher_file(values.voucher_image_islr, ["pdf", "jpg", "jpeg", "png"])) {
        return;
      }

      if (frm.doc.docstatus === 0) {
        frm.set_value("islr_receipt_number", values.islr_receipt_number);
        frm.set_value("islr_date", values.islr_date);
        frm.set_value("islr_registration_date", values.registration_date);
        frm.set_value("voucher_image_islr", values.voucher_image_islr);

        frm.save().then(() => {
          frappe.show_alert({
            message: __("Nota de Crédito guardada con los datos del comprobante de ISLR."),
            indicator: "green",
          });
          dialog.hide();
        });
      } else {
        frappe.call({
          method: "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.upload_credit_note_voucher_data",
          args: {
            docname: frm.doc.name,
            withholding_type: "ISLR",
            voucher_number: values.islr_receipt_number,
            withholding_date: values.islr_date,
            file_url: values.voucher_image_islr,
            registration_date: values.registration_date,
          },
          freeze: true,
          freeze_message: __("Guardando comprobante..."),
          callback: function (r) {
            if (r.message && r.message.status === "success") {
              frappe.show_alert({
                message: __(r.message.msg),
                indicator: "green",
              });
              frm.reload_doc();
              dialog.hide();
            }
          },
        });
      }
    },
  });
  dialog.show();
}

function apply_nc_vat_withholding(frm, customer_data) {
  frappe.db.get_value(
    "Company",
    frm.doc.company,
    "sales_vat_withholding_account",
    (co) => {
      let default_vat_account = co ? co.sales_vat_withholding_account : null;

      const proceed = (account, rate) => {
        let vat_base = (frm.doc.taxes || [])
          .filter((t) => t.charge_type === "VAT")
          .reduce((sum, t) => sum + flt(t.base_tax_amount), 0);

        if (!vat_base) {
          let conversion = flt(frm.doc.conversion_rate) || 1.0;
          vat_base = (frm.doc.taxes || [])
            .filter((t) => t.charge_type === "VAT")
            .reduce((sum, t) => sum + flt(t.tax_amount) * conversion, 0);
        }

        let suggested_amount = flt(vat_base * (rate / 100.0), 2);
        open_nc_withholding_dialog(frm, "VAT", account, rate, suggested_amount);
      };

      if (default_vat_account) {
        get_nc_vat_category_rate(customer_data.tax_withholding_category, frm.doc.company, (rate) => {
          proceed(default_vat_account, rate);
        });
      } else {
        frappe.db.get_value(
          "Tax Withholding Account",
          {
            parent: customer_data.tax_withholding_category,
            company: frm.doc.company,
          },
          "account",
          (twa) => {
            let fallback_account = twa ? twa.account : "";
            get_nc_vat_category_rate(customer_data.tax_withholding_category, frm.doc.company, (rate) => {
              proceed(fallback_account, rate);
            });
          },
        );
      }
    },
  );
}

function apply_nc_islr_withholding(frm, customer_data) {
  const tabulator_name = customer_data.tabulator_islr;
  if (!tabulator_name) {
    frappe.msgprint({
      title: __("Sin Tabulador"),
      message: __("El cliente no tiene asignado un Tabulador de ISLR."),
      indicator: "orange",
    });
    return;
  }

  frappe.db.get_doc("Tabulator ISLR", tabulator_name).then((tab_doc) => {
    let rate = 0;
    let client_person_type = customer_data.type_of_person;
    let target_row = null;

    if (tab_doc.aliquot && tab_doc.aliquot.length > 0) {
      if (client_person_type) {
        target_row = tab_doc.aliquot.find((r) => r.types_of_person === client_person_type);
      }
      if (!target_row) {
        target_row = tab_doc.aliquot[0];
      }
    }
    if (target_row) {
      rate = flt(target_row.aliquot);
    }

    let net_base = flt(frm.doc.base_net_total);
    let suggested_amount = flt(net_base * (rate / 100.0), 2);

    frappe.db.get_value(
      "Company",
      frm.doc.company,
      "sales_islr_withholding_account",
      (co) => {
        let islr_account = co ? co.sales_islr_withholding_account : "";
        open_nc_withholding_dialog(frm, "ISLR", islr_account, rate, suggested_amount);
      },
    );
  });
}

function open_nc_withholding_dialog(frm, type, default_account, suggested_rate, suggested_amount) {
  const is_vat = type === "VAT";
  const label = is_vat ? __("IVA") : __("ISLR");

  const fields = [
    {
      label: __("Nota de Crédito"),
      fieldname: "credit_note",
      fieldtype: "Link",
      options: "VE Sales Credit Note",
      default: frm.doc.name,
      read_only: 1,
    },
    {
      label: __("Factura Afectada"),
      fieldname: "return_against",
      fieldtype: "Link",
      options: "Sales Invoice",
      default: frm.doc.return_against,
      read_only: 1,
    },
    {
      label: __("Cliente"),
      fieldname: "customer",
      fieldtype: "Link",
      options: "Customer",
      default: frm.doc.customer,
      read_only: 1,
    },
    {
      label: __("Cuenta de Retención"),
      fieldname: "tax_account",
      fieldtype: "Link",
      options: "Account",
      reqd: 1,
      default: default_account,
      get_query: () => ({
        filters: {
          company: frm.doc.company,
          is_group: 0,
        },
      }),
    },
    {
      label: __("Alícuota / Porcentaje Retención (%)"),
      fieldname: "rate",
      fieldtype: "Percent",
      default: suggested_rate || 75.0,
      reqd: 1,
      onchange: function () {
        const new_rate = flt(dialog.get_value("rate"));
        if (is_vat) {
          const vat_base = (frm.doc.taxes || [])
            .filter((t) => t.charge_type === "VAT")
            .reduce((sum, t) => sum + flt(t.base_tax_amount), 0);
          dialog.set_value("amount", flt(vat_base * (new_rate / 100.0), 2));
        } else {
          const net_base = flt(frm.doc.base_net_total);
          dialog.set_value("amount", flt(net_base * (new_rate / 100.0), 2));
        }
      },
    },
    {
      label: __("Monto Estimado de Retención (Bs)"),
      fieldname: "amount",
      fieldtype: "Currency",
      default: suggested_amount || 0,
      read_only: 1,
      description: __("Monto en moneda base (Bs) que se ajustará contablemente."),
    },
    {
      label: is_vat ? __("Número de Comprobante IVA") : __("Número de Comprobante ISLR"),
      fieldname: "voucher_number",
      fieldtype: "Data",
      reqd: is_vat ? 1 : 0,
      description: is_vat ? __("Debe tener exactamente 14 caracteres numéricos.") : "",
    },
    {
      label: __("Fecha de registro"),
      fieldname: "withholding_date",
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
      reqd: 1,
      description: __(
        "Esta fecha determina el período fiscal en el que la retención viajará al Libro de Ventas.",
      ),
    },
    {
      label: is_vat ? __("Fecha de Comprobante") : __("Fecha de Comprobante ISLR"),
      fieldname: "registration_date",
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
      reqd: 1,
    },
    {
      label: __("Archivo de Comprobante (PDF/Imagen)"),
      fieldname: "file_url",
      fieldtype: "Attach",
      reqd: 1,
    },
  ];

  const dialog = new frappe.ui.Dialog({
    title: __("Cargar Retención de {0}", [label]),
    fields: fields,
    primary_action_label: __("Aplicar y Contabilizar"),
    primary_action(values) {
      if (!values.tax_account) {
        frappe.msgprint({
          title: __("Cuenta requerida"),
          message: __("Debe indicar la cuenta contable de retención."),
          indicator: "red",
        });
        return;
      }
      if (is_vat && values.voucher_number) {
        const regex = /^\d{14}$/;
        if (!regex.test(values.voucher_number)) {
          frappe.msgprint({
            title: __("Error de Formato"),
            indicator: "red",
            message: __(
              "El Número de Comprobante de IVA debe tener exactamente 14 caracteres numéricos.",
            ),
          });
          return;
        }
      }
      if (!validate_nc_voucher_file(values.file_url, ["pdf", "jpg", "jpeg", "png"])) {
        return;
      }

      frappe.call({
        method: "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.apply_credit_note_withholding",
        args: {
          credit_note_name: frm.doc.name,
          withholding_type: type,
          tax_account: values.tax_account,
          voucher_number: values.voucher_number,
          withholding_date: values.withholding_date,
          registration_date: values.registration_date,
          file_url: values.file_url,
          rate: values.rate,
        },
        freeze: true,
        freeze_message: __("Aplicando retención y generando asiento contable..."),
        callback(r) {
          if (r.message && r.message.status === "success") {
            dialog.hide();
            frappe.show_alert({
              message: __(r.message.msg),
              indicator: "green",
            });
            frm.reload_doc();
          }
        },
      });
    },
  });

  dialog.show();
}

function get_nc_vat_category_rate(category, company, callback) {
  if (!category) {
    callback(75.0);
    return;
  }
  frappe.db
    .get_doc("Tax Withholding Category", category)
    .then((doc) => {
      let rate = null;
      if (doc.accounts && doc.accounts.length > 0) {
        let account_row = doc.accounts.find((a) => a.company === company);
        if (account_row && doc.rates && doc.rates.length > 0) {
          rate = flt(doc.rates[0].tax_withholding_rate);
        }
      }
      if (!rate) {
        rate = flt(doc.default_rate) || flt(doc.rate) || 75.0;
      }
      callback(rate);
    })
    .catch(() => {
      callback(75.0);
    });
}

function validate_nc_voucher_file(file_url, allowed_extensions) {
  if (!file_url) return true;
  const ext = file_url.split(".").pop().toLowerCase();
  if (!allowed_extensions.includes(ext)) {
    frappe.msgprint({
      title: __("Archivo no permitido"),
      message: __("Solo se permiten archivos: {0}.", [
        allowed_extensions.map((e) => e.toUpperCase()).join(", "),
      ]),
      indicator: "red",
    });
    return false;
  }
  return true;
}

// ------------------------------------------------------------------ //
// Retenciones VE: Quitar Retención (Reverso y Limpieza)               //
// ------------------------------------------------------------------ //

function setup_nc_remove_withholding_buttons(frm) {
  if (frm.doc.docstatus !== 1) {
    return;
  }

  frm.page.remove_inner_button(__("Retención de IVA"), __("Quitar Retención"));
  frm.page.remove_inner_button(__("Retención de ISLR"), __("Quitar Retención"));

  const tipos = [
    {
      type: "VAT",
      charge_type: "VAT Withholding",
      label: __("Retención de IVA"),
      voucher_field: "vat_withholding_voucher_number",
    },
    {
      type: "ISLR",
      charge_type: "ISLR",
      label: __("Retención de ISLR"),
      voucher_field: "islr_receipt_number",
    },
  ];

  tipos.forEach((tipo) => {
    const has_tax = (frm.doc.taxes || []).some(
      (fila) => fila.charge_type === tipo.charge_type && flt(fila.tax_amount)
    );
    const has_voucher = !!frm.doc[tipo.voucher_field];

    if (has_tax || has_voucher) {
      frm.add_custom_button(
        tipo.label,
        () => remove_credit_note_withholding_dialog(frm, tipo.type),
        __("Quitar Retención"),
      );
    }
  });
}

function remove_credit_note_withholding_dialog(frm, withholding_type) {
  const etiqueta = withholding_type === "VAT" ? __("IVA") : __("ISLR");
  frappe.confirm(
    __(
      "Se va a quitar la retención de {0} de la Nota de Crédito {1}. Si existe un asiento contable asociado, se asentará el reverso correspondiente. ¿Desea continuar?",
      [etiqueta, frm.doc.name],
    ),
    () => {
      frappe.dom.freeze(__("Quitando la retención y asentando el reverso..."));
      frappe.call({
        method:
          "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.remove_credit_note_withholding",
        args: {
          credit_note_name: frm.doc.name,
          withholding_type: withholding_type,
        },
        callback: function (r) {
          frappe.dom.unfreeze();
          if (r.message && r.message.status === "success") {
            frappe.show_alert({ message: r.message.msg, indicator: "green" });
            frm.reload_doc();
          }
        },
        error: function () {
          frappe.dom.unfreeze();
        },
      });
    },
  );
}

