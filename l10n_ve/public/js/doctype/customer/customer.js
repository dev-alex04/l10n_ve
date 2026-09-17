frappe.ui.form.on("Customer", {
  before_save: function (frm) {
    if (!frm.doc.customer_primary_address) {
      frappe.throw(
        __(
          "El campo 'Dirección Principal' es obligatorio. Por favor, ingrese una dirección usando el botón 'Agregar Dirección' en la parte superior derecha",
        ),
      );
    }
  },
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value("type_of_document", "");
      frm.set_value("nature_of_the_taxpayer", "");
      frm.set_value("type_of_person", "");
    }
    setup_phone_validation(frm, "mobile_no");
  },
  refresh: function (frm) {
    add_address_button(frm);
    reorganize_customer_fields(frm);

    if (frm.is_new()) {
      hidden_address_contact(frm);
    } else {
      get_address_link(frm);
      frm.toggle_display("customer_primary_contact", false);
    }

    handle_customer_field_change(frm, null);
    handle_field_change(frm, null);
    setup_refund_audit_button(frm);

    // Ocultar campos
    frm.toggle_display("account_manager", false);
    frm.toggle_display("lead_name", false);
    frm.toggle_display("opportunity_name", false);
    frm.toggle_display("prospect_name", false);

    const is_system_manager = frappe.user_roles.includes("System Manager");
    frm.toggle_display("contact_html", is_system_manager);
    if (!is_system_manager) {
      frm.fields_dict.contact_html.$wrapper.find("a").hide();
    }

    if (!frm.is_new()) {
      render_balance_indicators(frm);
      render_custom_account_summary(frm);
    }

    // Botón de impuesto municipal — solo para contribuyentes especiales ya guardados
    if (!frm.is_new() && frm.doc.is_special_taxpayer) {
      frm.add_custom_button(__("Configurar Impuesto Municipal"), function () {
        open_municipal_tax_dialog(frm);
      }, __("Impuestos"));
    }

    // Filtro para no traer actividades de grupo en el formulario
    frm.set_query("economic_activity", function () {
      return {
        filters: {
          is_group: 0,
        },
      };
    });
  },

  nature_of_the_taxpayer: function (frm) {
    handle_field_change(frm, "nature_of_the_taxpayer");
    handle_customer_field_change(frm, "nature_of_the_taxpayer");
  },

  type_of_person: function (frm) {
    handle_field_change(frm, "type_of_person");
    handle_customer_field_change(frm, "type_of_person");
  },

  type_of_document: function (frm) {
    handle_field_change(frm, "type_of_document");
    handle_customer_field_change(frm, "type_of_document");
  },

  tax_id: function (frm) {
    build_tax_id(frm);
  },

  is_special_taxpayer: function (frm) {
    handle_customer_field_change(frm, "is_special_taxpayer");
  },

  validate: function (frm) {
    // validate_phone_format(frm, "mobile_no");
    validate_party_emails(frm);
  },
});

