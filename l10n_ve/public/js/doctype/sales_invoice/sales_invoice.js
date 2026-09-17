// Agregar funcion general para ejecutgar funciones de botones

function withholding_date_description() {
  return __(
    "Esta fecha determina el período fiscal en el que la retención viajará al Libro de Ventas.",
  );
}

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
    frm.set_df_property(
      "withholding_date",
      "description",
      withholding_date_description(),
    );
    frm.set_df_property("voucher_image", "read_only", true);
    frm.set_df_property("islr_receipt_number", "read_only", true);
    frm.set_df_property("islr_date", "read_only", true);
    frm.set_df_property("voucher_image_islr", "read_only", true);
    frm.set_df_property("municipal_receipt_number", "read_only", true);
    frm.set_df_property("municipal_date", "read_only", true);
    frm.set_df_property("voucher_image_municipal", "read_only", true);

    // Mover esto a una funcion
    realtime_numeric_validation(frm, "bill_no");
    realtime_alphanumeric_with_hyphen_validation(frm, "bill_control");
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
    calculate_base_total_with_vat(frm);

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

    // TODO: Eliminar esto (Habilitado temporalmente para cargar comprobantes de retención a facturas generadas sin ellos.)
    has_vat_withholding = true;
    has_islr_withholding = true;
    ///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    setup_voucher_buttons(frm);
    setup_remove_withholding_buttons(frm);

    setup_exchange_difference_button(frm);
    setup_government_withholding_button(frm);
    setup_hka_consulta_button(frm);
    render_fiscal_invoice_preview(frm);
    setup_credit_note_button(frm);
    setup_debit_note_button(frm);

    if (frappe.boot.tfhka_enabled) {
      setup_digital_invoice_button(frm);
      setup_force_send_hka_button(frm);
    }

    set_ve_form_indicator(frm, { doc_type: "sales_invoice" });

    frm.get_field('notes')?.$wrapper?.find('textarea').css({ height: '35px', 'min-height': '35px' });
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

// set_ve_form_indicator() — definida en sales_billing_indicators.js (app_include_js)
// Invocada en refresh con: set_ve_form_indicator(frm, { doc_type: "sales_invoice" })

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

function apply_custom_totals_labels(frm) {
  if (!frm || !frm.fields_dict || !frm.wrapper) return;

  // 1. Ocultar los campos innecesarios (incluyendo en palabras USD)
  const hide_fields = [
    "totals",
    "base_total",
    "total",
    "base_total_with_vat",
    "in_words",
    "base_rounding_adjustment",
    "base_rounded_total",
    "rounding_adjustment",
    "rounded_total",
    "total_advance",
  ];

  for (const field of hide_fields) {
    frm.set_df_property(field, "hidden", true);
    let f = frm.get_field(field);
    if (f && f.$wrapper) {
      f.$wrapper.hide();
    }
  }

  // 2. Renombrar las etiquetas fijas exactamente como las quiere el usuario
  frm.set_df_property("section_break_43", "hidden", false);
  frm.set_df_property("section_break_43", "label", __("Totales"));

  const labels_map = {
    "base_net_total": "Base Imponible",
    "base_total_taxes_and_charges": "IVA",
    "base_grand_total": "Base Imponible + IVA",
    "base_in_words": "En palabras",
    "net_total": "Base Imponible",
    "total_taxes_and_charges": "IVA",
    "grand_total": "Base Imponible + IVA",
    "outstanding_amount": "Monto Pendiente",
  };

  for (const [fieldname, label_text] of Object.entries(labels_map)) {
    frm.set_df_property(fieldname, "label", label_text);
  }

  // 3. Forzar visibilidad en docfield
  for (const f of [
    "section_break_43",
    "base_net_total",
    "base_total_taxes_and_charges",
    "base_grand_total",
    "base_in_words",
    "net_total",
    "total_taxes_and_charges",
    "grand_total",
    "outstanding_amount",
  ]) {
    frm.set_df_property(f, "hidden", false);
    let field_obj = frm.get_field(f);
    if (field_obj && field_obj.$wrapper) {
      field_obj.$wrapper.show();
    }
  }

  // Relocar físicamente el contenedor de outstanding_amount dentro de section_break_43 (debajo de base_grand_total)
  // ya que la sección genérica 'totals' de ERPNext está oculta para usar la vista de dos columnas.
  const out_field = frm.get_field("outstanding_amount");
  const target_field = frm.get_field("base_grand_total");
  if (out_field && out_field.$wrapper && target_field && target_field.$wrapper) {
    out_field.$wrapper.show();
    out_field.$wrapper.insertAfter(target_field.$wrapper);
  }

  // 4. Garantizar que base_in_words tenga el valor formateado de 'En palabras' en Bolívares
  if (!frm.doc.base_in_words && frm.doc.in_words) {
    frm.doc.base_in_words = frm.doc.in_words;
    if (frm.fields_dict.base_in_words) {
      frm.refresh_field("base_in_words");
    }
  }

  // 5. Hacer los campos del lado de Bolívares (VEF) un poco más grandes
  const vef_fields = ["base_net_total", "base_total_taxes_and_charges", "base_grand_total", "outstanding_amount"];
  for (const fn of vef_fields) {
    let f = frm.get_field(fn);
    if (f && f.$wrapper) {
      f.$wrapper.find("input, .control-value").css({
        "font-size": "16px",
        "font-weight": "700",
        "height": "42px",
        "line-height": "42px"
      });
      f.$wrapper.find("label.control-label").css({
        "font-size": "13px",
        "font-weight": "600"
      });
    }
  }

  // 6. Actualizar importes de IVA
  if (typeof update_ve_vat_fields === "function") {
    update_ve_vat_fields(frm);
  }
}

