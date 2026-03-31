// Agregar funcion general para ejecutgar funciones de botones

frappe.ui.form.on("Sales Invoice", {
  onload: function (frm) {
    // Mover esto a una funcion

    if (frm.is_new() && !frm.doc.amended_from) {
      frm.set_value("is_void", false);
      frm.set_value("bill_no", null);
      frm.set_value("credit_note_no", null);
      frm.set_value("debit_note_no", null);
      frm.set_value("bill_control", null);
    }

    // Mover esto a una funcion

    frm.set_df_property("vat_withholding_voucher_number", "read_only", true);
    frm.set_df_property("withholding_date", "read_only", true);
    frm.set_df_property("voucher_image", "read_only", true);
    frm.set_df_property("islr_receipt_number", "read_only", true);
    frm.set_df_property("islr_date", "read_only", true);
    frm.set_df_property("voucher_image_islr", "read_only", true);

    // Mover esto a una funcion
    realtime_numeric_validation(frm, "bill_no");
    realtime_numeric_validation(frm, "bill_control");
    realtime_numeric_validation(frm, "credit_note_no");
    realtime_numeric_validation(frm, "debit_note_no");

    // Mover esto a una funcion
    toggle_document_number_fields(frm);
    toggle_vat_withholding_fields(frm);
    toggle_islr_withholding_fields(frm);

    // Mover esto a una funcion
    frm.set_df_property("total_igtf", "hidden", !Boolean(frm.doc.total_igtf));
    frm.set_df_property(
      "base_amount_igtf",
      "hidden",
      !Boolean(frm.doc.base_amount_igtf),
    );
  },

  refresh: function (frm) {
    setup_void_button(frm);

    toggle_vat_withholding_fields(frm);
    toggle_islr_withholding_fields(frm);
    set_sales_invoice_fields(frm);
    print_button_pdf(frm);

    setTimeout(() => {
      // Oculta el botón de impresión principal
      frm.page.wrapper
        .find(`button[data-original-title="${__("Print")}"]`)
        .hide();
    }, 100);

    // Mover esto a una funcion

    let has_islr_withholding = true;

    // Mover esto a una funcion
    let has_vat_withholding = false;
    if (frm.doc.taxes && frm.doc.taxes.length) {
      has_vat_withholding = frm.doc.taxes.some(
        (tax_row) =>
          tax_row.charge_type &&
          tax_row.charge_type.toLowerCase().includes("withholding"),
      );
    }

    // Mover esto a una funcion

    if (
      !frm.doc.__islocal &&
      (has_vat_withholding || has_islr_withholding) &&
      !frm.custom_buttons["Cargar Comprobante"]
    ) {
      const button_group = __("Cargar Comprobante");

      if (has_vat_withholding) {
        frm.add_custom_button(
          __("Retención de IVA"),
          () => {
            const dialog = new frappe.ui.Dialog({
              title: __("Cargar Comprobante de Retención de IVA"),
              fields: [
                {
                  label: __("Número de Comprobante"),
                  fieldname: "vat_withholding_voucher_number",
                  fieldtype: "Data",
                  reqd: 1,
                },
                {
                  label: __("Fecha de Comprobante"),
                  fieldname: "withholding_date",
                  fieldtype: "Date",
                  reqd: 1,
                },
                {
                  label: __("Imagen/PDF del Comprobante"),
                  fieldname: "voucher_image",
                  fieldtype: "Attach",
                  reqd: 0,
                },
              ],
              primary_action_label: __("Subir y Guardar"),
              primary_action: (values) => {
                const voucher_number = values.vat_withholding_voucher_number;
                if (!voucher_number || !values.withholding_date) {
                  frappe.msgprint({
                    title: __("Error de Validación"),
                    indicator: "red",
                    message: __(
                      "Debe ingresar el Número y la Fecha del Comprobante.",
                    ),
                  });
                  return;
                }
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
                frappe.call({
                  method: "l10n_ve.overrides.sales_invoice.upload_voucher_data",
                  args: {
                    docname: frm.doc.name,
                    voucher_number: values.vat_withholding_voucher_number,
                    withholding_date: values.withholding_date,
                    file_url: values.voucher_image,
                  },
                  callback: function (r) {
                    if (r.message && r.message.status === "success") {
                      frappe.msgprint(
                        __("Comprobante de IVA cargado exitosamente."),
                      );
                      frm.reload_doc();
                      dialog.hide();
                    } else if (r.message && r.message.status === "error") {
                      frappe.msgprint(
                        __("Error al guardar: " + r.message.msg),
                        "Error",
                      );
                    }
                  },
                });
              },
            });
            dialog.show();
          },
          button_group,
        );
      }
      // Mover esto a una funcion
      if (has_islr_withholding) {
        frm.add_custom_button(
          __("Retención de ISLR"),
          () => {
            const dialog = new frappe.ui.Dialog({
              title: __("Cargar Comprobante de Retención de ISLR"),
              fields: [
                {
                  label: __("Número de Comprobante ISLR"),
                  fieldname: "islr_receipt_number",
                  fieldtype: "Data",
                  reqd: 0, // No es obligatorio
                },
                {
                  label: __("Fecha de Comprobante ISLR"),
                  fieldname: "islr_date",
                  fieldtype: "Date",
                  reqd: 1, // La fecha sigue siendo obligatoria
                },
                {
                  label: __("Imagen/PDF del Comprobante ISLR"),
                  fieldname: "voucher_image_islr",
                  fieldtype: "Attach",
                  reqd: 1, // El archivo adjunto ahora es obligatorio
                },
              ],
              primary_action_label: __("Subir y Guardar"),
              primary_action: (values) => {
                if (!values.islr_date || !values.voucher_image_islr) {
                  frappe.msgprint({
                    title: __("Error de Validación"),
                    indicator: "red",
                    message: __(
                      "Debe ingresar la Fecha y adjuntar el archivo del Comprobante de ISLR.",
                    ),
                  });
                  return;
                }
                frappe.call({
                  method:
                    "l10n_ve.overrides.sales_invoice.upload_islr_voucher_data",
                  args: {
                    docname: frm.doc.name,
                    islr_receipt_number: values.islr_receipt_number,
                    islr_date: values.islr_date,
                    file_url: values.voucher_image_islr,
                  },
                  callback: function (r) {
                    if (r.message && r.message.status === "success") {
                      frappe.msgprint(
                        __("Comprobante de ISLR cargado exitosamente."),
                      );
                      frm.reload_doc();
                      dialog.hide();
                    } else if (r.message && r.message.status === "error") {
                      frappe.msgprint(
                        __("Error al guardar: " + r.message.msg),
                        "Error",
                      );
                    }
                  },
                });
              },
            });
            dialog.show();
          },
          button_group,
        );
      }
    }

    setup_exchange_difference_button(frm);

    if (frappe.boot.tfhka_enabled) {
      setup_digital_invoice_button(frm);
    }
  },

  customer: function (frm) {
    toggle_vat_withholding_fields(frm);
    frm.refresh();
  },

  is_return: function (frm) {
    toggle_document_number_fields(frm);
  },

  is_debit_note: function (frm) {
    toggle_document_number_fields(frm);
  },
});

