// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Municipal Tax Declaration", {
  onload: function (frm) {

    currency_data_setting(frm);
  },
  company: get_company_data,
  currency: get_exchange_rate_for_declaration,
  declaration_date: get_exchange_rate_for_declaration,
  declaration_date_from: function (frm) {
    validate_date_range(frm, "declaration_date_from");
    if (frm.doc.declaration_date_from && frm.doc.declaration_date_until) {
      get_invoice_activities(frm);
    }
  },
  declaration_date_until: function (frm) {
    validate_date_range(frm, "declaration_date_until");
    if (frm.doc.declaration_date_from && frm.doc.declaration_date_until) {
      get_invoice_activities(frm);
    }
  },
  rate: function (frm) {
    calculate_all_rows_tax(frm);
  }
});

async function get_company_data(frm) {
  if (frm.doc.company) {
    frappe.call({
      method: "l10n_ve.l10n_ve.doctype.ve_municipal_tax_declaration.ve_municipal_tax_declaration.get_company_details_for_declaration",
      args: {
        company_name: frm.doc.company
      },
      callback: function(r) {
        if (r.message) {

          const data = r.message;
          frm.set_value("tax_id", data.tax_id);
          frm.set_value("num_license_economic", data.num_license_economic);
          frm.set_value("legal_representative", data.legal_representative);
          frm.set_value("legal_representative_id", data.legal_representative_id);
          frm.set_value("municipality", data.municipality_name);
          frm.set_value("municipality_id", data.municipality);

          if (data.address_details) {
            frm.set_value("address_line1", data.address_details.address_line1);
            frm.set_value("state",  data.address_details.state_name);
            frm.set_value("parish", data.address_details.parish_name);
            frm.set_value("phone", data.address_details.phone);
            frm.set_value("email_id", data.address_details.email_id);
          } else {
            clear_address_fields(frm);
          }
        } else {
          clear_all_company_fields(frm);
        }
      }
    });
  } else {
    clear_all_company_fields(frm);
  }
}

function clear_all_company_fields(frm) {
  frm.set_value("tax_id", "");
  frm.set_value("municipality", "");
  frm.set_value("num_license_economic", "");
  frm.set_value("legal_representative", "");
  frm.set_value("legal_representative_id", "");
  clear_address_fields(frm);
}

function clear_address_fields(frm) {
  frm.set_value("state", "");
  frm.set_value("address_line1", "");
  frm.set_value("parish", "");
  frm.set_value("phone", "");
  frm.set_value("email_id", "");
  frm.set_value("sector", "");
}

function get_exchange_rate_for_declaration(frm) {
  let target_date = frm.doc.declaration_date;
  let from_currency = frm.doc.currency;

  if (target_date && from_currency) {
    frappe.call({
      method: "l10n_ve.l10n_ve.doctype.ve_municipal_tax_declaration.ve_municipal_tax_declaration.get_exchange_rate",
      args: {
        declaration_date: target_date,
        from_currency: from_currency
      },
      callback: function(r) {
        if (r.message && r.message > 0) {
          frm.set_value("rate", r.message);
          calculate_all_rows_tax(frm);
        } else {
          frm.set_value("rate", 0);
          frappe.msgprint({
            title: __('Tasa de Cambio no Encontrada'),
            indicator: 'orange',
            message: __('No se encontró una tasa para la fecha exacta (' + frappe.datetime.str_to_user(target_date) + '). Por favor, configúrela.')
          });
        }
      }
    });
  } else {
    frm.set_value("rate", 0);
  }
}

function validate_date_range(frm, field_changed) {
  const from_date = frm.doc.declaration_date_from;
  const to_date = frm.doc.declaration_date_until;

  if (from_date && to_date && from_date > to_date) {
    frm.set_value(field_changed, null);
    frappe.throw({
      title: __("Error en Fechas"),
      message: __("La 'Fecha Desde' no puede ser posterior a la 'Fecha Hasta'."),
      indicator: "red"
    });
  }
}

function get_invoice_activities(frm) {
  if (
    frm.doc.declaration_date_from &&
    frm.doc.declaration_date_until &&
    frm.doc.company &&
    frm.doc.municipality
  ) {
    frappe.call({
      method:
        "l10n_ve.l10n_ve.doctype.ve_municipal_tax_declaration.ve_municipal_tax_declaration.get_activities_from_sales_invoices",
      args: {
        from_date: frm.doc.declaration_date_from,
        to_date: frm.doc.declaration_date_until,
        company: frm.doc.company,
        municipality: frm.doc.municipality_id,
      },
      callback: function (r) {
        if (r.message && r.message.length > 0) {
          frm.clear_table("municipal_declaration_data");
          r.message.forEach((activity_data) => {
            let child = frm.add_child("municipal_declaration_data");

            child.code = activity_data.name;
            child.economic_sector = activity_data.sector;
            child.branch = activity_data.branch;
            child.aliquot = activity_data.aliquot;
            child.mt_tcmmv = activity_data.mt_tcmmv;
            child.gross_income = activity_data.taxable_base;
          });
          calculate_all_rows_tax(frm);
          frm.refresh_field("municipal_declaration_data");
          frappe.msgprint(__("Actividades cargadas correctamente."));
        } else {
          frappe.msgprint(
            __(
              "No se encontraron actividades para el rango de fechas seleccionado."
            )
          );
        }
      },
    });
  } else {
    frappe.msgprint(
      __(
        "Por favor, seleccione Compañía, Municipio, Fecha Desde y Fecha Hasta."
      )
    );
  }
}

function calculate_all_rows_tax(frm) {
  if (frm.doc.municipal_declaration_data && frm.doc.municipal_declaration_data.length > 0) {
    let total_calculated_tax = 0;
    frm.doc.municipal_declaration_data.forEach(function(row) {
      if (typeof calculate_municipal_declaration_row_tax === 'function') {
        calculate_municipal_declaration_row_tax(frm, row);
        total_calculated_tax += row.calculated_tax || 0;
      }
    });
    frm.set_value("tax_amount", total_calculated_tax);
    frm.set_value("total_pay", total_calculated_tax);
    frm.refresh_field("municipal_declaration_data");
    frm.refresh_field("tax_amount");
    frm.refresh_field("total_pay");
  }
}

async function currency_data_setting(frm) {
  const mt_currency = await frappe.db.get_single_value("Venezuela Account Settings", "mt_currency");

  if (mt_currency) {
    await frm.set_value("currency", mt_currency);
  } else if (frm.is_new()) {
    frm.set_value("currency", "");
    frm.set_value("rate", 0);
    frappe.msgprint({
      title: __('Configuración Requerida'),
      indicator: 'orange',
      message: __('Por favor, configure la <b>Moneda para Impuestos Municipales</b> en la sección de <b>Configuración de Cuentas de Venezuela</b>.')
    });
  }
}

frappe.ui.form.on("VE Municipal Declaration Data", {
  aliquot: function (frm) {
    calculate_all_rows_tax(frm);
  },
  mt_tcmmv: function (frm) {
    calculate_all_rows_tax(frm);
  },
  gross_income: function (frm) {
    calculate_all_rows_tax(frm);
  },
});

function calculate_municipal_declaration_row_tax(parent_frm, row) {
  let rate = parent_frm.doc.rate || 0;

  let tax_by_aliquot = (row.gross_income || 0) * (row.aliquot || 0) / 100;

  let tax_by_mt = (row.mt_tcmmv || 0) * rate;

  row.calculated_tax = Math.max(tax_by_aliquot, tax_by_mt);
}