function set_sales_invoice_fields(frm) {
  if (!frm || !frm.fields_dict) return;

  // Interceptar set_currency_labels para que no revierta nuestras etiquetas
  if (!frm._ve_currency_labels_patched) {
    frm._ve_currency_labels_patched = true;
    const _orig_set_currency_labels = frm.set_currency_labels;
    frm.set_currency_labels = function (fields, currency) {
      if (_orig_set_currency_labels) {
        _orig_set_currency_labels.call(this, fields, currency);
      }
      apply_custom_totals_labels(frm);
    };
  }

  apply_custom_totals_labels(frm);
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
 * Solo el Gerente de Contabilidad (Accounts Manager) puede anular; y si el
 * documento tiene sucursal, además debe tener acceso a esa VE Branch
 * (User Permission). Espejo de la validación server-side de void_document
 * (ocultar el botón es cosmético: la garantía real está en el servidor).
 * @param {object} frm
 * @returns {boolean}
 */
function user_can_void(frm) {
  if (frappe.session.user === "Administrator") return true;
  if (!frappe.user.has_role("Accounts Manager")) return false;

  const branch = frm.doc.branch;
  if (!branch) return true;

  const user_perms = frappe.defaults.get_user_permissions() || {};
  const branch_perms = user_perms["VE Branch"] || [];
  if (!branch_perms.length) return true; // sin restricción de sucursal: acceso global
  return branch_perms.some((p) => (p.doc || p) === branch);
}

/**
 * @param {object} frm
 */
function setup_void_button(frm) {
  if (frm.doc.docstatus === 2 && !frm.doc.is_void && user_can_void(frm)) {
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
    flt(frm.doc.outstanding_amount) !== 0
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
    frm.doc.docstatus === 2 ||
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

  if (frm.doc.docstatus === 0) {
    frm.page.set_inner_btn_group_as_primary(__("Factura Digital"));
  }
}

/**
 * Botón para forzar el envío a HKA saltando la validación de tasa BCV.
 * Solo visible para Administrator en facturas aprobadas que no hayan sido
 * enviadas exitosamente a HKA.
 * @param {object} frm
 */
function setup_force_send_hka_button(frm) {
  const is_authorized_user =
    frappe.session.user === "Administrator" ||
    frappe.user.has_role("System Manager") ||
    frappe.user.has_role("Accounts Manager");

  if (
    !is_authorized_user ||
    frm.doc.docstatus !== 1 ||
    (frm.doc.remarks && frm.doc.remarks.includes('"numeroControl"'))
  ) {
    return;
  }

  frm.add_custom_button(
    __("⚡ Forzar Envío HKA"),
    function () {
      frappe.confirm(
        __(
          "<b>⚠️ Atención:</b> Esta acción enviará la factura a HKA " +
          "<b>sin validar la tasa de cambio BCV</b>.<br><br>" +
          "Solo debe usarse cuando la tasa BCV del documento difiere " +
          "de la registrada por motivos operativos legítimos.<br><br>" +
          "¿Desea continuar?",
        ),
        function () {
          frappe.call({
            method:
              "l10n_ve.digital_invoice.tfhka_integration.send_invoice_manually",
            args: { invoice_name: frm.doc.name, force: 1 },
            freeze: true,
            freeze_message: __("Enviando a HKA (forzado)..."),
            callback: function (r) {
              if (!r.exc) {
                frappe.show_alert({
                  message: __("Factura enviada exitosamente a HKA"),
                  indicator: "green",
                });
                frm.reload_doc();
              }
            },
          });
        },
      );
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
  const has_item_discount = Boolean(d.has_item_discount);
  const has_discount = Boolean(d.has_discount);

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
      ${has_item_discount ? `<td class="right" style="color:#e53e3e;">${item.has_discount ? '- $ ' + frappe.utils.escape_html(item.discount_usd) : '—'}</td>` : ''}
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
            <div class="hka-preview__field"><label>Nota</label><span class="accent">${frappe.utils.escape_html(d.nota || "—")}</span></div>
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
                ${has_item_discount ? '<th class="right">Desc.</th>' : ''}
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
                ${has_discount ? `<div class="hka-preview__total-row"><span>Subtotal Bruto:</span><span>$ ${frappe.utils.escape_html(d.subtotal_gross_usd)}</span></div>` : ''}
                ${has_discount ? `<div class="hka-preview__total-row" style="color:#e53e3e;"><span>Descuento:</span><span>- $ ${frappe.utils.escape_html(d.discount_usd)}</span></div>` : ''}
                <div class="hka-preview__total-row"><span>Subtotal${has_discount ? ' Neto' : ''}:</span><span>$ ${frappe.utils.escape_html(d.subtotal_usd)}</span></div>
                <div class="hka-preview__total-row bold"><span>IVA:</span><span>$ ${frappe.utils.escape_html(d.iva_usd)}</span></div>
              </div>
              <div>
                <p class="hka-preview__totals-col-title bs">Bs.</p>
                ${has_discount ? `<div class="hka-preview__total-row"><span>Subtotal Bruto:</span><span>${frappe.utils.escape_html(d.subtotal_gross_bs)}</span></div>` : ''}
                ${has_discount ? `<div class="hka-preview__total-row" style="color:#e53e3e;"><span>Descuento:</span><span>- ${frappe.utils.escape_html(d.discount_bs)}</span></div>` : ''}
                <div class="hka-preview__total-row"><span>Subtotal${has_discount ? ' Neto' : ''}:</span><span>${frappe.utils.escape_html(d.subtotal_bs)}</span></div>
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

// Anulación directa de facturas ante HKA: DESHABILITADA POR LA IMPRENTA el 01/09/2026.
//
// Aviso de The Factory HKA del 27-jul-2026 ("🚨Aviso: Anulaciones de Facturas"), en
// cumplimiento de la Providencia Administrativa SNAT/2024/000121: "la anulación directa de
// facturas quedará deshabilitada a partir del 01/09/2026. Desde esa fecha, y para preservar
// la inalterabilidad fiscal, toda modificación o anulación se gestionará de forma exclusiva
// mediante la emisión de notas de crédito o de débito."
//
// Se oculta el botón en vez de dejar que falle: sin esto el usuario recibe el error crudo
// que devuelva HKA, sin decirle qué hacer en su lugar. La vía correcta es la NOTA DE
// CRÉDITO, que ya está soportada de punta a punta.
//
// Se conserva la función entera detrás del flag para que reactivarla sea una línea, por si
// la imprenta revierte o habilita excepciones. OJO: esto oculta el botón, no cierra la
// puerta — `l10n_ve.overrides.sales_invoice.void_sales_invoice` sigue publicado con
// @frappe.whitelist y es alcanzable por API.
const HKA_DIRECT_VOID_ENABLED = false;

/**
 * Botón "Anular en HKA" para facturas emitidas ante la imprenta digital.
 * Solo visible cuando docstatus === 1 y la factura tiene bill_no.
 * Abre un diálogo para capturar motivo, fecha y hora de anulación,
 * luego llama al endpoint backend que anula en HKA y cancela en Frappe.
 * @param {object} frm
 */
function setup_hka_void_button(frm) {
  if (!HKA_DIRECT_VOID_ENABLED) return;
  if (frm.doc.docstatus !== 1 || !frm.doc.bill_no) return;
  // Misma regla de visibilidad que "Anular Documento": solo Accounts Manager
  // con acceso a la sucursal del documento (ver user_can_void).
  if (!user_can_void(frm)) return;

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

function open_withholding_dialog(frm, invoice, customer, type, default_account, suggested_rate, suggested_amount, company) {
  // Se refleja el criterio del backend (handle_voucher_metadata): un comprobante
  // "existe" si ya hay número o imagen. Los campos de fecha reales son
  // withholding_date (IVA) e islr_date (ISLR); no existen vat_withholding_date
  // ni islr_withholding_date, así que no se consultan aquí.
  const has_existing = type === "VAT"
    ? !!(frm.doc.vat_withholding_voucher_number || frm.doc.voucher_image)
    : !!(frm.doc.islr_receipt_number || frm.doc.voucher_image_islr);

  const is_required = has_existing ? 0 : 1;

  const fields = [
    {
      label: __("Factura"),
      fieldname: "invoice",
      fieldtype: "Link",
      options: "Sales Invoice",
      default: invoice,
      read_only: 1,
    },
    {
      label: __("Cliente"),
      fieldname: "customer",
      fieldtype: "Link",
      options: "Customer",
      default: customer,
      read_only: 1,
    },
    {
      label: __("Cuenta de Retención"),
      fieldname: "tax_account",
      fieldtype: "Link",
      options: "Account",
      reqd: 1,
      default: default_account,
      read_only: 1,
      get_query: () => ({
        filters: {
          company: frm.doc.company,
          is_group: 0,
        },
      }),
    },
    {
      label: __("Monto de Retención"),
      fieldname: "amount",
      fieldtype: "Currency",
      reqd: 1,
      default: suggested_amount || 0,
      read_only: 1,
      description: __("Monto de la retención aplicada por el cliente."),
    },
    {
      label: type === "VAT" ? __("Número de Comprobante IVA") : __("Número de Comprobante/Control ISLR"),
      fieldname: "voucher_number",
      fieldtype: "Data",
      reqd: type === "VAT" ? is_required : 0,
      description: type === "VAT" ? __("Debe tener exactamente 14 caracteres numéricos.") : "",
    },
    {
      label: __("Fecha de Registro"),
      fieldname: "withholding_date",
      fieldtype: "Date",
      description: withholding_date_description(),
      default: frappe.datetime.get_today(),
      reqd: is_required,
    },
    {
      label: __("Fecha de Comprobante"),
      fieldname: "registration_date",
      fieldtype: "Date",
      default: frappe.datetime.get_today(),
      reqd: is_required,
    },
    {
      label: __("Archivo de Comprobante (PDF/Imagen)"),
      fieldname: "file_url",
      fieldtype: "Attach",
      reqd: is_required,
    },
  ];

  if (type === "ISLR") {
    fields.push({
      label: __("Alícuota ISLR (%)"),
      fieldname: "rate",
      fieldtype: "Percent",
      reqd: 1,
      read_only: 1,
      default: suggested_rate || 0,
    });
  }

  const dialog = new frappe.ui.Dialog({
    title: type === "VAT" ? __("Corregir Retención de IVA") : __("Corregir Retención de ISLR"),
    fields: fields,
    primary_action_label: __("Aplicar y Guardar"),
    primary_action(values) {
      const has_any = !!(values.voucher_number || values.withholding_date || values.file_url);
      const has_all = !!(values.voucher_number && values.withholding_date && values.file_url);

      if (has_any && !has_all) {
        frappe.msgprint({
          title: __("Campos Incompletos"),
          indicator: "orange",
          message: type === "VAT"
            ? __("Debe completar todos los campos del formulario para el comprobante de IVA (Número, Fecha y Archivo).")
            : __("Debe completar todos los campos del formulario para el comprobante de ISLR (Número, Fecha y Archivo).")
        });
        return;
      }

      if (type === "VAT" && values.voucher_number) {
        const regex = /^\d{14}$/;
        if (!regex.test(values.voucher_number)) {
          frappe.msgprint({
            title: __("Error de Formato"),
            indicator: "red",
            message: __("El Número de Comprobante de IVA debe tener exactamente 14 caracteres numéricos."),
          });
          return;
        }
      }

      if (!validate_voucher_file_frontend(values.file_url, ["pdf", "jpg", "jpeg", "png"])) {
        return;
      }

      // No se oculta el diálogo aquí: si el servidor lanza un error, el operador
      // conserva lo que tecleó. Se oculta solo tras aplicar la retención con éxito.
      const ejecutar_peticion = (overwrite_value = 0, only_line_value = 0) => {
        frappe.call({
          method: "l10n_ve.overrides.sales_invoice.fix_missing_withholding",
          args: {
            invoice_name: invoice,
            withholding_type: type,
            tax_account: values.tax_account,
            voucher_number: values.voucher_number,
            withholding_date: values.withholding_date,
            file_url: values.file_url,
            rate: values.rate !== undefined ? values.rate : suggested_rate,
            overwrite: overwrite_value,
            only_line: only_line_value,
            company: company,
            registration_date: values.registration_date,
          },
          freeze: true,
          freeze_message: __("Aplicando retención y generando asiento..."),
          callback(r) {
            if (r.message && r.message.status === "success") {
              dialog.hide();
              frappe.show_alert({
                message: __(r.message.msg),
                indicator: "green",
              });
              frm.reload_doc();
            } else if (r.message && r.message.status === "ask_overwrite") {
              frappe.confirm(
                r.message.message,
                () => {
                  // SÍ: Reemplaza datos de comprobante + Crea línea de impuestos
                  ejecutar_peticion(1, 0);
                },
                () => {
                  // NO: Mantiene datos viejos de comprobante + Crea línea de impuestos
                  ejecutar_peticion(0, 1);
                },
                () => {
                  frappe.show_alert({
                    message: __("Se creó el impuesto y corrigió el asiento pero no se modificó la información del comprobante."),
                    indicator: "orange"
                  });
                  frm.reload_doc();
                }
              );
            }
          },
        });
      };

      ejecutar_peticion(0, 0);
    },
  });

  dialog.show();

  if (dialog.fields_dict.voucher_number) {
    const $input = dialog.fields_dict.voucher_number.$input;
    $input.attr("maxlength", 14);
    $input.on("input", function () {
      this.value = this.value.replace(/\D/g, "");
    });
  }
}

function get_vat_category_rate(category, company, callback) {
  if (!category) {
    frappe.msgprint({
      title: __("Categoría Faltante"),
      message: __("El cliente no tiene asignada una categoría de retención de impuestos."),
      indicator: "orange"
    });
    return;
  }

  frappe.db.get_doc("Tax Withholding Category", category).then(doc => {
    let rate = null;

    if (doc.accounts && doc.accounts.length > 0) {
      let account_row = doc.accounts.find(a => a.company === company);

      if (account_row && doc.rates && doc.rates.length > 0) {
        rate = flt(doc.rates[0].tax_withholding_rate);
      }
    }

    if (rate === null || rate === 0) {
      rate = flt(doc.default_rate) || flt(doc.rate) || null;
    }

    if (rate === null || rate === 0) {
      frappe.msgprint({
        title: __("Tasa no Configurada"),
        message: __("No se encontró ninguna tasa (Rate) válida o configurada para la categoría de retención {0}.", [category]),
        indicator: "red"
      });
      return;
    }

    callback(rate);
  }).catch((err) => {
    frappe.msgprint({
      title: __("Error de Servidor"),
      message: __("Ocurrió un error al intentar consultar la Categoría de Retención del cliente."),
      indicator: "red"
    });
  });
}

function validate_voucher_file_frontend(file_url, allowed_extensions) {
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

function setup_voucher_buttons(frm) {
  if (frm.doc.docstatus == 2 || frm.doc.__islocal || !frm.doc.customer) {
    return;
  }

  const has_vat_withholding = frm.doc.taxes
    ? frm.doc.taxes.some((t) => t.charge_type === "VAT Withholding")
    : false;
  const has_islr_withholding = frm.doc.taxes
    ? frm.doc.taxes.some((t) => t.charge_type === "ISLR")
    : false;
  const has_municipal_withholding = frm.doc.taxes
    ? frm.doc.taxes.some((t) => t.charge_type === "Municipal Withholding")
    : false;

  frappe.db.get_value(
    "Customer",
    frm.doc.customer,
    [
      "is_special_taxpayer",
      "tax_withholding_category",
      "tabulator_islr",
      "municipal_withholding_rate",
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
      const show_municipal =
        has_municipal_withholding ||
        (customer_data.is_special_taxpayer && flt(customer_data.municipal_withholding_rate) > 0);

      // Limpiar para evitar duplicados al refrescar el formulario
      frm.page.remove_inner_button(
        __("Retención de IVA"),
        __("Cargar Comprobante"),
      );
      frm.page.remove_inner_button(
        __("Retención de ISLR"),
        __("Cargar Comprobante"),
      );
      frm.page.remove_inner_button(
        __("Retención Municipal"),
        __("Cargar Comprobante"),
      );

      if (show_vat) {
        frm.add_custom_button(
          __("Retención de IVA"),
          () => {
            if (frm.doc.docstatus === 0 || has_vat_withholding) {
              open_upload_vat_modal(frm);
            } else {
              apply_vat_withholding(frm, customer_data);
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
              open_upload_islr_modal(frm);
            } else {
              apply_islr_withholding(frm, customer_data);
            }
          },
          __("Cargar Comprobante"),
        );
      }

      if (show_municipal) {
        frm.add_custom_button(
          __("Retención Municipal"),
          () => {
            open_upload_municipal_modal(frm);
          },
          __("Cargar Comprobante"),
        );
      }
    },
  );
}

function open_upload_municipal_modal(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Cargar Comprobante de Retención Municipal (ISAE)"),
    fields: [
      {
        label: __("Número de Comprobante Municipal"),
        fieldname: "municipal_receipt_number",
        fieldtype: "Data",
        reqd: 0,
        default: frm.doc.municipal_receipt_number,
      },
      {
        label: __("Fecha de registro"),
        fieldname: "municipal_date",
        fieldtype: "Date",
        default: frm.doc.municipal_date || frappe.datetime.get_today(),
        reqd: 1,
      },
      {
        label: __("Fecha de Comprobante Municipal"),
        fieldname: "registration_date",
        fieldtype: "Date",
        default: frm.doc.municipal_registration_date || frappe.datetime.get_today(),
        reqd: 1,
      },
      {
        label: __("Imagen/PDF del Comprobante Municipal"),
        fieldname: "voucher_image_municipal",
        fieldtype: "Attach",
        reqd: 1,
        default: frm.doc.voucher_image_municipal,
      },
    ],
    primary_action_label: __("Subir y Guardar"),
    primary_action: (values) => {
      if (!values.municipal_date || !values.voucher_image_municipal) {
        frappe.msgprint({
          title: __("Error de Validación"),
          indicator: "red",
          message: __(
            "Debe ingresar la Fecha y adjuntar el archivo del Comprobante Municipal.",
          ),
        });
        return;
      }
      if (
        !validate_voucher_file_frontend(values.voucher_image_municipal, [
          "pdf",
          "jpg",
          "jpeg",
          "png",
        ])
      ) {
        return;
      }

      if (frm.doc.docstatus === 0) {
        frm.set_value("municipal_receipt_number", values.municipal_receipt_number);
        frm.set_value("municipal_date", values.municipal_date);
        frm.set_value("voucher_image_municipal", values.voucher_image_municipal);
        frm.set_value("municipal_registration_date", values.registration_date);

        frm.save().then(() => {
          frappe.show_alert({
            message: __(
              "Factura guardada con los datos del comprobante Municipal.",
            ),
            indicator: "green",
          });
          dialog.hide();
        });
      } else {
        frappe.call({
          method: "l10n_ve.overrides.sales_invoice.upload_municipal_voucher_data",
          args: {
            docname: frm.doc.name,
            municipal_receipt_number: values.municipal_receipt_number,
            municipal_date: values.municipal_date,
            file_url: values.voucher_image_municipal,
            registration_date: values.registration_date,
          },
          callback: function (r) {
            if (r.message && r.message.status === "success") {
              frappe.msgprint(
                __("Comprobante Municipal cargado exitosamente."),
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
      }
    },
  });
  dialog.show();
}

function open_upload_vat_modal(frm) {
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
        description: withholding_date_description(),
        default: frm.doc.withholding_date || frappe.datetime.get_today(),
        reqd: 1,
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
      if (
        !voucher_number ||
        !values.withholding_date ||
        !values.voucher_image
      ) {
        frappe.msgprint({
          title: __("Error de Validación"),
          indicator: "red",
          message: __(
            "Debe ingresar el Número, la Fecha y adjuntar el archivo del Comprobante.",
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
      if (
        !validate_voucher_file_frontend(values.voucher_image, [
          "pdf",
          "jpg",
          "jpeg",
          "png",
        ])
      ) {
        return;
      }

      if (frm.doc.docstatus === 0) {
        frm.set_value("vat_withholding_voucher_number", voucher_number);
        frm.set_value("withholding_date", values.withholding_date);
        frm.set_value("voucher_image", values.voucher_image);
        frm.set_value("vat_registration_date", values.registration_date);

        frm.save().then(() => {
          frappe.show_alert({
            message: __(
              "Factura guardada con los datos del comprobante de IVA.",
            ),
            indicator: "green",
          });
          dialog.hide();
        });
      } else {
        frappe.call({
          method: "l10n_ve.overrides.sales_invoice.upload_voucher_data",
          args: {
            docname: frm.doc.name,
            voucher_number: voucher_number,
            withholding_date: values.withholding_date,
            file_url: values.voucher_image,
            registration_date: values.registration_date,
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
      }
    },
  });
  dialog.show();
  if (dialog.fields_dict.vat_withholding_voucher_number) {
    const $input = dialog.fields_dict.vat_withholding_voucher_number.$input;
    $input.attr("maxlength", 14);
    $input.on("input", function () {
      this.value = this.value.replace(/\D/g, "");
    });
  }
}

function open_upload_islr_modal(frm) {
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
      if (
        !validate_voucher_file_frontend(values.voucher_image_islr, [
          "pdf",
          "jpg",
          "jpeg",
          "png",
        ])
      ) {
        return;
      }

      if (frm.doc.docstatus === 0) {
        frm.set_value("islr_receipt_number", values.islr_receipt_number);
        frm.set_value("islr_date", values.islr_date);
        frm.set_value("voucher_image_islr", values.voucher_image_islr);
        frm.set_value("islr_registration_date", values.registration_date);

        frm.save().then(() => {
          frappe.show_alert({
            message: __(
              "Factura guardada con los datos del comprobante de ISLR.",
            ),
            indicator: "green",
          });
          dialog.hide();
        });
      } else {
        frappe.call({
          method: "l10n_ve.overrides.sales_invoice.upload_islr_voucher_data",
          args: {
            docname: frm.doc.name,
            islr_receipt_number: values.islr_receipt_number,
            islr_date: values.islr_date,
            file_url: values.voucher_image_islr,
            registration_date: values.registration_date,
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
      }
    },
  });
  dialog.show();
}

function apply_vat_withholding(frm, customer_data) {
  let invoice = frm.doc.bill_no ? frm.doc.bill_no : frm.doc.name;
  let company = frm.doc.company;

  frappe.db.get_value(
    "Company",
    frm.doc.company,
    "sales_vat_withholding_account",
    (co) => {
      let vat_account = co ? co.sales_vat_withholding_account : null;

      const open_vat_modal = (account, rate) => {
        let vat_amount = frm.doc.taxes
          .filter((t) => t.charge_type === "VAT")
          .reduce((sum, t) => sum + flt(t.base_tax_amount), 0);

        let suggested_amount = flt(vat_amount * (rate / 100.0), 2);
        open_withholding_dialog(
          frm,
          invoice,
          frm.doc.customer,
          "VAT",
          account,
          rate,
          suggested_amount,
          company,
        );
      };

      if (vat_account) {
        get_vat_category_rate(
          customer_data.tax_withholding_category,
          frm.doc.company,
          (rate) => {
            open_vat_modal(vat_account, rate);
          },
        );
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
            get_vat_category_rate(
              customer_data.tax_withholding_category,
              frm.doc.company,
              (rate) => {
                open_vat_modal(fallback_account, rate);
              },
            );
          },
        );
      }
    },
  );
}

function apply_islr_withholding(frm, customer_data) {
  let invoice = frm.doc.bill_no ? frm.doc.bill_no : frm.doc.name;
  let company = frm.doc.company;

  frappe.db
    .get_doc("Tabulator ISLR", customer_data.tabulator_islr)
    .then((tab_doc) => {
      let islr_rate = 0;
      let subtrahend = 0;
      let percentage_base = 75;

      let target_row = null;
      let client_person_type = customer_data.type_of_person;

      if (tab_doc.aliquot && tab_doc.aliquot.length > 0) {
        if (client_person_type) {
          target_row = tab_doc.aliquot.find(
            (row) => row.types_of_person === client_person_type,
          );
        }
        if (!target_row) {
          frappe.msgprint({
            title: __("Configuración Incompleta"),
            indicator: "orange",
            message: __(
              'No se encontró un tramo en el Tabulador para "{0}". Se usará el primer tramo por defecto, verifique los montos sugeridos.',
              [client_person_type],
            ),
          });
          target_row = tab_doc.aliquot[0];
        }
      }

      if (target_row) {
        islr_rate = flt(target_row.aliquot);
        subtrahend = flt(target_row.subtracting);
        percentage_base = flt(target_row.percentage_base) || 100;
      }

      let base_net_total = flt(frm.doc.base_net_total);
      let calculated_base = flt(base_net_total * (percentage_base / 100));

      let suggested_islr_amount = flt(
        calculated_base * (islr_rate / 100) - subtrahend,
        2,
      );
      if (suggested_islr_amount < 0) suggested_islr_amount = 0;

      const open_islr_modal = (final_account) => {
        open_withholding_dialog(
          frm,
          invoice,
          frm.doc.customer,
          "ISLR",
          final_account,
          islr_rate,
          suggested_islr_amount,
          company,
        );
      };

      frappe.db.get_value(
        "Company",
        frm.doc.company,
        "sales_islr_account",
        (co) => {
          let company_account = co ? co.sales_islr_account : "";

          if (company_account) {
            open_islr_modal(company_account);
          } else if (customer_data.tax_withholding_category) {
            frappe.db.get_value(
              "Tax Withholding Account",
              {
                parent: customer_data.tax_withholding_category,
                company: frm.doc.company,
              },
              "account",
              (twa) => {
                let category_account = twa ? twa.account : "";
                open_islr_modal(category_account);
              },
            );
          } else {
            open_islr_modal("");
          }
        },
      );
    })
    .catch((err) => {
      frappe.msgprint(
        __(
          "Error leyendo el Tabulador de ISLR del cliente: {0}",
          [err.message],
        ),
      );
    });
}

/**
 * Botón "Retención Gubernamental" en Factura de Venta.
 *
 * Registra retenciones de entes gubernamentales (timbre fiscal, ISAE,
 * responsabilidad social) creando un Asiento Contable de cruce que baja el saldo
 * pendiente de la factura.
 *
 * El monto va SIEMPRE en la moneda de la empresa (Bs). El saldo pendiente se pide
 * al servidor en vez de convertirlo acá: `outstanding_amount` está en la moneda de
 * la cuenta por cobrar, y repetir esa conversión en el cliente es la forma de que
 * el modal muestre un número y el asiento postee otro.
 *
 * Se admiten varias retenciones sobre la misma factura y el comprobante es
 * opcional: cada asiento baja el pendiente, así que el tope del servidor acota la
 * suma.
 *
 * @param {object} frm
 */
function setup_government_withholding_button(frm) {
  frm.page.remove_inner_button(
    __("Retención Gubernamental"),
    __("Cargar Comprobante"),
  );

  if (frm.doc.docstatus !== 1) return;

  frm.add_custom_button(
    __("Retención Gubernamental"),
    function () {
      frappe.call({
        method:
          "l10n_ve.overrides.sales_invoice.get_government_withholding_context",
        args: { docname: frm.doc.name },
        freeze: true,
        freeze_message: __("Consultando saldo pendiente..."),
        callback: function (r) {
          if (r.exc || !r.message) return;
          open_government_withholding_dialog(frm, r.message);
        },
      });
    },
    __("Cargar Comprobante"),
  );
}

function open_government_withholding_dialog(frm, ctx) {
  const outstanding = flt(ctx.outstanding);
  const currency = ctx.currency;
  const has_balance = outstanding > 0.001;

  const fields = [
    {
      label: __("Moneda"),
      fieldname: "display_currency",
      fieldtype: "Data",
      hidden: 1,
      default: currency,
    },
    {
      label: __("Monto Pendiente"),
      fieldname: "outstanding_display",
      fieldtype: "Currency",
      options: "display_currency",
      default: outstanding,
      read_only: 1,
    },
  ];

  if (has_balance) {
    fields.push({
      label: __("Monto de Retención"),
      fieldname: "amount",
      fieldtype: "Currency",
      options: "display_currency",
      reqd: 1,
      default: outstanding,
      description: __("Ingrese el monto de la retención a descontar."),
    });
  }

  fields.push(
    {
      label: __("Número de Comprobante"),
      fieldname: "voucher_number",
      fieldtype: "Data",
      placeholder: __("Ej. 2026080001 (Opcional)"),
      default: frm.doc.municipal_receipt_number || "",
    },
    {
      label: __("Fecha de Comprobante"),
      fieldname: "voucher_date",
      fieldtype: "Date",
      default: frm.doc.municipal_date || frappe.datetime.get_today(),
    },
    {
      label: __("Imagen/PDF del Comprobante"),
      fieldname: "voucher_file",
      fieldtype: "Attach",
      default: frm.doc.voucher_image_municipal || "",
      description: __("Adjuntar archivo del comprobante (Opcional)"),
    },
    {
      label: __("Descripción / Concepto"),
      fieldname: "description",
      fieldtype: "Small Text",
      placeholder: __(
        "Ej. Retención Timbre Fiscal / Impuesto Municipal de la factura",
      ),
    },
  );

  const dialog = new frappe.ui.Dialog({
    title: has_balance
      ? __("Registrar Retención Gubernamental")
      : __("Cargar Comprobante de Retención"),
    fields: fields,
    primary_action_label: has_balance
      ? __("Confirmar y Contabilizar")
      : __("Guardar Comprobante"),
    primary_action: function (values) {
      const amount = has_balance ? flt(values.amount) : 0;

      if (has_balance && amount <= 0) {
        frappe.msgprint({
          title: __("Monto Inválido"),
          indicator: "red",
          message: __("El monto de la retención debe ser mayor a cero."),
        });
        return;
      }

      if (
        values.voucher_file &&
        !validate_voucher_file_frontend(values.voucher_file, [
          "pdf",
          "jpg",
          "jpeg",
          "png",
        ])
      ) {
        return;
      }

      if (has_balance && amount > outstanding + 0.001) {
        frappe.msgprint({
          title: __("Exceso de Monto"),
          indicator: "red",
          message: __(
            "El monto de la retención no puede ser mayor que el saldo pendiente de la factura ({0}).",
            [format_currency(outstanding, currency)],
          ),
        });
        return;
      }

      dialog.hide();

      if (has_balance && amount > 0) {
        frappe.call({
          method:
            "l10n_ve.overrides.sales_invoice.create_government_withholding_journal_entry",
          args: {
            docname: frm.doc.name,
            amount: amount,
            description: values.description,
            voucher_number: values.voucher_number,
            voucher_date: values.voucher_date,
            voucher_file: values.voucher_file,
          },
          freeze: true,
          freeze_message: __("Contabilizando la retención..."),
          callback: function (r) {
            if (r.exc || !r.message) return;
            frappe.msgprint({
              title: __("Retención Gubernamental registrada exitosamente."),
              indicator: "green",
              message: r.message.message,
            });
            frm.reload_doc();
          },
        });
      } else {
        frappe.call({
          method:
            "l10n_ve.overrides.sales_invoice.upload_municipal_voucher_data",
          args: {
            docname: frm.doc.name,
            municipal_receipt_number: values.voucher_number,
            municipal_date: values.voucher_date,
            file_url: values.voucher_file,
            registration_date: values.voucher_date,
          },
          freeze: true,
          freeze_message: __("Guardando comprobante..."),
          callback: function (r) {
            if (r.exc || !r.message) return;
            frappe.msgprint({
              title: __("Comprobante cargado exitosamente."),
              indicator: "green",
              message: __(
                "Factura actualizada con los datos del comprobante.",
              ),
            });
            frm.reload_doc();
          },
        });
      }
    },
  });

  dialog.show();
}

/**
 * Menú «Quitar Retención» en la factura aprobada, uno por tipo que tenga cargado.
 *
 * Existe por el caso que reportó administración el 16-sep-2026: clientes con el check de
 * contribuyente especial marcado por error a los que se les descontó el 75% del IVA sin ser
 * agentes de retención. Hasta ahora sólo había camino para AGREGAR una retención; quitarla
 * había que hacerlo a mano, asiento por asiento.
 *
 * Es el mismo botón que ya tiene la Factura de Compra, del otro lado del mostrador.
 *
 * @param {object} frm - Instancia del formulario
 */
function setup_remove_withholding_buttons(frm) {
  if (frm.doc.docstatus !== 1) {
    return;
  }

  const tipos = [
    { type: "VAT", charge_type: "VAT Withholding", label: __("Retención de IVA") },
    { type: "ISLR", charge_type: "ISLR", label: __("Retención de ISLR") },
  ];

  tipos.forEach((tipo) => {
    const tiene = (frm.doc.taxes || []).some(
      (fila) => fila.charge_type === tipo.charge_type && flt(fila.tax_amount)
    );
    if (tiene) {
      frm.add_custom_button(tipo.label, () => remove_sales_withholding(frm, tipo.type), __("Quitar Retención"));
    }
  });
}

/**
 * Quita una retención de la factura aprobada, tras confirmar.
 *
 * El monto vuelve a deberlo el cliente: se dice en el diálogo, porque es lo que el usuario
 * necesita saber antes de aceptar.
 *
 * @param {object} frm              - Instancia del formulario
 * @param {string} withholding_type - "VAT" o "ISLR"
 */
function remove_sales_withholding(frm, withholding_type) {
  const charge_type = withholding_type === "VAT" ? "VAT Withholding" : "ISLR";
  const etiqueta = withholding_type === "VAT" ? __("IVA") : __("ISLR");
  const filas = (frm.doc.taxes || []).filter((fila) => fila.charge_type === charge_type);
  const monto = filas.reduce((acumulado, fila) => acumulado + flt(fila.tax_amount), 0);
  const monto_base = filas.reduce((acumulado, fila) => acumulado + flt(fila.base_tax_amount), 0);

  frappe.confirm(
    __(
      "Se va a quitar la retención de {0} por {1} de la factura {2}. Se asienta el reverso y ese monto vuelve a deberlo el cliente. La otra retención no se toca. ¿Continuar?",
      [
        etiqueta,
        l10n_ve.money.in_both_currencies(frm, monto, monto_base),
        // El número fiscal, que es el que el usuario tiene en la mano.
        frm.doc.bill_no || frm.doc.name,
      ]
    ),
    () => {
      frappe.dom.freeze(__("Quitando la retención y asentando el reverso..."));
      frappe.call({
        method: "l10n_ve.overrides.sales_invoice.remove_retroactive_sales_withholding",
        args: {
          invoice_name: frm.doc.name,
          withholding_type: withholding_type,
          company: frm.doc.company,
        },
        callback(r) {
          frappe.dom.unfreeze();
          if (r.message && r.message.status === "success") {
            frappe.show_alert({ message: r.message.msg, indicator: "green" });
            frm.reload_doc();
          }
        },
        error() {
          frappe.dom.unfreeze();
        },
      });
    }
  );
}
