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
    // Resetear visibilidad del botón primario en cada refresh para evitar que
    // el hide() de setup_hka_void_banners persista al navegar a otra factura
    // (problema de SPA: Frappe reutiliza el objeto page entre formularios).
    frm.page.btn_primary.show();

    setup_void_button(frm);
    setup_hka_void_button(frm);
    setup_hka_void_banners(frm);
    setup_hka_voided_consulta_button(frm);
    setup_replacement_invoice_button(frm);

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
    setup_hka_consulta_button(frm);
    render_fiscal_invoice_preview(frm);
    setup_credit_note_button(frm);
    setup_debit_note_button(frm);

    if (frappe.boot.tfhka_enabled) {
      setup_digital_invoice_button(frm);
    }

    set_ve_form_indicator(frm);
  },

  customer: function (frm) {
    toggle_vat_withholding_fields(frm);
    frm.refresh();
    apply_ve_exchange_rate_from_date(frm);
  },

  posting_date: function (frm) {
    apply_ve_exchange_rate_from_date(frm);
  },

  // Intercepta el reset que hace ERPNext cuando apply_price_list devuelve
  // plc_conversion_rate calculado con la fecha exacta (no la del 1° del mes).
  // Solo activa si TFHKA (facturación digital) está habilitado.
  plc_conversion_rate: function (frm) {
    if (!frappe.boot.tfhka_enabled) return;
    const target = frm._l10n_ve_conv_rate;
    if (!target || frm.doc.docstatus !== 0) return;

    let corrected = false;
    if (Math.abs(flt(frm.doc.plc_conversion_rate) - target) > 0.0001) {
      frm.doc.plc_conversion_rate = target;
      frm.refresh_field("plc_conversion_rate");
      corrected = true;
    }
    if (Math.abs(flt(frm.doc.conversion_rate) - target) > 0.0001) {
      frm.doc.conversion_rate = target;
      frm.refresh_field("conversion_rate");
      corrected = true;
    }
    // Marcar como modificado solo si hubo corrección real.
    if (corrected) frm.dirty();
  },

  is_return: function (frm) {
    toggle_document_number_fields(frm);
  },

  is_debit_note: function (frm) {
    toggle_document_number_fields(frm);
  },
});

/**
 * Indicador compuesto para el formulario de Factura de Venta.
 * Combina el estado fiscal (Emitida/Pendiente) con el estado de pago.
 * @param {object} frm
 */
function set_ve_form_indicator(frm) {
  if (frm.doc.docstatus === 2 && frm.doc.is_void) {
    setTimeout(() => {
      frm.page.set_indicator(__("Anulado"), "red");
    }, 0);
    return;
  }

  if (frm.doc.docstatus !== 1) return;

  // SI legacy que son NC o ND (is_return / is_debit_note)
  if (frm.doc.is_return) return;
  if (frm.doc.is_debit_note) return;

  setTimeout(() => {
    let fiscal = frm.doc.bill_no ? __("Emitida") : __("Pendiente");

    let payment, color;
    const status = frm.doc.status;

    if (status === "Paid") {
      payment = __("Pagado");
      color = "green";
    } else if (status === "Credit Note Issued") {
      payment = __("NC Aplicada");
      color = "gray";
    } else if (status === "Debit Note Issued") {
      payment = __("ND Aplicada");
      color = "gray";
    } else if (status.includes("Partly Paid")) {
      payment = __("Parcial");
      color = "yellow";
    } else {
      payment = __("Por Cobrar");
      color = frm.doc.bill_no ? "blue" : "orange";
    }

    // Advertencia de comprobante faltante integrada en el indicador
    let indicator_label = `${fiscal} - ${payment}`;
    if (
      flt(frm.doc.total_withholding) > 0 &&
      !frm.doc.vat_withholding_voucher_number
    ) {
      indicator_label += " · Falta comprobante de retención de IVA";
      color = "orange";
    }

    frm.page.set_indicator(indicator_label, color);
  }, 0);
}

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
  // Cuando HKA está activo, el PDF se genera desde la imprenta digital
  if (frappe.boot.tfhka_enabled) return;

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
 * Muestra un modal de vista previa con todos los datos antes de enviar.
 * @param {object} frm
 */
