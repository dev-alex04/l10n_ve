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

  // Limpiar indicadores generados por ERPNext para este campo
  frm.dashboard.clear_indicators();

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