function handle_customer_field_change(frm, fieldname) {
  const doc_type = frm.doc.type_of_document;

  if (doc_type === "Cedula" || doc_type === "Passport") {
    frm.toggle_display("is_special_taxpayer", false);
    frm.toggle_display("tabulator_islr", false);
    if (fieldname) {
      if (frm.doc.is_special_taxpayer) frm.set_value("is_special_taxpayer", 0);
      if (frm.doc.tabulator_islr) frm.set_value("tabulator_islr", "");
      if (frm.doc.tax_withholding_category) frm.set_value("tax_withholding_category", "");
    }
    frm.set_df_property("tax_withholding_category", "reqd", 0);
    frm.toggle_display("tax_withholding_category", false);
    frm.toggle_display("ve_municipality", false);
    frm.toggle_display("economic_activity", false);
    frm.toggle_display("municipal_withholding_rate", false);
    frm.toggle_display("municipality_tax", false);
  } else {
    frm.toggle_display("is_special_taxpayer", true);
    frm.toggle_display("tabulator_islr", true);

    const is_special = frm.doc.is_special_taxpayer;
    frm.toggle_display("tax_withholding_category", is_special);
    frm.set_df_property("tax_withholding_category", "reqd", is_special ? 1 : 0);
    if (!is_special && fieldname) {
      if (frm.doc.tax_withholding_category) frm.set_value("tax_withholding_category", "");
      if (frm.doc.ve_municipality) frm.set_value("ve_municipality", "");
      if (frm.doc.economic_activity) frm.set_value("economic_activity", "");
      if (frm.doc.municipal_withholding_rate) frm.set_value("municipal_withholding_rate", 0);
      if (frm.doc.municipality_tax) frm.set_value("municipality_tax", "");
    }
    frm.toggle_display("ve_municipality", is_special);
    frm.toggle_display("economic_activity", is_special);
    frm.toggle_display("municipal_withholding_rate", is_special);
    frm.toggle_display("municipality_tax", is_special);
  }
}

function reorganize_customer_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id")?.$wrapper;
  let type_of_person_field_wrapper = frm.get_field("type_of_person")?.$wrapper;
  let customer_type_field_wrapper = frm.get_field("customer_type")?.$wrapper;
  let customer_name_field_wrapper = frm.get_field("customer_name")?.$wrapper;
  let type_of_document_field_wrapper =
    frm.get_field("type_of_document")?.$wrapper;
  let nature_of_the_taxpayer_field_wrapper = frm.get_field(
    "nature_of_the_taxpayer",
  )?.$wrapper;

  // Solo organizamos los campos de la pestaña de Detalles
  if (customer_name_field_wrapper) {
    if (customer_type_field_wrapper) customer_type_field_wrapper.insertAfter(customer_name_field_wrapper);
    if (type_of_document_field_wrapper) type_of_document_field_wrapper.insertAfter(customer_type_field_wrapper || customer_name_field_wrapper);
    if (nature_of_the_taxpayer_field_wrapper) nature_of_the_taxpayer_field_wrapper.insertAfter(type_of_document_field_wrapper || customer_name_field_wrapper);
    if (type_of_person_field_wrapper) type_of_person_field_wrapper.insertAfter(nature_of_the_taxpayer_field_wrapper || customer_name_field_wrapper);
    if (tax_id_field_wrapper) tax_id_field_wrapper.insertAfter(type_of_person_field_wrapper || customer_name_field_wrapper);
  }

  // Moviendo campos fiscales a la sección 'Información Fiscal' dividiendo en 2 columnas (Izquierda SENIAT, Derecha ISAE)
  let is_special_taxpayer_field_wrapper = frm.get_field("is_special_taxpayer")?.$wrapper;
  let tax_withholding_category_field_wrapper = frm.get_field("tax_withholding_category")?.$wrapper;
  let tabulator_islr_field_wrapper = frm.get_field("tabulator_islr")?.$wrapper;

  let ve_municipality_field_wrapper = frm.get_field("ve_municipality")?.$wrapper;
  let economic_activity_field_wrapper = frm.get_field("economic_activity")?.$wrapper;
  let municipal_withholding_rate_field_wrapper = frm.get_field("municipal_withholding_rate")?.$wrapper;
  let municipality_tax_field_wrapper = frm.get_field("municipality_tax")?.$wrapper;

  if (is_special_taxpayer_field_wrapper) {
    let $section = is_special_taxpayer_field_wrapper.closest(".form-section");
    if ($section && $section.length) {
      let $section_body = $section.find(".section-body");
      let $cols = $section_body.children(".form-column");

      let $col1 = $cols.eq(0);
      let $col2 = $cols.eq(1);

      if (!$col2 || !$col2.length) {
        $col2 = $('<div class="form-column col-sm-6"></div>').appendTo($section_body);
        $col1.removeClass("col-sm-12").addClass("col-sm-6");
      }

      // Columna 1 (Izquierda): Retenciones Nacionales (SENIAT / ISLR) + Alícuota Municipal
      if (is_special_taxpayer_field_wrapper) $col1.append(is_special_taxpayer_field_wrapper);
      if (tax_withholding_category_field_wrapper) $col1.append(tax_withholding_category_field_wrapper);
      if (tabulator_islr_field_wrapper) $col1.append(tabulator_islr_field_wrapper);
      if (municipal_withholding_rate_field_wrapper) $col1.append(municipal_withholding_rate_field_wrapper);

      // Columna 2 (Derecha): Datos Municipales (ISAE)
      if (ve_municipality_field_wrapper) $col2.append(ve_municipality_field_wrapper);
      if (economic_activity_field_wrapper) $col2.append(economic_activity_field_wrapper);
      if (municipality_tax_field_wrapper) $col2.append(municipality_tax_field_wrapper);
    }
  }
}

