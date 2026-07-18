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
    frm.set_value("is_special_taxpayer", 0);
    frm.set_value("tabulator_islr", "");
    frm.set_value("tax_withholding_category", "");
    frm.set_df_property("tax_withholding_category", "reqd", 0);
    frm.toggle_display("tax_withholding_category", false);
  } else {
    frm.toggle_display("is_special_taxpayer", true);
    frm.toggle_display("tabulator_islr", true);

    const is_special = frm.doc.is_special_taxpayer;
    frm.toggle_display("tax_withholding_category", is_special);
    frm.set_df_property("tax_withholding_category", "reqd", is_special ? 1 : 0);
    if (!is_special) {
      frm.set_value("tax_withholding_category", "");
    }
  }
}

function reorganize_customer_fields(frm) {
  let tax_id_field_wrapper = frm.get_field("tax_id").$wrapper;
  let type_of_person_field_wrapper = frm.get_field("type_of_person").$wrapper;
  let customer_type_field_wrapper = frm.get_field("customer_type").$wrapper;
  let customer_name_field_wrapper = frm.get_field("customer_name").$wrapper;
  let type_of_document_field_wrapper =
    frm.get_field("type_of_document").$wrapper;
  let nature_of_the_taxpayer_field_wrapper = frm.get_field(
    "nature_of_the_taxpayer",
  ).$wrapper;

  // Solo organizamos los campos de la pestaña de Detalles
  customer_type_field_wrapper.insertAfter(customer_name_field_wrapper);
  type_of_document_field_wrapper.insertAfter(customer_type_field_wrapper);
  nature_of_the_taxpayer_field_wrapper.insertAfter(
    type_of_document_field_wrapper,
  );
  type_of_person_field_wrapper.insertAfter(
    nature_of_the_taxpayer_field_wrapper,
  );
  tax_id_field_wrapper.insertAfter(type_of_person_field_wrapper);

  // Moviendo campos fiscales a la sección 'Información Fiscal'
  let is_special_taxpayer_field_wrapper = frm.get_field(
    "is_special_taxpayer",
  ).$wrapper;
  let tax_withholding_category_field_wrapper = frm.get_field(
    "tax_withholding_category",
  ).$wrapper;
  let tabulator_islr_field_wrapper = frm.get_field("tabulator_islr").$wrapper;

  tax_withholding_category_field_wrapper.insertAfter(
    is_special_taxpayer_field_wrapper,
  );
  tabulator_islr_field_wrapper.insertAfter(
    tax_withholding_category_field_wrapper,
  );
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
      }
    }
  });
}
