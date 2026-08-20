frappe.ui.form.on("Purchase Invoice", {
  onload: function (frm) {
    if (frm.is_new() && (frm.doc.is_return || frm.doc.is_debit_note)) {
      frm.set_value("bill_control", "");
    }

    realtime_alphanumeric_with_hyphen_validation(frm, "bill_control");
    realtime_numeric_validation(frm, "credit_note_no");
    realtime_numeric_validation(frm, "debit_note_no");

    toggle_purchase_type_fields(frm);

    const return_against_field = "return_against";
    if (frm.get_docfield(return_against_field).label !== "Factura Afectada") {
      frm.set_df_property(return_against_field, "label", "Factura Afectada");
    }
  },
  refresh: function (frm) {
    toggle_purchase_type_fields(frm);
    set_purchase_invoice_fields(frm);
    set_islr_buttons(frm);
    setup_credit_note_button(frm);
    setup_debit_note_button(frm);
    setup_withholding_voucher_buttons(frm);
    setup_purchase_exchange_difference_button(frm);
    setup_government_withholding_button(frm);
    setup_retroactive_withholding_buttons(frm);
  },

  is_debit_note: function (frm) {
    if (frm.doc.is_debit_note) {
      frm.set_value("is_return", 0);
      frm.set_value("bill_control", "");
    }
    toggle_purchase_type_fields(frm);
  },

  is_return: function (frm) {
    if (frm.doc.is_return) {
      frm.set_value("is_debit_note", 0);
      frm.set_value("bill_control", "");
    }
    toggle_purchase_type_fields(frm);
  },
});

/**
 * Alterna la visibilidad y obligatoriedad de los campos de la factura de compra
 * según si es una factura normal, una nota de débito o una devolución (nota de crédito).
 * Esta función asegura que la interfaz siempre muestre solo los campos relevantes
 * para el tipo de transacción seleccionado.
 *
 * @param {object} frm - La instancia del formulario
 * @returns {void} -
 */

function toggle_purchase_type_fields(frm) {
  const is_debit_note = frm.doc.is_debit_note;
  const is_return = frm.doc.is_return;

  frm.toggle_reqd("bill_no", !is_debit_note && !is_return);
  frm.toggle_reqd("credit_note_no", is_return);
  frm.toggle_reqd("debit_note_no", is_debit_note);

  if (is_return) {
    frm.toggle_display(
      ["credit_note_no", "affected_invoice_number", "return_against"],
      true,
    );
    frm.toggle_display(["debit_note_no", "bill_no"], false);

    frm.set_value("bill_no", "");
    frm.set_value("debit_note_no", "");
  } else if (is_debit_note) {
    frm.toggle_display(
      ["debit_note_no", "affected_invoice_number", "return_against"],
      true,
    );
    frm.toggle_display(["credit_note_no", "bill_no"], false);

    frm.set_value("bill_no", "");
    frm.set_value("credit_note_no", "");
  } else {
    frm.toggle_display("bill_no", true);
    frm.toggle_display(
      [
        "credit_note_no",
        "debit_note_no",
        "affected_invoice_number",
        "return_against",
      ],
      false,
    );

    frm.set_value("credit_note_no", "");
    frm.set_value("debit_note_no", "");
  }

  frm.set_df_property("total_igtf", "hidden", !Boolean(frm.doc.total_igtf));
  frm.set_df_property(
    "base_amount_igtf",
    "hidden",
    !Boolean(frm.doc.base_amount_igtf),
  );
}