/**
 * Reemplaza el indicador genérico de "Total Unpaid" de ERPNext por
 * etiquetas en español que muestran el saldo del cliente de forma clara:
 *   - Saldo a Favor (verde, valor positivo) cuando el cliente pagó de más.
 *   - Saldo en Contra (naranja) cuando tiene deuda pendiente.
 *   - Sin Saldo Pendiente (verde) cuando está al día.
 */
function render_balance_indicators(frm) {
  var info = frm.doc.__onload && frm.doc.__onload.dashboard_info;
  if (!info || info.length === 0) return;

  // Solo aplica cuando hay una única empresa (caso habitual)
  if (info.length !== 1) return;

  var data = info[0];
  var balance = flt(data.total_unpaid);
  var currency = data.currency;

  // Limpiar indicadores generados por ERPNext (stats_area_row es el contenedor real)
  frm.dashboard.stats_area_row.empty();
  frm.dashboard.stats_area.show();

  // Facturación anual (se mantiene igual que ERPNext)
  frm.dashboard.add_indicator(
    __('Facturación Anual: {0}', [format_currency(data.billing_this_year, currency)]),
    'blue'
  );

  // Saldo: interpretamos el signo contable
  if (balance > 0) {
    frm.dashboard.add_indicator(
      __('Saldo en Contra: {0}', [format_currency(balance, currency)]),
      'orange'
    );
  } else if (balance < 0) {
    frm.dashboard.add_indicator(
      __('Saldo a Favor: {0}', [format_currency(Math.abs(balance), currency)]),
      'green'
    );
  } else {
    frm.dashboard.add_indicator(__('Sin Saldo Pendiente'), 'green');
  }

  // Puntos de fidelidad (si aplica)
  if (data.loyalty_points) {
    frm.dashboard.add_indicator(
      __('Puntos de Fidelidad: {0}', [data.loyalty_points]),
      'blue'
    );
  }
}

/**
 * Agrega una sección HTML en el tablero del cliente que muestra
 * de forma resumida el total facturado, cobrado, retenciones/créditos
 * y la tabla de facturas pendientes con sus días de vencimiento.
 */