function toggle_document_number_fields(frm) {
  const is_credit_note = frm.doc.is_return;

  const is_debit_note = frm.doc.is_debit_note;

  const is_return_doc = is_credit_note || is_debit_note;

  frm.toggle_display(["debit_note_no"], is_debit_note);
  frm.toggle_display(["credit_note_no"], is_credit_note);

  frm.toggle_display(["bill_no"], !is_return_doc);
  frm.toggle_display(["affected_invoice_number"], is_return_doc);
  frm.toggle_display(["bill_control"], true);

  if (is_return_doc) {
    if (frm.doc.bill_no) {
      frm.set_value("bill_no", null);
    }
  } else {
    if (frm.doc.credit_note_no) {
      frm.set_value("credit_note_no", null);
    }

    if (frm.doc.debit_note_no) {
      frm.set_value("debit_note_no", null);
    }
  }
}

function toggle_vat_withholding_fields(frm) {
  const fields_to_toggle = [
    "voucher_image",
    "withholding_date",
    "vat_withholding_voucher_number",
  ];

  frm.toggle_display(fields_to_toggle, false);

  const has_voucher_data = frm.doc.vat_withholding_voucher_number;

  if (has_voucher_data) {
    frm.toggle_display(fields_to_toggle, true);
    return;
  }

  if (frm.doc.customer) {
    frappe.db
      .get_value("Customer", frm.doc.customer, "is_special_taxpayer")
      .then((r) => {
        if (r.message && r.message.is_special_taxpayer) {
          frm.toggle_display(fields_to_toggle, true);
        }
      });
  }
}

function toggle_islr_withholding_fields(frm) {
  const fields_to_toggle = [
    "islr_receipt_number",
    "islr_date",
    "voucher_image_islr",
  ];

  frm.toggle_display(fields_to_toggle, false);

  const has_voucher_data = frm.doc.islr_receipt_number;
  if (has_voucher_data) {
    frm.toggle_display(fields_to_toggle, true);
    return;
  }

  const has_islr_tax = (frm.doc.taxes || []).some(
    (tax) => tax.charge_type === "ISLR",
  );
  if (has_islr_tax) {
    frm.toggle_display(fields_to_toggle, true);
  }
}