function setup_digital_invoice_button(frm) {
  if (
    frm.doc.docstatus !== 1 ||
    (frm.doc.remarks && frm.doc.remarks.includes('"numeroControl"'))
  ) {
    return;
  }

  frm.add_custom_button(
    __("Enviar Facturación Digital"),
    function () {
      frappe.call({
        method:
          "l10n_ve.digital_invoice.tfhka_integration.get_invoice_preview_data",
        args: { invoice_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Cargando vista previa..."),
        callback: function (r) {
          if (r.exc || !r.message) return;
          show_hka_preview_dialog(frm, r.message);
        },
      });
    },
    __("Factura Digital"),
  );
}

/**
 * Renderiza y muestra el modal de vista previa HKA.
 * @param {object} frm
 * @param {object} d  Datos devueltos por get_invoice_preview_data
 */
function show_hka_preview_dialog(frm, d) {
  const items_html = d.items
    .map(
      (item) => `
    <tr>
      <td>
        <span class="hka-preview__item-code">${frappe.utils.escape_html(item.code)}</span>
        ${frappe.utils.escape_html(item.description)}
        <span class="hka-preview__iva-badge ${item.is_exempt ? "hka-preview__iva-badge--exento" : "hka-preview__iva-badge--gravado"}">
          ${item.is_exempt ? "EXENTO" : "IVA " + item.iva_rate + "%"}
        </span>
      </td>
      <td class="right">${frappe.utils.escape_html(item.qty)}</td>
      <td class="right">$ ${frappe.utils.escape_html(item.rate_usd)}</td>
      <td class="right">$ ${frappe.utils.escape_html(item.valor_iva_usd)}</td>
      <td class="right"><strong>$ ${frappe.utils.escape_html(item.total_item_usd)}</strong></td>
    </tr>
  `,
    )
    .join("");

  const preview_html = `
    <div class="hka-preview">

      <!-- HEADER -->
      <div class="hka-preview__header">

        <div class="hka-preview__doc-numbers">
          <div class="hka-preview__doc-num-item">
            <span class="hka-preview__doc-num-label">N° Documento</span>
            <span class="hka-preview__doc-num-value">
              ${frappe.utils.escape_html(d.bill_no_preview)}
              <span class="hka-preview__badge hka-preview__badge--orange">Proyectado</span>
            </span>
          </div>
          <div class="hka-preview__doc-num-item">
            <span class="hka-preview__doc-num-label">N° Control</span>
            <span class="hka-preview__doc-num-value">
              ${frappe.utils.escape_html(d.control_no_preview)}
              <span class="hka-preview__badge hka-preview__badge--orange">Proyectado</span>
            </span>
          </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:12px;">
          <div>
            <p class="hka-preview__total-label">Total a Pagar — ${frappe.utils.escape_html(d.invoice_name)}</p>
            <div style="display:flex;align-items:baseline;gap:6px;">
              <span class="hka-preview__total-usd">$ ${frappe.utils.escape_html(d.total_usd)}</span>
              <span class="hka-preview__total-currency">${frappe.utils.escape_html(d.currency)}</span>
            </div>
          </div>
          <div style="text-align:right;">
            <p style="font-size:10px;opacity:0.75;margin:0 0 3px;letter-spacing:0.5px;">
              1 USD = Bs. ${frappe.utils.escape_html(d.tasa_bcv)}
            </p>
            <p class="hka-preview__total-bs">Bs. ${frappe.utils.escape_html(d.total_bs)}</p>
            <p class="hka-preview__total-bs-label">Bolívares Digitales</p>
          </div>
        </div>
      </div>

      <!-- BODY -->
      <div class="hka-preview__body">

        <!-- EMISOR / CLIENTE -->
        <div class="hka-preview__parties">
          <div class="hka-preview__party">
            <div class="hka-preview__avatar hka-preview__avatar--company">
              ${frappe.utils.escape_html(d.company_name.charAt(0))}
            </div>
            <div>
              <p class="hka-preview__party-name">${frappe.utils.escape_html(d.company_name)}</p>
              <p class="hka-preview__party-rif">RIF: ${frappe.utils.escape_html(d.company_tax_id)}</p>
              <p class="hka-preview__party-address">${frappe.utils.escape_html(d.company_address)}</p>
              ${d.company_phone ? `<p class="hka-preview__party-address">☎ ${frappe.utils.escape_html(d.company_phone)}</p>` : ""}
              ${d.company_website ? `<p class="hka-preview__party-address">🌐 ${frappe.utils.escape_html(d.company_website)}</p>` : ""}
            </div>
          </div>
          <div class="hka-preview__party">
            <div class="hka-preview__avatar hka-preview__avatar--client">
              ${frappe.utils.escape_html(d.customer_name.charAt(0))}
            </div>
            <div>
              <p class="hka-preview__party-name">${frappe.utils.escape_html(d.customer_name)}</p>
              <p class="hka-preview__party-rif">RIF: ${frappe.utils.escape_html(d.customer_tax_id)}</p>
              <p class="hka-preview__party-address">${frappe.utils.escape_html(d.customer_address)}</p>
              ${d.customer_phone ? `<p class="hka-preview__party-address">☎ ${frappe.utils.escape_html(d.customer_phone)}</p>` : ""}
              ${d.customer_email ? `<p class="hka-preview__party-address">✉ ${frappe.utils.escape_html(d.customer_email)}</p>` : ""}
            </div>
          </div>
        </div>

        <!-- FECHAS Y HORA -->
        <div class="hka-preview__section">
          <p class="hka-preview__section-title">Fechas y Hora de Emisión</p>
          <div class="hka-preview__grid hka-preview__grid--4">
            <div class="hka-preview__field"><label>Fecha Emisión</label><span>${frappe.utils.escape_html(d.fecha_emision)}</span></div>
            <div class="hka-preview__field"><label>Hora Emisión</label><span>${frappe.utils.escape_html(d.hora_emision)}</span></div>
            <div class="hka-preview__field"><label>Fecha Vencimiento</label><span>${frappe.utils.escape_html(d.fecha_vencimiento)}</span></div>
            <div class="hka-preview__field"><label>Fecha Asignación</label><span>${frappe.utils.escape_html(d.fecha_asignacion)}</span></div>
          </div>
        </div>

        <!-- SERIE Y OPERACIÓN -->
        <div class="hka-preview__section">
          <p class="hka-preview__section-title">Serie y Datos de la Imprenta</p>
          <div class="hka-preview__grid hka-preview__grid--2">
            <div class="hka-preview__field"><label>Serie TFHKA</label><span class="accent">${frappe.utils.escape_html(d.serie_tfhka)}</span></div>
            <div class="hka-preview__field"><label>Rango Autorizado</label><span style="font-size:10px;">${frappe.utils.escape_html(d.range_from)} al ${frappe.utils.escape_html(d.range_to)}</span></div>
          </div>
        </div>

        <!-- DATOS TÉCNICOS DEL SERVICIO -->
        <div class="hka-preview__section">
          <p class="hka-preview__section-title">Datos del Servicio</p>
          <div class="hka-preview__grid hka-preview__grid--4">
            <div class="hka-preview__field"><label>ID Servicio</label><span>${frappe.utils.escape_html(d.id_servicio)}</span></div>
            <div class="hka-preview__field"><label>Zona</label><span>${frappe.utils.escape_html(d.zona || "—")}</span></div>
            <div class="hka-preview__field"><label>Nodo</label><span>${frappe.utils.escape_html(d.nodo || "—")}</span></div>
            <div class="hka-preview__field"><label>Período</label><span class="accent">${frappe.utils.escape_html(d.periodo)}</span></div>
          </div>
        </div>

        <!-- ITEMS -->
        <div class="hka-preview__section">
          <p class="hka-preview__section-title">Descripción del Servicio / Productos</p>
          <table class="hka-preview__items-table">
            <thead>
              <tr>
                <th>Descripción</th>
                <th class="right">Cant.</th>
                <th class="right">Precio Unit.</th>
                <th class="right">IVA</th>
                <th class="right">Total Item</th>
              </tr>
            </thead>
            <tbody>${items_html}</tbody>
          </table>
        </div>

        <!-- TOTALES DUALES + BCV -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div class="hka-preview__section">
            <p class="hka-preview__section-title" style="margin-bottom:6px;">Totales</p>
            <div class="hka-preview__totals">
              <div>
                <p class="hka-preview__totals-col-title usd">USD</p>
                <div class="hka-preview__total-row"><span>Subtotal:</span><span>$ ${frappe.utils.escape_html(d.subtotal_usd)}</span></div>
                <div class="hka-preview__total-row bold"><span>IVA:</span><span>$ ${frappe.utils.escape_html(d.iva_usd)}</span></div>
              </div>
              <div>
                <p class="hka-preview__totals-col-title bs">Bs.</p>
                <div class="hka-preview__total-row"><span>Subtotal:</span><span>${frappe.utils.escape_html(d.subtotal_bs)}</span></div>
                <div class="hka-preview__total-row bold"><span>IVA:</span><span>${frappe.utils.escape_html(d.iva_bs)}</span></div>
              </div>
            </div>
          </div>

          <div class="hka-preview__bcv">
            <div class="hka-preview__bcv-row">
              <span class="hka-preview__bcv-label">Tasa BCV (${frappe.utils.escape_html(d.tasa_fecha)})</span>
              <span class="hka-preview__bcv-value">Bs. ${frappe.utils.escape_html(d.tasa_bcv)}</span>
            </div>
            <p class="hka-preview__bcv-note">
              Cálculos según Art. 25 Ley IVA. Sujeto a IGTF (+3%) si paga en divisas.
            </p>
          </div>
        </div>

        <!-- FOOTER INFORMATIVO -->
        <div class="hka-preview__footer-info">
          <span>Imprenta: THE FACTORY HKA VENEZUELA (J-402385358) • Providencia SNAT/2024/000102</span>
          <span>Rango: ${frappe.utils.escape_html(d.range_from)} — ${frappe.utils.escape_html(d.range_to)}</span>
        </div>

      </div><!-- /body -->
    </div><!-- /hka-preview -->
  `;

  const dialog = new frappe.ui.Dialog({
    title: __("Vista Previa — Facturación Digital HKA"),
    size: "large",
    fields: [
      { fieldtype: "HTML", fieldname: "preview_html", options: preview_html },
    ],
    primary_action_label: __("Confirmar Emisión"),
    primary_action: function () {
      dialog.hide();
      frappe.call({
        method:
          "l10n_ve.digital_invoice.tfhka_integration.send_invoice_manually",
        args: { invoice_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Enviando a TFHKA..."),
        callback: function (r) {
          if (!r.exc) {
            if (r.message === "Sent") {
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
    secondary_action_label: __("Cancelar"),
    secondary_action: function () {
      dialog.hide();
    },
  });

  dialog.show();

  // Ajustar ancho del modal para que el preview se vea completo
  dialog.$wrapper.find(".modal-dialog").css("max-width", "760px");
}

/**
 * Agrega un botón "Consultar en TFHKA" cuando la factura ya fue enviada
 * a la imprenta digital y el campo remarks contiene la urlConsulta.
 * @param {object} frm
 */
function setup_hka_consulta_button(frm) {
  if (!frm.doc.remarks || !frm.doc.remarks.includes('"urlConsulta"')) {
    return;
  }

  try {
    const data = JSON.parse(frm.doc.remarks);
    const url = (data && data.resultado && data.resultado.urlConsulta) || "";
    if (!url) return;

    frm.add_custom_button(
      __("Consultar en TFHKA"),
      function () {
        window.open(url, "_blank", "noopener,noreferrer");
      },
      __("Factura Digital"),
    );
  } catch (e) {
    // remarks no es JSON válido, ignorar silenciosamente
  }
}

/**
 * Obtiene y aplica la tasa de cambio venezolana correcta para el cliente.
 *
 * Regla fiscal: Jurídico → fecha exacta del posting_date.
 *               Natural  → primer día del mes del posting_date.
 *
 * Sincronización: se usa frappe.after_ajax() para garantizar que la
 * aplicación de la tasa VE ocurre DESPUÉS de que ERPNext complete su
 * propia cadena async (get_due_date → currency → get_exchange_rate).
 * El handler de `plc_conversion_rate` actúa como guardia de segundo
 * nivel ante cualquier reset posterior de ERPNext.
 *
 * Los valores se asignan directamente en frm.doc para evitar disparar
 * `apply_price_list` (que sobrescribiría la tasa con la fecha exacta).
 * Los totales en BS se recalculan vía `_calculate_taxes_and_totals`.
 *
 * @param {object} frm - Instancia del formulario Frappe.
 */
function apply_ve_exchange_rate_from_date(frm) {
  if (!frappe.boot.tfhka_enabled) return;

  // Limpia el flag previo para evitar que un cambio Natural→Jurídico
  // deje un target obsoleto activo en el handler de plc_conversion_rate.
  frm._l10n_ve_conv_rate = null;

  if (!frm.doc.customer || !frm.doc.posting_date || frm.doc.docstatus !== 0)
    return;

  const company_currency = erpnext.get_currency(frm.doc.company);
  if (!frm.doc.currency || frm.doc.currency === company_currency) return;

  // Capturamos los valores actuales para validar que no cambiaron
  // entre el disparo del evento y la resolución del after_ajax.
  const captured_customer = frm.doc.customer;
  const captured_date = frm.doc.posting_date;
  const captured_currency = frm.doc.currency;

  // frappe.after_ajax() ejecuta el callback una vez que todas las
  // llamadas ajax en vuelo del framework hayan completado, eliminando
  // la necesidad de un setTimeout arbitrario.
  frappe.after_ajax(function () {
    // Verificar que el formulario no cambió mientras esperábamos
    if (
      frm.doc.customer !== captured_customer ||
      frm.doc.posting_date !== captured_date ||
      frm.doc.currency !== captured_currency ||
      frm.doc.docstatus !== 0
    )
      return;

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

        // Guarda el target para que el handler de plc_conversion_rate
        // pueda interceptar cualquier reset posterior de ERPNext.
        frm._l10n_ve_conv_rate = rate;

        // Asignación directa: evita disparar apply_price_list (que
        // devuelve plc_conversion_rate con la fecha exacta y resetea
        // conversion_rate via el evento plc_conversion_rate()).
        frm.doc.conversion_rate = rate;
        frm.doc.plc_conversion_rate = rate;
        frm.refresh_field("conversion_rate");
        frm.refresh_field("plc_conversion_rate");

        // Recalcula los campos base_* (base_grand_total, base_taxes, etc.)
        // usando la función pura de JS del controlador (sin llamadas al backend).
        if (
          frm.cscript &&
          typeof frm.cscript._calculate_taxes_and_totals === "function"
        ) {
          frm.cscript._calculate_taxes_and_totals();
        }

        frm.dirty();
      },
    });
  });
}

/**
 * Oculta el botón nativo de ERPNext "Devolución / Nota de Crédito"
 * y lo reemplaza con "Nota de Crédito" que abre directamente el DocType
 * VE Sales Credit Note pre-llenado con los datos de la factura actual.
 * @param {object} frm
 */
function setup_credit_note_button(frm) {
  // El controller de ERPNext (extend_cscript) agrega "Return / Credit Note"
  // DESPUÉS de nuestro refresh. Usamos un timeout para removerlo siempre.
  setTimeout(() => {
    frm.page.remove_inner_button(__("Return / Credit Note"), __("Create"));
  }, 500);
  setTimeout(() => {
    frm.page.remove_inner_button(__("Return / Credit Note"), __("Create"));
  }, 1500);

  if (
    frm.doc.docstatus !== 1 ||
    frm.doc.is_return ||
    frm.doc.status === "Credit Note Issued" ||
    frm.doc.status === "Debit Note Issued"
  )
    return;

  frm.add_custom_button(
    __("Nota de Crédito"),
    function () {
      frappe.route_options = {
        return_against: frm.doc.name,
        company: frm.doc.company,
        customer: frm.doc.customer,
      };
      frappe.new_doc("VE Sales Credit Note");
    },
    __("Create"),
  );
}

/**
 * Botón "Nota de Débito" en el grupo "Create" de la Factura de Venta.
 * Redirige al formulario de VE Sales Debit Note pre-llenado con los datos
 * de la factura actual. Solo visible cuando la factura está aprobada y no
 * es una NC ni una ND.
 * @param {object} frm
 */
function setup_debit_note_button(frm) {
  if (
    frm.doc.docstatus !== 1 ||
    frm.doc.is_return ||
    frm.doc.is_debit_note ||
    frm.doc.status === "Debit Note Issued" ||
    frm.doc.status === "Credit Note Issued"
  )
    return;

  frm.add_custom_button(
    __("Nota de Débito"),
    function () {
      frappe.route_options = {
        return_against: frm.doc.name,
        company: frm.doc.company,
        customer: frm.doc.customer,
      };
      frappe.new_doc("VE Sales Debit Note");
    },
    __("Create"),
  );
}

/**
 * Botón "Anular en HKA" para facturas emitidas ante la imprenta digital.
 * Solo visible cuando docstatus === 1 y la factura tiene bill_no.
 * Abre un diálogo para capturar motivo, fecha y hora de anulación,
 * luego llama al endpoint backend que anula en HKA y cancela en Frappe.
 * @param {object} frm
 */
function setup_hka_void_button(frm) {
  if (frm.doc.docstatus !== 1 || !frm.doc.bill_no) return;

  frm.add_custom_button(
    __("Anular Factura de Venta"),
    function () {
      const today = frappe.datetime.get_today();
      const now = frappe.datetime.now_time();

      const dialog = new frappe.ui.Dialog({
        title: __("Anular Factura en HKA"),
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

          // Convertir YYYY-MM-DD → DD/MM/YYYY (formato requerido por TFHKA)
          const date_parts = values.void_date.split("-");
          const formatted_date = `${date_parts[2]}/${date_parts[1]}/${date_parts[0]}`;

          frappe.call({
            method: "l10n_ve.overrides.sales_invoice.void_sales_invoice",
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
                  message: __(
                    "Factura anulada correctamente en HKA y en el sistema.",
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

/**
 * Muestra banners informativos cuando una factura fue anulada ante HKA.
 * - Banner rojo con el motivo de anulación.
 * - Oculta el botón "Amend" para evitar enmendar documentos anulados fiscalmente.
 * @param {object} frm
 */
function setup_hka_void_banners(frm) {
  if (frm.doc.docstatus !== 2 || !frm.doc.bill_no || !frm.doc.avoid_reason) {
    return;
  }

  frm.set_intro(
    __(
      "🚫 Esta factura fue <b>anulada ante HKA</b> (N° {0}). " +
        "No puede ser corregida ni enmendada. " +
        "Cree una nueva factura si es necesario.",
      [frm.doc.bill_no],
    ),
    "red",
  );

  frm.page.btn_primary.hide();
}

/**
 * Botón "Ver Documento Anulado en HKA" para facturas canceladas
 * que fueron anuladas en la imprenta digital.
 * Abre la URL de consulta del documento en el portal TFHKA.
 * @param {object} frm
 */
function setup_hka_voided_consulta_button(frm) {
  if (frm.doc.docstatus !== 2 || !frm.doc.bill_no || !frm.doc.remarks) {
    return;
  }

  try {
    const hka_data = JSON.parse(frm.doc.remarks);
    const url = hka_data.resultado && hka_data.resultado.urlConsulta;
    if (!url) return;

    frm.add_custom_button(
      __("Ver Documento Anulado en HKA"),
      function () {
        window.open(url, "_blank", "noopener,noreferrer");
      },
      __("Factura Digital"),
    );
  } catch (_) {
    // remarks no es JSON válido, ignorar silenciosamente
  }
}

/**
 * Botón "Generar Factura de Reemplazo" para facturas anuladas ante HKA.
 * Solo visible cuando docstatus === 2 e is_void === 1.
 * Usa get_mapped_doc para crear un borrador con los mismos datos
 * de la factura original pero con fecha, tasa y campos fiscales limpios.
 * @param {object} frm
 */
function setup_replacement_invoice_button(frm) {
  if (frm.doc.docstatus !== 2 || !frm.doc.is_void) return;

  frm.add_custom_button(__("Generar Factura de Reemplazo"), function () {
    frappe.model.open_mapped_doc({
      method: "l10n_ve.overrides.sales_invoice.make_replacement_invoice",
      frm: frm,
    });
  });
}