function render_custom_account_summary(frm) {
  frappe.call({
    method: "l10n_ve.overrides.customer.get_balance_summary",
    args: { customer: frm.doc.name },
    callback: function (r) {
      if (r.message) {
        var data = r.message;
        
        // Limpiar sección previa si ya existe
        frm.dashboard.parent.find(".custom-account-summary-section").remove();
        
        var currency = data.account_currency || "VEF";
        
        var total_credits_withholdings = data.total_credits + data.total_withholdings;
        
        // Tarjeta dinámica para anticipos sin aplicar
        var unapplied_card_html = "";
        if (data.unapplied_credits > 0.01) {
          unapplied_card_html = `
            <div style="flex: 1; min-width: 150px; background: #ffffff; padding: 10px; border-radius: 4px; border-left: 4px solid #f1c40f; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-top: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
              <div style="font-size: 10px; text-transform: uppercase; color: #8d99a6; font-weight: bold; margin-bottom: 4px;">Anticipos sin aplicar</div>
              <div style="font-size: 14px; font-weight: bold; color: #2c3e50;">${format_currency(data.unapplied_credits, currency)}</div>
            </div>
          `;
        }

        // Explicación de los montos contables vs comerciales
        var math_explanation = "";
        if (data.unapplied_credits > 0.01) {
          math_explanation = `
            <div style="margin-top: 10px; font-size: 11px; color: #6f7c87; background: #fffde7; padding: 8px 12px; border-radius: 4px; border-left: 3px solid #f1c40f; margin-bottom: 15px; border-top: 1px solid #ffe082; border-right: 1px solid #ffe082; border-bottom: 1px solid #ffe082;">
              <i class="fa fa-info-circle" style="color: #f39c12; margin-right: 5px;"></i>
              <strong>Conciliación de Saldos:</strong> El cliente tiene facturas por pagar por un total de <strong>${format_currency(data.open_invoices_total, currency)}</strong>, pero dispone de <strong>${format_currency(data.unapplied_credits, currency)}</strong> en anticipos o créditos no cruzados. Por lo tanto, el saldo neto por cobrar real es de <strong>${format_currency(data.net_balance, currency)}</strong>.
            </div>
          `;
        }
        
        var section_html = `
          <div class="custom-account-summary-section" style="margin-top: 20px; border: 1px solid #d1d8dd; border-radius: 4px; padding: 15px; background-color: #fafbfc;">
            <h5 style="margin-top: 0; margin-bottom: 15px; color: #5a6b7c; font-weight: bold; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">
              <i class="fa fa-info-circle" style="margin-right: 5px;"></i> Resumen de Cuenta del Cliente
            </h5>
            <!-- Fila de totales -->
            <div style="display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;">
              <div style="flex: 1; min-width: 150px; background: #ffffff; padding: 10px; border-radius: 4px; border-left: 4px solid #1b9de2; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-top: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
                <div style="font-size: 10px; text-transform: uppercase; color: #8d99a6; font-weight: bold; margin-bottom: 4px;">Total Facturado</div>
                <div style="font-size: 14px; font-weight: bold; color: #2c3e50;">${format_currency(data.total_invoiced, currency)}</div>
              </div>
              <div style="flex: 1; min-width: 150px; background: #ffffff; padding: 10px; border-radius: 4px; border-left: 4px solid #2ecc71; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-top: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
                <div style="font-size: 10px; text-transform: uppercase; color: #8d99a6; font-weight: bold; margin-bottom: 4px;">Total Cobrado</div>
                <div style="font-size: 14px; font-weight: bold; color: #2c3e50;">${format_currency(data.total_paid, currency)}</div>
              </div>
              <div style="flex: 1; min-width: 150px; background: #ffffff; padding: 10px; border-radius: 4px; border-left: 4px solid #e67e22; box-shadow: 0 1px 3px rgba(0,0,0,0.05); border-top: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;">
                <div style="font-size: 10px; text-transform: uppercase; color: #8d99a6; font-weight: bold; margin-bottom: 4px;">Retenciones y Créditos</div>
                <div style="font-size: 14px; font-weight: bold; color: #2c3e50;">${format_currency(total_credits_withholdings, currency)}</div>
              </div>
              ${unapplied_card_html}
            </div>
            
            ${math_explanation}
          </div>
        `;
        
        var $section = $(section_html);
        if (frm.dashboard.stats_area && frm.dashboard.stats_area.wrapper && frm.dashboard.stats_area.wrapper.length) {
          $section.insertAfter(frm.dashboard.stats_area.wrapper);
        } else {
          frm.dashboard.add_section($section);
        }

        render_refund_audit_banner(frm, $section);
      }
    }
  });
}