function set_purchase_invoice_fields(frm) {
  for (const field of [
    "base_in_words",
    "base_total_taxes_and_charges",
    "totals",
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

// ------------------------------------------------------------------ //
// ISLR — Botones y diálogo para asignación manual de retención       //
// ------------------------------------------------------------------ //

/**
 * Agrega los botones de ISLR en el formulario de Purchase Invoice.
 * Solo se muestra en facturas en borrador, no nuevas, con proveedor asignado.
 *
 * @param {object} frm - La instancia del formulario
 */
function set_islr_buttons(frm) {
  if (frm.doc.docstatus !== 0 || frm.is_new() || !frm.doc.supplier) {
    return;
  }

  const has_islr = (frm.doc.taxes || []).some(
    (tax) => tax.charge_type === "ISLR",
  );

  // Siempre mostrar "Agregar ISLR"
  frm.add_custom_button(
    __("Agregar ISLR"),
    function () {
      show_islr_dialog(frm);
    },
    __("Retenciones"),
  );

  // Mostrar "Eliminar ISLR" solo si hay al menos una retención ISLR
  if (has_islr) {
    frm.add_custom_button(
      __("Eliminar ISLR"),
      function () {
        frappe.confirm(
          "¿Está seguro de eliminar todas las retenciones de ISLR?",
          () => {
            frappe.dom.freeze("Eliminando retenciones ISLR...");
            frm
              .call("remove_islr_concept")
              .then(() => {
                frappe.dom.unfreeze();
                frm.reload_doc();
              })
              .catch(() => {
                frappe.dom.unfreeze();
              });
          },
        );
      },
      __("Retenciones"),
    );
  }
}

async function show_islr_dialog(frm) {
  // 1. Consultar Proveedor y Compañía en paralelo sin anidar callbacks
  const [supplier_res, company_res] = await Promise.all([
    frappe.db.get_value("Supplier", frm.doc.supplier, "type_of_person"),
    frappe.db.get_value("Company", frm.doc.company, "purchase_islr_account")
  ]);

  const type_of_person = supplier_res?.message?.type_of_person || "";
  const islr_account = company_res?.message?.purchase_islr_account || null;
  const type_of_person_label = type_of_person ? __(type_of_person) : __("No configurado");

  // Códigos ISLR ya cargados en la factura (para excluir duplicados)
  const existing_codes = (frm.doc.taxes || [])
    .filter((tax) => tax.charge_type === "ISLR" && tax.code)
    .map((tax) => tax.code);

  // 2. Construir el diálogo con el flujo totalmente plano
  const dialog = new frappe.ui.Dialog({
    title: __("Agregar Retención de ISLR"),
    fields: [
      {
        fieldtype: "HTML",
        fieldname: "islr_info",
        options: `
          <div style="padding: 10px 12px; margin-bottom: 12px;
                      border: 1px solid var(--border-color);
                      border-radius: var(--border-radius);
                      background: var(--bg-color);">
            <div style="margin-bottom: 4px;">
              <strong>Proveedor:</strong> ${frm.doc.supplier_name}
            </div>
            <div style="margin-bottom: 4px;">
              <strong>Tipo de Persona:</strong> ${type_of_person_label}
            </div>
            <div>
              <strong>Base Imponible:</strong>
              ${frappe.format(frm.doc.total, { fieldtype: "Currency" })}
            </div>
          </div>
        `,
      },
      {
        fieldtype: "Link",
        fieldname: "tabulator_islr",
        label: __("Concepto ISLR"),
        options: "Tabulator ISLR",
        reqd: 1,
        get_query: function () {
          return {
            query: "l10n_ve.overrides.purchase_invoice.get_tabulators_by_person_type",
            filters: {
              existing_codes: existing_codes,
            },
          };
        },
      },
      {
        fieldtype: "Section Break",
        fieldname: "preview_section",
        label: __("Vista previa del cálculo"),
        depends_on: "eval:doc.tabulator_islr",
      },
      {
        fieldtype: "HTML",
        fieldname: "calculation_preview",
      },
    ],
    primary_action_label: __("Aplicar Retención"),
    primary_action(values) {
      if (!values.tabulator_islr) {
        frappe.msgprint(__("Debe seleccionar un concepto de ISLR."));
        return;
      }

      dialog.hide();

      // CASO 1: Factura en Borrador (docstatus == 0)
      if (frm.doc.docstatus === 0) {
        frappe.dom.freeze(__("Calculando retención de ISLR..."));
        frm
          .call("set_islr_concept", {
            tabulator_name: values.tabulator_islr,
          })
          .then(() => {
            frappe.dom.unfreeze();
            frm.reload_doc();
          })
          .catch(() => {
            frappe.dom.unfreeze();
            frappe.msgprint({
              title: __("Error"),
              message: __(
                "Ocurrió un error al calcular la retención. " +
                "Verifique la configuración del tabulador e intente nuevamente."
              ),
              indicator: "red",
            });
          });
      }
      // CASO 2: Factura Aprobada (docstatus == 1)
      else if (frm.doc.docstatus === 1) {
        if (!islr_account) {
          frappe.msgprint({
            title: __("Cuenta no configurada"),
            message: __(
              "La Cuenta de Retención de ISLR de Compras no está configurada " +
              "en la Compañía. Configure el campo 'Cuenta de ISLR (Compras)' " +
              "en el formulario de Compañía."
            ),
            indicator: "red",
          });
          return;
        }

        frappe.dom.freeze(__("Aplicando Retención de ISLR y generando asiento..."));
        frappe.call({
          method: "l10n_ve.overrides.purchase_invoice.apply_retroactive_purchase_withholding",
          args: {
            invoice_name: frm.doc.name,
            withholding_type: "ISLR",
            tax_account: islr_account,
            company: frm.doc.company,
            tabulator_name: values.tabulator_islr,
          },
          callback(r) {
            frappe.dom.unfreeze();
            if (r.message && r.message.status === "success") {
              frappe.show_alert({
                message: r.message.msg,
                indicator: "green",
              });
              frm.reload_doc();
            }
          },
          error() {
            frappe.dom.unfreeze();
          },
        });
      }
    },
  });

  // Eventos de vista previa
  dialog.fields_dict.tabulator_islr.$input.on("change", function () {
    update_islr_preview(dialog, frm, type_of_person);
  });
  dialog.fields_dict.tabulator_islr.df.onchange = function () {
    update_islr_preview(dialog, frm, type_of_person);
  };

  dialog.show();
}

/**
 * Actualiza la vista previa del cálculo ISLR en el diálogo.
 *
 * @param {object} dialog - La instancia del diálogo
 * @param {object} frm - La instancia del formulario
 * @param {string} type_of_person - Tipo de persona del proveedor
 */
function update_islr_preview(dialog, frm, type_of_person) {
  const tabulator_name = dialog.get_value("tabulator_islr");
  const preview_field = dialog.fields_dict.calculation_preview;

  if (!tabulator_name) {
    preview_field.$wrapper.html("");
    return;
  }

  frappe.call({
    method: "frappe.client.get",
    args: {
      doctype: "Tabulator ISLR",
      name: tabulator_name,
    },
    callback: function (r) {
      if (!r.message) return;

      const tabulator = r.message;
      let aliquot_info = null;
      if (type_of_person) {
        aliquot_info = (tabulator.aliquot || []).find(
          (aq) => aq.types_of_person === type_of_person && flt(aq.aliquot) > 0,
        );
      }

      if (!aliquot_info) {
        aliquot_info = (tabulator.aliquot || []).find(
          (aq) => flt(aq.aliquot) > 0,
        );
      }

      if (!aliquot_info) {
        preview_field.$wrapper.html(`
          <div style="padding: 10px 12px;
                      border: 1px solid var(--border-color);
                      border-radius: var(--border-radius);
                      background: var(--bg-color);
                      color: var(--orange-500);">
            No se encontró alícuota válida (> 0) en este tabulador.
          </div>
        `);
        return;
      }

      const base_amount = flt(frm.doc.total);
      const tax_base = flt(
        (base_amount * flt(aliquot_info.percentage_base)) / 100,
        2,
      );
      const islr_amount = flt(
        (tax_base * flt(aliquot_info.aliquot)) / 100 -
        flt(aliquot_info.subtracting),
        2,
      );

      const amount_formatted = frappe.format(Math.max(islr_amount, 0), {
        fieldtype: "Currency",
      });

      preview_field.$wrapper.html(`
        <div style="padding: 10px 12px;
                    border: 1px solid var(--border-color);
                    border-radius: var(--border-radius);
                    background: var(--bg-color);">
          <table style="width: 100%;">
            <tr>
              <td><strong>Código:</strong></td>
              <td>${tabulator.codigo}</td>
            </tr>
            <tr>
              <td><strong>Descripción:</strong></td>
              <td>${tabulator.descripcion}</td>
            </tr>
            <tr>
              <td><strong>Base imponible:</strong></td>
              <td>${frappe.format(base_amount, { fieldtype: "Currency" })}</td>
            </tr>
            <tr>
              <td><strong>% Base:</strong></td>
              <td>${flt(aliquot_info.percentage_base)}%</td>
            </tr>
            <tr>
              <td><strong>Base fiscal:</strong></td>
              <td>${frappe.format(tax_base, { fieldtype: "Currency" })}</td>
            </tr>
            <tr>
              <td><strong>Alícuota:</strong></td>
              <td>${flt(aliquot_info.aliquot)}%</td>
            </tr>
            <tr>
              <td><strong>Sustraendo:</strong></td>
              <td>${frappe.format(flt(aliquot_info.subtracting), { fieldtype: "Currency" })}</td>
            </tr>
            <tr style="border-top: 2px solid var(--text-muted); font-size: 1.1em;">
              <td><strong>Retención ISLR:</strong></td>
              <td><strong>${amount_formatted}</strong></td>
            </tr>
          </table>
        </div>
      `);
    },
  });
}

/**
 * Oculta el botón nativo de ERPNext "Return / Debit Note" y agrega
 * "Nota de Crédito", que abre directamente el DocType VE Purchase Credit Note
 * pre-llenado con los datos de la factura actual (mismo patrón que la
 * Factura de Venta con VE Sales Credit Note).
 * @param {object} frm
 */
function setup_credit_note_button(frm) {
  // El controller de ERPNext agrega "Return / Debit Note" DESPUÉS de
  // nuestro refresh. Usamos timeouts para removerlo siempre.
  setTimeout(() => {
    frm.page.remove_inner_button(__("Return / Debit Note"), __("Create"));
  }, 500);
  setTimeout(() => {
    frm.page.remove_inner_button(__("Return / Debit Note"), __("Create"));
  }, 1500);

  if (
    frm.doc.docstatus !== 1 ||
    frm.doc.is_return ||
    frm.doc.is_debit_note ||
    frm.doc.status === "Debit Note Issued"
  )
    return;

  frm.add_custom_button(
    __("Nota de Crédito"),
    function () {
      frappe.route_options = {
        return_against: frm.doc.name,
        company: frm.doc.company,
        supplier: frm.doc.supplier,
      };
      frappe.new_doc("VE Purchase Credit Note");
    },
    __("Create"),
  );
}

/**
 * Botón "Nota de Débito" en el grupo "Create" de la Factura de Compra.
 * Redirige al formulario de VE Purchase Debit Note pre-llenado con los
 * datos de la factura actual. Solo visible cuando la factura está aprobada
 * y no es una NC ni una ND.
 * @param {object} frm
 */
function setup_debit_note_button(frm) {
  if (
    frm.doc.docstatus !== 1 ||
    frm.doc.is_return ||
    frm.doc.is_debit_note ||
    frm.doc.status === "Debit Note Issued"
  )
    return;

  frm.add_custom_button(
    __("Nota de Débito"),
    function () {
      frappe.route_options = {
        return_against: frm.doc.name,
        company: frm.doc.company,
        supplier: frm.doc.supplier,
      };
      frappe.new_doc("VE Purchase Debit Note");
    },
    __("Create"),
  );
}

/**
 * Botones "Comprobante Retención IVA/ISLR" en el grupo "Create".
 * Crean, APRUEBAN (submit) y emiten a HKA el comprobante con las líneas
 * de esta factura, calculadas por el mismo get_valid_invoices del
 * formulario del comprobante, y avisan con el enlace sin salir de la
 * factura. Si la emisión a HKA falla, el comprobante queda aprobado en
 * estado Error (el cron lo reintenta si el auto-envío está activo).
 * Cada botón solo aparece si la factura tiene la retención
 * correspondiente en la tabla de impuestos; el servidor re-valida.
 */
function setup_withholding_voucher_buttons(frm) {
  if (frm.doc.docstatus !== 1 || frm.doc.is_return || frm.doc.is_debit_note)
    return;

  const taxes = frm.doc.taxes || [];
  const has_vat_withholding = taxes.some(
    (tax) => tax.charge_type === "VAT Withholding" && flt(tax.base_tax_amount),
  );
  const has_islr = taxes.some(
    (tax) => tax.charge_type === "ISLR" && flt(tax.base_tax_amount),
  );

  const create_voucher = (method, doctype, confirm_message) => {
    frappe.confirm(confirm_message, () => {
      frappe.call({
        method: method,
        args: { source_name: frm.doc.name },
        freeze: true,
        freeze_message: __("Generando y emitiendo comprobante de retención..."),
        callback: function (r) {
          const result = r.message;
          if (!result) {
            // Respuesta sin payload (p.ej. truncada): avisar en vez de un
            // no-op mudo, para evitar un doble clic a ciegas.
            frappe.msgprint({
              title: __("Sin respuesta del servidor"),
              message: __(
                "No se recibió confirmación. Verifique en la lista de comprobantes " +
                "de retención si el documento fue creado antes de reintentar.",
              ),
              indicator: "orange",
            });
            return;
          }

          if (result.emitted) {
            // Enlace con el N° de comprobante (HKA) como texto, no el name.
            // Valores de la respuesta de HKA: escapar antes de insertar en HTML.
            const route = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(result.voucher)}`;
            const number_text = frappe.utils.escape_html(
              result.voucher_number || result.voucher,
            );
            const number_link = `<a href="${route}"><b>${number_text}</b></a>`;
            frappe.msgprint({
              title: __("Comprobante emitido"),
              message:
                __("El comprobante {0} fue generado y emitido exitosamente.", [
                  number_link,
                ]) +
                (result.bill_control
                  ? "<br>" +
                  __("N° de Control: <b>{0}</b>", [
                    frappe.utils.escape_html(result.bill_control),
                  ])
                  : ""),
              indicator: "green",
            });
          } else {
            const link = frappe.utils.get_form_link(doctype, result.voucher, true);
            frappe.msgprint({
              title: __("Comprobante creado — emisión pendiente"),
              message:
                __(
                  "El comprobante {0} fue creado y aprobado, pero la emisión a HKA falló. " +
                  "Quedará pendiente de emisión: puede reintentarla desde el comprobante " +
                  "(o la reintenta el envío automático, si está activo).",
                  [link],
                ) +
                (result.error
                  ? `<br><br><b>${__("Motivo")}:</b> ${frappe.utils.escape_html(result.error)}`
                  : ""),
              indicator: "orange",
            });
          }
        },
      });
    });
  };

  if (has_vat_withholding) {
    frm.add_custom_button(
      __("Comprobante Retención IVA"),
      function () {
        create_voucher(
          "l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher.make_vat_withholding_voucher",
          "VAT Withholding Voucher",
          __("¿Desea generar, aprobar y emitir a HKA el comprobante de retención de IVA para esta factura?"),
        );
      },
      __("Create"),
    );
  }

  if (has_islr) {
    frm.add_custom_button(
      __("Comprobante Retención ISLR"),
      function () {
        create_voucher(
          "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher.make_islr_withholding_voucher",
          "ISLR Withholding Voucher",
          __("¿Desea generar, aprobar y emitir a HKA el comprobante de retención de ISLR para esta factura?"),
        );
      },
      __("Create"),
    );
  }
}

/**
 * Total del documento en la moneda de la cuenta del proveedor, para poder
 * compararlo contra outstanding_amount (que va en party_account_currency).
 * Réplica de get_total_in_party_account_currency de ERPNext.
 *
 * @param {object} frm
 * @returns {number}
 */
function get_purchase_total_in_party_currency(frm) {
  let fieldname = frm.doc.disable_rounded_total ? "grand_total" : "rounded_total";

  if (frm.doc.party_account_currency !== frm.doc.currency) {
    fieldname = "base_" + fieldname;
  }

  return flt(frm.doc[fieldname]);
}

/**
 * Botón para registrar el residual cambiario de una factura de compra
 * parcialmente pagada. Solo aplica cuando queda un saldo positivo pendiente,
 * lo cual representa una Ganancia para la empresa (deja de pagar ese residual).
 * Aplica para cualquier moneda, incluidas facturas en VES.
 *
 * Se exige que la factura tenga pagos aplicados (outstanding < total): sobre una
 * factura sin abonar el botón mandaría el 100% del documento al diferencial.
 *
 * @param {object} frm
 */
function setup_purchase_exchange_difference_button(frm) {
  const outstanding_amount = flt(frm.doc.outstanding_amount);

  if (
    frm.doc.docstatus === 1 &&
    outstanding_amount > 0 &&
    outstanding_amount < get_purchase_total_in_party_currency(frm)
  ) {
    frm.add_custom_button(
      __("Generar Diferencial Cambiario"),
      function () {
        const outstanding = flt(frm.doc.outstanding_amount);

        // format_currency y no frappe.format: el formatter de Currency pasa por
        // _right(), que envuelve el monto en un <div align=right> y parte la
        // frase del modal en tres líneas.
        const monto = format_currency(outstanding, frm.doc.party_account_currency);

        frappe.confirm(
          `¿Desea registrar el residual cambiario (<b>Ganancia</b>) por <b>${monto}</b>?<br><br>Se creará y enviará un Asiento Contable automáticamente.`,
          () => {
            frappe.call({
              method:
                "l10n_ve.overrides.purchase_invoice.create_purchase_exchange_difference_entry",
              args: { docname: frm.doc.name },
              freeze: true,
              freeze_message: __("Registrando diferencial cambiario..."),
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

function setup_government_withholding_button(frm) {
  if (frm.doc.docstatus === 1 && flt(frm.doc.outstanding_amount) > 0) {
    frm.add_custom_button(
      __("Retención Gubernamental"),
      function () {
        open_government_withholding_dialog(frm);
      },
      __("Acciones"),
    );
  }
}

function open_government_withholding_dialog(frm) {
  const conversion_rate = flt(frm.doc.conversion_rate) || 1.0;
  const company_currency = frm.doc.company_currency || "VEF";

  const base_grand_total =
    flt(frm.doc.base_grand_total) ||
    flt(flt(frm.doc.grand_total) * conversion_rate);
  let base_outstanding = flt(frm.doc.outstanding_amount);
  if (
    frm.doc.currency !== company_currency &&
    base_outstanding <= flt(frm.doc.grand_total)
  ) {
    base_outstanding = flt(base_outstanding * conversion_rate);
  }

  const dialog = new frappe.ui.Dialog({
    title: __("Registrar Retención Gubernamental"),
    fields: [
      {
        label: __("Monto Pendiente (Bs)"),
        fieldname: "outstanding_display",
        fieldtype: "Currency",
        options: "company_currency",
        default: base_outstanding,
        read_only: 1,
      },
      {
        label: __("Monto de Retención (Bs)"),
        fieldname: "amount",
        fieldtype: "Currency",
        options: "company_currency",
        reqd: 1,
        default: base_outstanding,
        description: __("Ingrese el monto de la retención a descontar."),
      },
      {
        label: __("Número de Comprobante"),
        fieldname: "voucher_number",
        fieldtype: "Data",
        reqd: 0,
        placeholder: __("Ej. 2026080001 (Opcional)"),
      },
      {
        label: __("Descripción / Concepto"),
        fieldname: "description",
        fieldtype: "Small Text",
        reqd: 0,
        placeholder: __(
          "Ej. Retención Timbre Fiscal / Impuesto Municipal de la factura",
        ),
      },
    ],
    primary_action_label: __("Confirmar y Contabilizar"),
    primary_action: function (values) {
      const amount = flt(values.amount);

      if (amount <= 0) {
        frappe.msgprint({
          title: __("Monto Inválido"),
          indicator: "red",
          message: __("El monto de la retención debe ser mayor a cero."),
        });
        return;
      }

      if (amount > base_grand_total) {
        frappe.msgprint({
          title: __("Exceso de Monto"),
          indicator: "red",
          message: __(
            "El monto de la retención ({0}) no puede ser mayor que el monto total de la factura ({1}).",
            [
              format_currency(amount, company_currency),
              format_currency(base_grand_total, company_currency),
            ],
          ),
        });
        return;
      }

      if (amount > base_outstanding) {
        frappe.msgprint({
          title: __("Exceso de Monto"),
          indicator: "red",
          message: __(
            "El monto de la retención ({0}) no puede superar el saldo pendiente de la factura ({1}).",
            [
              format_currency(amount, company_currency),
              format_currency(base_outstanding, company_currency),
            ],
          ),
        });
        return;
      }

      frappe.call({
        method:
          "l10n_ve.overrides.purchase_invoice.create_government_withholding_journal_entry_for_purchase_invoice",
        args: {
          docname: frm.doc.name,
          amount: amount,
          description: values.description,
          voucher_number: values.voucher_number,
        },
        freeze: true,
        freeze_message: __("Procesando Asiento Contable de Retención..."),
        callback: function (r) {
          if (r.message && r.message.status === "success") {
            dialog.hide();
            frappe.show_alert({
              message: r.message.message,
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

// ------------------------------------------------------------------ //
// Aplicación Retroactiva de Retenciones (docstatus == 1)             //
// ------------------------------------------------------------------ //

/**
 * Agrega el menú "Aplicar Retención" con las opciones de IVA e ISLR
 * para facturas de compra en estado Aprobado (docstatus == 1).
 * Solo muestra cada botón si la retención correspondiente aún no existe
 * en la tabla de impuestos.
 *
 * @param {object} frm - La instancia del formulario
 */
function setup_retroactive_withholding_buttons(frm) {
  if (
    frm.doc.docstatus !== 1 ||
    frm.doc.is_return ||
    frm.doc.is_debit_note ||
    !frm.doc.supplier
  ) {
    return;
  }

  const taxes = frm.doc.taxes || [];
  const has_vat_withholding = taxes.some(
    (t) => t.charge_type === "VAT Withholding" && flt(t.tax_amount),
  );
  const has_islr_withholding = taxes.some(
    (t) => t.charge_type === "ISLR" && flt(t.tax_amount),
  );

  // Ambas retenciones ya aplicadas: no hay nada que agregar
  if (has_vat_withholding && has_islr_withholding) {
    return;
  }

  frappe.db
    .get_value("Supplier", frm.doc.supplier, [
      "tax_withholding_category",
      "type_of_person",
    ])
    .then((r) => {
      const supplier_data = r.message || {};

      // Retención de IVA: solo si el proveedor tiene categoría de retención
      // y la factura aún no la tiene aplicada.
      if (!has_vat_withholding && supplier_data.tax_withholding_category) {
        frm.add_custom_button(
          __("Retención de IVA"),
          () => apply_purchase_vat_withholding(frm, supplier_data),
          __("Aplicar Retención"),
        );
      }

      // Retención de ISLR: siempre disponible si aún no está aplicada,
      // ya que el concepto se selecciona en el diálogo.
      // if (!has_islr_withholding) {
      //   frm.add_custom_button(
      //     __("Retención de ISLR"),
      //     () => apply_purchase_islr_withholding_dialog(frm, supplier_data),
      //     __("Aplicar Retención"),
      //   );
      // }
      if (!has_islr_withholding) {
        frm.add_custom_button(
          __("Retención de ISLR"),
          () => show_islr_dialog(frm),
          __("Aplicar Retención")
        );
      }
    });
}

/**
 * Aplica retroactivamente la Retención de IVA a una Factura de Compra aprobada.
 * Obtiene la cuenta desde la compañía y llama al backend tras confirmar el usuario.
 *
 * @param {object} frm           - Instancia del formulario
 * @param {object} supplier_data - Datos del proveedor (tax_withholding_category, type_of_person)
 */
function apply_purchase_vat_withholding(frm, supplier_data) {
  frappe.db
    .get_value(
      "Company",
      frm.doc.company,
      "purchase_vat_withholding_account",
    )
    .then((r) => {
      const co_data = r.message || {};
      const vat_account = co_data.purchase_vat_withholding_account;

      if (!vat_account) {
        frappe.msgprint({
          title: __("Cuenta no configurada"),
          message: __(
            "La Cuenta de Retención de IVA de Compras no está configurada "
            + "en la Compañía {0}. Vaya a Compañía y configure el campo "
            + "'Cuenta de Retención de IVA (Compras)'.",
            [frm.doc.company],
          ),
          indicator: "red",
        });
        return;
      }

      frappe.confirm(
        __(
          "¿Desea aplicar la Retención de IVA a esta factura? "
          + "Se generará el asiento contable correspondiente y se "
          + "reducirá el saldo pendiente.",
        ),
        () => {
          frappe.call({
            method:
              "l10n_ve.overrides.purchase_invoice.apply_retroactive_purchase_withholding",
            args: {
              invoice_name: frm.doc.name,
              withholding_type: "VAT",
              tax_account: vat_account,
              company: frm.doc.company,
            },
            freeze: true,
            freeze_message: __("Aplicando Retención de IVA y generando asiento..."),
            callback(r) {
              if (r.message && r.message.status === "success") {
                frappe.show_alert({
                  message: r.message.msg,
                  indicator: "green",
                });
                frm.reload_doc();
              }
            },
          });
        },
      );
    });
}
