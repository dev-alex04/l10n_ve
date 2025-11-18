// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Municipal Tax Declaration", {
  refresh: function (frm) {
    // Establecer la fecha actual si es un nuevo documento
    if (frm.is_new()) {
      if (!frm.doc.declaration_date) {
        frm.set_value("declaration_date", frappe.datetime.now_date());
      }
    }
  },
  company: get_company_data,
  declaration_date: get_eur_rate,
  // Enlazar la función al clic del botón definido en el DocType
  obtain_economic_activities: get_invoice_activities,
  // Disparador para recalcular si la tasa del euro cambia
  rate_eur: function(frm) {
    calculate_all_rows_tax(frm);
  }
});

function get_company_data(frm) {
  if (frm.doc.company) {
    frappe.call({
      method: "frappe.client.get",
      args: {
        doctype: "Company",
        name: frm.doc.company,
      },
      callback: function (r) {
        if (r.message) {
          frm.set_value("tax_id", r.message.tax_id);
          frm.set_value("num_license_economic", r.message.num_license_economic);
          frm.set_value("municipality", r.message.municipality);

          if (r.message.municipality) {
            frappe.db
              .get_value("VE Municipality", r.message.municipality, "state")
              .then((res) => {
                if (res && res.message)
                  frm.set_value("state", res.message.state);
              });
          } else {
            frm.set_value("state", "");
          }
        }
      },
    });
  } else {
    frm.set_value("tax_id", "");
    frm.set_value("municipality", "");
    frm.set_value("num_license_economic", "");
    frm.set_value("state", "");
  }
}

function get_eur_rate(frm) {
  if (frm.doc.declaration_date) {
    frappe.call({
      method: "erpnext.setup.utils.get_exchange_rate",
      args: {
        from_currency: "EUR",
        to_currency:
          frm.doc.currency || frappe.defaults.get_default("currency"),
        date: frappe.datetime.now_date(),
      },
      callback: function (r) {
        frm.set_value("rate_eur", r.message || 0);
      },
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
        municipality: frm.doc.municipality,
      },
      callback: function (r) {
        if (r.message && r.message.length > 0) {
          frm.clear_table("municipal_declaration_data");
          r.message.forEach((activity_data) => {
            let child = frm.add_child("municipal_declaration_data");

            // Asignar valores a los campos de la tabla hija
            child.code = activity_data.name;
            child.economic_sector = activity_data.sector;
            child.branch = activity_data.branch;
            child.aliquot = activity_data.aliquot; // Corregido a minúsculas
            child.mt_tcmmv = activity_data.mt_tcmmv; // El Ingreso Bruto es la base imponible calculada
            child.gross_income = activity_data.taxable_base; // El Ingreso Bruto es la base imponible calculada
          });
          calculate_all_rows_tax(frm); // Calcular el impuesto para todas las filas nuevas
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
    frm.doc.municipal_declaration_data.forEach(function(row) {
      calculate_row_tax(frm, row);
    });
    frm.refresh_field("municipal_declaration_data");
  }
}

function calculate_row_tax(frm, row) {
  let rate_eur = frm.doc.rate_eur || 0;

  // Cálculo basado en la alícuota (asumiendo que la alícuota es un porcentaje)
  let tax_by_aliquot = (row.gross_income || 0) * (row.aliquot || 0) / 100;

  // Cálculo basado en el Mínimo Tributable
  let tax_by_mt = (row.mt_tcmmv || 0) * rate_eur;

  // Se asigna el mayor de los dos cálculos
  row.calculated_tax = Math.max(tax_by_aliquot, tax_by_mt);
  console.log(tax_by_aliquot, tax_by_mt);
}

// Disparadores para recalcular si un valor en la tabla hija cambia
frappe.ui.form.on('VE Municipal Declaration Data', {
    aliquot: calculate_all_rows_tax,
    mt_tcmmv: calculate_all_rows_tax,
    gross_income: calculate_all_rows_tax
});