/**
 * Abre el diálogo para configurar el impuesto municipal (ISAE) del cliente.
 *
 * - Pre-carga los valores ya guardados en el cliente.
 * - Busca la alícuota existente en VE Municipality Taxes para el par
 *   (municipio, actividad económica) seleccionados.
 * - Al confirmar: crea o actualiza el registro en VE Municipality Taxes y
 *   enlaza los campos custom_* en el Customer sin requerir un save() del form.
 */
function open_municipal_tax_dialog(frm) {
  // 1. Primero traemos la info actual del cliente
  frappe.call({
    method: "l10n_ve.overrides.customer.get_municipal_tax_info",
    args: { customer: frm.doc.name },
    callback: function (r) {
      if (r.exc) return;

      const info = r.message || {};

      const dialog = new frappe.ui.Dialog({
        title: __("Configurar Impuesto Municipal (ISAE)"),
        fields: [
          {
            label: __("Municipio"),
            fieldname: "municipality",
            fieldtype: "Link",
            options: "VE Municipality",
            reqd: 1,
            default: info.municipality || info.suggested_municipality || frm.doc.ve_municipality || "",
            description: __("Municipio donde el cliente ejerce actividad y aplica el ISAE."),
          },
          {
            label: __("Actividad Económica"),
            fieldname: "economic_activity",
            fieldtype: "Link",
            options: "VE Economic Activity",
            reqd: 1,
            default: info.economic_activity || frm.doc.economic_activity || "",
            description: __("Actividad económica registrada del cliente."),
          },
          {
            label: __("Código de Actividad"),
            fieldname: "activity_code",
            fieldtype: "Data",
            read_only: 0,
            default: "",
            description: __("Código de actividad. Se pre-rellena desde la Actividad Económica pero puede modificarse si difiere."),
          },
          {
            label: __("Alícuota (%)"),
            fieldname: "aliquot",
            fieldtype: "Float",
            precision: 2,
            reqd: 1,
            default: info.existing_aliquot || info.municipal_withholding_rate || 0,
            description: __("Porcentaje de retención ISAE a aplicar. Se prellenará si ya existe el impuesto para este municipio + actividad."),
          },
        ],
        primary_action_label: __("Guardar"),
        primary_action: function (values) {
          const rate = flt(values.aliquot);
          if (rate < 0 || rate > 100) {
            frappe.msgprint({
              title: __("Alícuota Inválida"),
              indicator: "red",
              message: __("La alícuota municipal debe estar entre 0% y 100%."),
            });
            return;
          }

          frappe.call({
            method: "l10n_ve.overrides.customer.setup_or_update_municipal_tax",
            args: {
              customer: frm.doc.name,
              municipality: values.municipality,
              economic_activity: values.economic_activity,
              aliquot: values.aliquot,
              activity_code: values.activity_code,
            },
            freeze: true,
            freeze_message: __("Configurando impuesto municipal..."),
            callback: function (res) {
              if (res.exc) return;

              // Actualizar el form en memoria sin requerir un save del usuario
              frm.set_value("ve_municipality", values.municipality);
              frm.set_value("economic_activity", res.message.economic_activity);
              frm.set_value("municipality_tax", res.message.municipality_tax);
              frm.set_value("municipal_withholding_rate", res.message.aliquot);

              frappe.show_alert({
                message: __("Impuesto municipal configurado: {0}% — {1}", [
                  res.message.aliquot,
                  res.message.municipality_tax,
                ]),
                indicator: "green",
              });

              dialog.hide();
              frm.reload_doc();
            },
          });
        },
        secondary_action_label: __("Eliminar Impuesto"),
        secondary_action: function () {
          frappe.confirm(
            __("¿Está seguro de eliminar la configuración de impuesto municipal de este cliente?"),
            function () {
              frappe.call({
                method: "l10n_ve.overrides.customer.remove_municipal_tax",
                args: { customer: frm.doc.name },
                freeze: true,
                freeze_message: __("Eliminando impuesto municipal..."),
                callback: function (res) {
                  if (res.exc) return;
                  frappe.show_alert({
                    message: __("Configuración de impuesto municipal eliminada."),
                    indicator: "orange",
                  });
                  dialog.hide();
                  frm.reload_doc();
                },
              });
            }
          );
        },
      });

      // Cuando cambia la actividad económica: traer el código y buscar alícuota existente
      dialog.fields_dict.economic_activity.df.onchange = function () {
        const act = dialog.get_value("economic_activity");
        const mun = dialog.get_value("municipality");

        if (act) {
          frappe.db.get_value("VE Economic Activity", act, "code", function (data) {
            dialog.set_value("activity_code", data.code || "");
          });
        }

        if (act && mun) {
          frappe.db.get_value(
            "VE Municipality Taxes",
            { municipality: mun, economic_activity: act },
            ["name", "aliquot"],
            function (data) {
              if (data && data.aliquot) {
                dialog.set_value("aliquot", data.aliquot);
                frappe.show_alert({
                  message: __("Alícuota existente cargada: {0}%", [data.aliquot]),
                  indicator: "blue",
                });
              }
            }
          );
        }
      };

      // Al cambiar municipio: también buscar alícuota existente
      dialog.fields_dict.municipality.df.onchange = function () {
        const mun = dialog.get_value("municipality");
        const act = dialog.get_value("economic_activity");

        if (act && mun) {
          frappe.db.get_value(
            "VE Municipality Taxes",
            { municipality: mun, economic_activity: act },
            ["name", "aliquot"],
            function (data) {
              if (data && data.aliquot) {
                dialog.set_value("aliquot", data.aliquot);
                frappe.show_alert({
                  message: __("Alícuota existente cargada: {0}%", [data.aliquot]),
                  indicator: "blue",
                });
              }
            }
          );
        }
      };

      // Pre-cargar código si ya hay actividad seleccionada
      if (info.economic_activity) {
        frappe.db.get_value(
          "VE Economic Activity",
          info.economic_activity,
          "code",
          function (data) {
            dialog.set_value("activity_code", data.code || "");
          }
        );
      }

      // Filtro para no traer actividades de grupo en el diálogo
      dialog.fields_dict.economic_activity.get_query = function () {
        return {
          filters: {
            is_group: 0,
          },
        };
      };

      dialog.show();
    },
  });
}