function set_sales_invoice_fields(frm) {
  for (const field of [
    "base_in_words",
    "base_total_taxes_and_charges",
    "section_break_43",
    "base_rounding_adjustment",
  ]) {
    frm.set_df_property(field, "hidden", true);
  }

  let base_total_taxes_and_charges = frm.get_field(
    "base_total_taxes_and_charges",
  ).$wrapper;

  let base_rounding_adjustment = frm.get_field(
    "base_rounding_adjustment",
  ).$wrapper;

  let base_rounded_total = frm.get_field("base_rounded_total").$wrapper;
  let base_in_words = frm.get_field("base_in_words").$wrapper;

  base_rounding_adjustment.insertBefore(base_total_taxes_and_charges);
  base_rounded_total.insertBefore(base_total_taxes_and_charges);
  base_in_words.insertBefore(base_total_taxes_and_charges);
}

function print_button_pdf(frm) {
  if (!frm.custom_buttons["Generar PDF de Factura"]) {
    frm.add_custom_button(__("Generar PDF de Factura"), () => {
      generate_custom_invoice_preview(frm);
    });
  }
}

/**
 * @param {object} frm
 */
function setup_void_button(frm) {
  if (frm.doc.docstatus === 2 && !frm.doc.is_void) {
    frm.add_custom_button(
      __("Anular Documento"),
      function () {
        frappe.confirm(
          __("¿Estás seguro de que deseas anular este documento?"),
          () => {
            frappe.call({
              method: "l10n_ve.overrides.sales_invoice.void_document",
              args: {
                doctype: frm.doc.doctype,
                name: frm.doc.name,
              },
              callback: function (r) {
                if (!r.exc) {
                  frappe.show_alert({
                    message: __("Documento anulado correctamente."),
                    indicator: "green",
                  });
                  frm.reload_doc();
                }
              },
              error: () => {
                frappe.show_alert({
                  message: __("Ocurrió un error al anular el documento."),
                  indicator: "red",
                });
              },
            });
          },
        );
      },
      __("Acciones"),
    );
  }
}

/**
 * Botón para registrar diferencial cambiario
 * cuando la factura tiene saldo pendiente por diferencia de tasas.
 * @param {object} frm
 */
function setup_exchange_difference_button(frm) {
  if (
    frm.doc.docstatus === 1 &&
    frm.doc.outstanding_amount &&
    flt(frm.doc.outstanding_amount) !== 0 &&
    frm.doc.currency !== frm.doc.party_account_currency
  ) {
    frm.add_custom_button(
      __("Generar Diferencial Cambiario"),
      function () {
        const outstanding = flt(frm.doc.outstanding_amount);
        const tipo = outstanding > 0 ? "Pérdida" : "Ganancia";

        frappe.confirm(
          `¿Desea registrar un diferencial cambiario (${tipo}) por <b>${frappe.format(
            Math.abs(outstanding),
            { fieldtype: "Currency", currency: frm.doc.party_account_currency },
          )}</b>?<br><br>Se creará y enviará un Asiento Contable automáticamente.`,
          () => {
            frappe.call({
              method:
                "l10n_ve.overrides.sales_invoice.create_exchange_difference_entry",
              args: { docname: frm.doc.name },
              freeze: true,
              freeze_message: "Registrando diferencial cambiario...",
              callback: function (r) {
                if (r.message && r.message.status === "success") {
                  frappe.show_alert({
                    message: __(
                      `Diferencial cambiario registrado: ${r.message.journal_entry}`,
                    ),
                    indicator: "green",
                  });
                  frm.reload_doc();
                }
              },
            });
          },
        );
      },
      __("Acciones"),
    );
  }
}

/**
 * Botón para enviar manualmente la factura a Facturación Digital (TFHKA).
 * Solo visible si la factura está enviada y el status NO es "Sent".
 * @param {object} frm
 */
function setup_digital_invoice_button(frm) {
  // Solo visible si la factura está enviada (1) 
  // y si NO existe ya el JSON de HKA en remarks (evita re-envíos)
  if (frm.doc.docstatus !== 1 || (frm.doc.remarks && frm.doc.remarks.includes('"numeroControl"'))) {
    return;
  }

  frm.add_custom_button(
    __("Enviar Facturación Digital"),
    function () {
      frappe.confirm(
        __(
          "¿Estás seguro de enviar esta factura a Facturación Digital (TFHKA)?<br><br>" +
            "<b>Esta acción no se puede deshacer.</b>",
        ),
        () => {
          frappe.call({
            method:
              "l10n_ve.digital_invoice.tfhka_integration.send_invoice_manually",
            args: { invoice_name: frm.doc.name },
            freeze: true,
            freeze_message: __("Enviando a TFHKA..."),
            callback: function (r) {
              if (!r.exc) {
                const status = r.message;
                if (status === "Sent") {
                  frappe.show_alert({
                    message: __("Enviado exitosamente a TFHKA."),
                    indicator: "green",
                  });
                } else {
                  frappe.show_alert({
                    message: __(
                      "Hubo un error al enviar. Revisa el Log de Facturación Digital.",
                    ),
                    indicator: "red",
                  });
                }
                frm.reload_doc();
              }
            },
          });
        },
      );
    },
    __("Acciones"),
  );
}
