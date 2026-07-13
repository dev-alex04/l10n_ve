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

/**
 * Muestra el diálogo para seleccionar un concepto ISLR del tabulador.
 * Obtiene el tipo de persona del proveedor para filtrar las alícuotas válidas.
 *
 * @param {object} frm - La instancia del formulario
 */
function show_islr_dialog(frm) {
  frappe.db
    .get_value("Supplier", frm.doc.supplier, "type_of_person")
    .then((r) => {
      const type_of_person = r.message.type_of_person;

      if (!type_of_person) {
        frappe.msgprint({
          title: __("Configuración faltante"),
          message: __(
            "El proveedor <b>{0}</b> no tiene configurado el Tipo de Persona. " +
              "Configúrelo antes de asignar retención de ISLR.",
            [frm.doc.supplier_name || frm.doc.supplier],
          ),
          indicator: "red",
        });
        return;
      }

      const type_of_person_label = __(type_of_person);

      // Códigos ISLR ya cargados en la factura (para excluir duplicados)
      const existing_codes = (frm.doc.taxes || [])
        .filter((tax) => tax.charge_type === "ISLR" && tax.code)
        .map((tax) => tax.code);

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
                  <strong>Proveedor:</strong> ${frm.doc.supplier_name || frm.doc.supplier}
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
                query:
                  "l10n_ve.overrides.purchase_invoice.get_tabulators_by_person_type",
                filters: {
                  type_of_person: type_of_person,
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
                    "Verifique la configuración del tabulador e intente nuevamente.",
                ),
                indicator: "red",
              });
            });
        },
      });

      // Vista previa al seleccionar un tabulador
      dialog.fields_dict.tabulator_islr.$input.on("change", function () {
        update_islr_preview(dialog, frm, type_of_person);
      });
      // Actualizar tambien cuando se selecciona via awesomebar
      dialog.fields_dict.tabulator_islr.df.onchange = function () {
        update_islr_preview(dialog, frm, type_of_person);
      };

      dialog.show();
    });
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
      const aliquot_info = (tabulator.aliquot || []).find(
        (aq) => aq.types_of_person === type_of_person && flt(aq.aliquot) > 0,
      );

      if (!aliquot_info) {
        preview_field.$wrapper.html(`
          <div style="padding: 10px 12px;
                      border: 1px solid var(--border-color);
                      border-radius: var(--border-radius);
                      background: var(--bg-color);
                      color: var(--orange-500);">
            No se encontró alícuota para el tipo de persona
            <b>${__(type_of_person)}</b> en este tabulador.
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