/**
 * Botón «Revisar reembolsos»: avisa si los cobros del cliente ofrecen un anticipo que ya se le
 * devolvió, y ofrece corregirlo. El mismo diagnóstico del reporte Unlinked Refunds («Reembolsos sin enlazar»),
 * para cuando alguien llega por la ficha del cliente y no por la lista.
 *
 * @param {object} frm - Instancia del formulario Customer
 */
function setup_refund_audit_button(frm) {
  const roles = ["Accounts Manager", "Accounts User", "ISP Finance Pro", "System Manager"];
  if (frm.is_new() || !roles.some((role) => frappe.user_roles.includes(role))) {
    return;
  }

  frm.add_custom_button(__("Revisar reembolsos"), () => {
    frappe
      .call({
        method: "l10n_ve.overrides.advance_refund_audit.scan",
        args: { company: frappe.defaults.get_user_default("Company"), party: frm.doc.name },
        freeze: true,
        freeze_message: __("Revisando..."),
      })
      .then((r) => {
        const cases = r.message || [];
        if (!cases.length) {
          frappe.show_alert({
            message: __("Este cliente no tiene reembolsos sin enlazar."),
            indicator: "green",
          });
          return;
        }
        show_refund_audit_dialog(frm, cases[0]);
      });
  }, __("Acciones"));
}

/**
 * Muestra qué se le haría a la cuenta del cliente y, si lo aprueban, lo hace.
 *
 * @param {object} frm - Instancia del formulario Customer
 * @param {object} caso - Caso devuelto por el diagnóstico
 */
function show_refund_audit_dialog(frm, refund_case) {
  frappe
    .call({
      method: "l10n_ve.overrides.advance_refund_audit.describe",
      args: { company: refund_case.company, party: refund_case.party, advance_account: refund_case.advance_account },
    })
    .then((r) => {
      const plan = r.message || {};
      const summary = __("Sus cobros ofrecen {0} y el mayor dice {1}.", [
        format_currency(refund_case.offered),
        format_currency(refund_case.ledger),
      ]);

      if (!plan.can_fix) {
        frappe.msgprint({
          title: __("Hay que revisarlo a mano"),
          message: `<p>${summary}</p><p>${frappe.utils.escape_html(plan.problem || "")}</p>`,
          indicator: "orange",
        });
        return;
      }

      frappe.confirm(
        `<p>${summary}</p><ul><li>${plan.lines.map(frappe.utils.escape_html).join("</li><li>")}</li></ul>`,
        () => {
          frappe.call({
            method: "l10n_ve.overrides.advance_refund_audit.fix",
            args: { company: refund_case.company, party: refund_case.party, advance_account: refund_case.advance_account },
            freeze: true,
            freeze_message: __("Corrigiendo..."),
            callback(res) {
              if (!res.message) return;
              frappe.show_alert({
                message: __("Listo. Documentos creados: {0}", [res.message.documents.join(", ")]),
                indicator: "green",
              });
              frm.reload_doc();
            },
          });
        }
      );
    });
}

/**
 * Barra dentro del resumen de cuenta: avisa cuando los cobros del cliente ofrecen un anticipo
 * que ya se le devolvió, y trae el botón para corregirlo ahí mismo. Solo aparece cuando hay
 * algo que corregir, así que en un cliente sano no se ve nada.
 *
 * @param {object} frm - Instancia del formulario Customer
 * @param {object} $section - La sección del resumen, ya insertada
 */
function render_refund_audit_banner(frm, $section) {
  const roles = ["Accounts Manager", "Accounts User", "ISP Finance Pro", "System Manager"];
  if (!roles.some((role) => frappe.user_roles.includes(role))) {
    return;
  }

  frappe.call({
    method: "l10n_ve.overrides.advance_refund_audit.scan",
    args: {
      company: frm.doc.represents_company || frappe.defaults.get_user_default("Company"),
      party: frm.doc.name,
    },
    callback(r) {
      const refund_case = (r.message || [])[0];
      if (!refund_case) {
        return;
      }

      const summary = __("Sus cobros ofrecen {0} y el mayor dice {1}.", [
        format_currency(refund_case.offered),
        format_currency(refund_case.ledger),
      ]);
      const detail = refund_case.problem
        ? `<div style="margin-top: 4px; color: #8d99a6;">${frappe.utils.escape_html(refund_case.problem)}</div>`
        : "";
      const button = refund_case.problem
        ? ""
        : `<button class="btn btn-sm btn-primary refund-audit-fix" style="white-space: nowrap;">${__(
            "Corregir"
          )}</button>`;

      const $banner = $(`
        <div style="display: flex; gap: 12px; align-items: center; justify-content: space-between;
          font-size: 11px; color: #6f7c87; background: #fdf2e9; padding: 8px 12px; border-radius: 4px;
          border: 1px solid #f5cba7; border-left: 3px solid #e67e22; margin-bottom: 15px;">
          <div>
            <i class="fa fa-exclamation-circle" style="color: #e67e22; margin-right: 5px;"></i>
            <strong>${__("Reembolso sin enlazar")}:</strong> ${summary}
            ${detail}
          </div>
          ${button}
        </div>
      `);
      $banner.find(".refund-audit-fix").on("click", () => show_refund_audit_dialog(frm, refund_case));
      $section.find("h5").after($banner);
    },
  });
}
