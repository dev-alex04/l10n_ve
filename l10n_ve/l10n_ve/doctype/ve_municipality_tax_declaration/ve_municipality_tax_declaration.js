// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Municipality Tax Declaration", {
  validate: function (frm) {
    if (frm.doc.is_branch_required && !frm.doc.branch) {
      frappe.throw(__("Debe seleccionar una sucursal."));
    }
  },
  onload: function (frm) {
    currency_data_setting(frm);
    if (frm.is_new()) {
      const currentYear = new Date().getFullYear();
      frm.set_value("declaration_year", currentYear);
    }
  },
  refresh: function (frm) {
    add_declaration_upload_button(frm);
    check_branch_required(frm);
  },
  currency: get_exchange_rate_for_declaration,
  declaration_date: get_exchange_rate_for_declaration,
  rate: function (frm) {
    calculate_all_rows_tax(frm);
  },
  declaration_month: setup_triggers,
  declaration_year: validate_year,
  setup: function (frm) {
    frm.set_query("branch", function () {
      return {
        filters: {
          "company": frm.doc.company,
          "is_group": 0
        }
      };
    });
  },
  company: async (frm) => {
    if (
      frm.doc.municipality_declaration_data &&
      frm.doc.municipality_declaration_data.length > 0
    ) {
      frm.clear_table("municipality_declaration_data");
      frm.refresh_field("municipality_declaration_data");
    }
    await get_company_data(frm);
    setup_triggers(frm);
    check_branch_required(frm);
  },
  branch: function (frm) {
    frm.clear_table("municipality_declaration_data");
    frm.refresh_field("municipality_declaration_data");

    if (frm.doc.branch) {
      frappe.call({
        method: "l10n_ve.l10n_ve.doctype.ve_municipality_tax_declaration.ve_municipality_tax_declaration.get_branch_details",
        args: { branch_name: frm.doc.branch },
        callback: function (r) {
          if (r.message) {
            frm.set_value('municipality', r.message.municipality);
            frm.set_value('municipality_id', r.message.municipality_id);
            frm.set_value('state', r.message.state);

            setup_triggers(frm);
          }
        }
      });
    } else {
      get_company_data(frm);
    }
  }
});

function validate_year(frm) {
  if (frm.doc.declaration_year) {
    const year_str = frm.doc.declaration_year.toString();
    let is_valid = true;

    if (year_str.length > 4) {
      const truncated_year = year_str.slice(0, 4);
      frm.set_value("declaration_year", parseInt(truncated_year, 10));
      frappe.msgprint(__("El año no puede tener más de 4 dígitos."));
    } else if (year_str.length < 3) {
      frappe.msgprint(__("El año debe tener al menos 3 dígitos."));
      is_valid = false;
    }

    if (is_valid) {
      setup_triggers(frm);
    }
  }
}

async function get_company_data(frm) {
  if (frm.doc.company) {
    try {
      const r = await frappe.call({
        method:
          "l10n_ve.l10n_ve.doctype.ve_municipality_tax_declaration.ve_municipality_tax_declaration.get_company_details_for_declaration",
        args: {
          company_name: frm.doc.company,
        },
      });
      if (r.message) {
        const data = r.message;
        let missing_fields = [];
        if (!data.tax_id) missing_fields.push(__("Tax ID"));
        if (!data.num_license_economic)
          missing_fields.push(__("Número de Licencia Económica"));
        if (!data.legal_representative)
          missing_fields.push(__("Representante Legal"));
        if (!data.legal_representative_id)
          missing_fields.push(__("Identificación del Representante Legal"));
        if (!data.municipality) missing_fields.push(__("Municipio(en Direccion Principal)"));

        if (missing_fields.length > 0) {
          frappe.msgprint({
            title: __("Faltan Datos de la Compañía"),
            indicator: "orange",
            message: __(
              'Por favor, complete los siguientes campos en la ficha de la compañía "{0}":<br><b>{1}</b>',
              [frm.doc.company, missing_fields.join("<br>")]
            ),
          });
        }

        frm.set_value("tax_id", data.tax_id);
        frm.set_value("num_license_economic", data.num_license_economic);
        frm.set_value("legal_representative", data.legal_representative);
        frm.set_value(
          "legal_representative_id",
          data.legal_representative_id
        );
        frm.set_value("municipality", data.municipality_name);
        frm.set_value("municipality_id", data.municipality);

        if (data.address_details) {
          frm.set_value("address_line1", data.address_details.address_line1);
          frm.set_value("state", data.address_details.state_name);
          frm.set_value("parish", data.address_details.parish_name);
          frm.set_value("phone", data.address_details.phone || data.phone_no);
          frm.set_value("email_id", data.address_details.email_id || data.email);
          frm.set_value("sector", data.address_details.sector);
        } else {
          clear_address_fields(frm);
          frm.set_value("phone", data.phone_no);
          frm.set_value("email_id", data.email);
        }
      } else {
        clear_all_company_fields(frm);
      }
    } catch (e) {
      frappe.log_error(e);
      clear_all_company_fields(frm);
    }
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
  frm.set_value("branch", "");
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
      method:
        "l10n_ve.l10n_ve.doctype.ve_municipality_tax_declaration.ve_municipality_tax_declaration.get_exchange_rate",
      args: {
        declaration_date: target_date,
        from_currency: from_currency,
      },
      callback: function (r) {
        if (r.message && r.message > 0) {
          frm.set_value("rate", r.message);
          calculate_all_rows_tax(frm);
        } else {
          frm.set_value("rate", 0);
          frappe.msgprint({
            title: __("Tasa de Cambio no Encontrada"),
            indicator: "orange",
            message: __(
              "No se encontró una tasa de cambio ni para fechas posteriores ni anteriores a la fecha (" +
              frappe.datetime.str_to_user(target_date) +
              "). Por favor, configúrela en el doctype de Tasa de Cambio."
            ),
          });
        }
      },
    });
  } else {
    frm.set_value("rate", 0);
  }
}

function get_invoice_activities(frm) {
  const monthMap = {
    Enero: 1,
    Febrero: 2,
    Marzo: 3,
    Abril: 4,
    Mayo: 5,
    Junio: 6,
    Julio: 7,
    Agosto: 8,
    Septiembre: 9,
    Octubre: 10,
    Noviembre: 11,
    Diciembre: 12,
  };

  const month = monthMap[frm.doc.declaration_month];

  const year = parseInt(frm.doc.declaration_year, 10);

  if (month && year && frm.doc.company && frm.doc.municipality_id) {
    frm.set_value("declaration_date", frappe.datetime.nowdate());

    const firstDayObj = new Date(year, month - 1, 1);
    const lastDayObj = new Date(year, month, 0);
    const from_date = frappe.datetime.obj_to_str(firstDayObj);
    const to_date = frappe.datetime.obj_to_str(lastDayObj);

    frappe.dom.freeze(__("Buscando actividades económicas en las facturas..."));
    frappe.call({
      method:
        "l10n_ve.l10n_ve.doctype.ve_municipality_tax_declaration.ve_municipality_tax_declaration.get_activities_from_sales_invoices",
      args: {
        from_date: from_date,
        to_date: to_date,
        company: frm.doc.company,
        municipality: frm.doc.municipality_id,
        branch: frm.doc.branch
      },
      callback: function (r) {
        frappe.dom.unfreeze();
        if (r.message && r.message.length > 0) {
          frm.clear_table("municipality_declaration_data");
          r.message.forEach((activity_data) => {
            let child = frm.add_child("municipality_declaration_data");
            child.code = activity_data.name;
            child.code_name = activity_data.code;
            child.economic_sector = activity_data.sector;
            child.branch = activity_data.branch;
            child.aliquot = activity_data.aliquot;
            child.mt_tcmmv = activity_data.mt_tcmmv;
            child.gross_income = activity_data.taxable_base;
          });
          calculate_all_rows_tax(frm);
          frm.refresh_field("municipality_declaration_data");
          frappe.msgprint(__("Actividades cargadas correctamente."));
        } else {
          frm.clear_table("municipality_declaration_data");
          frm.refresh_field("municipality_declaration_data");
          frappe.msgprint(
            __("No se encontraron actividades para el mes y año seleccionados.")
          );
        }
      },
      error: function (r) {
        frappe.dom.unfreeze();
      }
    });
  } else {
    frappe.msgprint(
      __(
        "Por favor, seleccione Compañía, Municipio, Mes y Año para buscar las actividades."
      )
    );
  }
}

function setup_triggers(frm) {
  if (
    frm.doc.declaration_month &&
    frm.doc.declaration_year &&
    frm.doc.company &&
    frm.doc.municipality_id
  ) {
    get_invoice_activities(frm);
  }
}

function calculate_all_rows_tax(frm) {
  if (
    frm.doc.municipality_declaration_data &&
    frm.doc.municipality_declaration_data.length > 0
  ) {
    let total_calculated_tax = 0;
    frm.doc.municipality_declaration_data.forEach(function (row) {
      if (typeof calculate_municipal_declaration_row_tax === "function") {
        calculate_municipal_declaration_row_tax(frm, row);
        total_calculated_tax += row.calculated_tax || 0;
      }
    });
    frm.set_value("tax_amount", total_calculated_tax);
    frm.set_value("total_pay", total_calculated_tax);
    frm.refresh_field("municipality_declaration_data");
    frm.refresh_field("tax_amount");
    frm.refresh_field("total_pay");
  }
}

async function currency_data_setting(frm) {
  const mt_currency = await frappe.db.get_single_value(
    "Venezuela Account Settings",
    "mt_currency"
  );

  if (mt_currency) {
    await frm.set_value("currency", mt_currency);
  } else if (frm.is_new()) {
    frm.set_value("currency", "");
    frm.set_value("rate", 0);
    frappe.msgprint({
      title: __("Configuración Requerida"),
      indicator: "orange",
      message: __(
        "Por favor, configure la <b>Moneda para Impuestos Municipales</b> en la sección de <a href='/app/venezuela-account-settings'><b>Configuración Contable Venezolana</b></a>."
      ),
    });
  }
}

function add_declaration_upload_button(frm) {
  if (
    frm.doc.docstatus === 1 &&
    !frm.custom_buttons[__("Cargar Datos de Declaración")]
  ) {
    frm.add_custom_button(__("Cargar Datos de Declaración"), function () {
      const dialog = new frappe.ui.Dialog({
        title: __("Cargar Datos de Declaración Municipal"),
        fields: [
          {
            label: __("Número de Declaración"),
            fieldname: "num_declaration",
            fieldtype: "Data",
            reqd: 1,
            default: frm.doc.num_declaration,
          },
          {
            label: __("Adjuntar Declaración"),
            fieldname: "declaration_document",
            fieldtype: "Attach",
            reqd: 1,
            default: frm.doc.declaration_document,
          },
        ],
        primary_action_label: __("Guardar"),
        primary_action: (values) => {
          if (!values.num_declaration || !values.declaration_document) {
            frappe.msgprint({
              title: __("Error de Validación"),
              indicator: "red",
              message: __(
                "Debe ingresar el Número de Declaración y adjuntar el documento."
              ),
            });
            return;
          }
          frappe.call({
            method:
              "l10n_ve.l10n_ve.doctype.ve_municipality_tax_declaration.ve_municipality_tax_declaration.upload_declaration_data",
            args: {
              docname: frm.doc.name,
              num_declaration: values.num_declaration,
              declaration_document: values.declaration_document,
            },
            callback: function (r) {
              frm.reload_doc();
              dialog.hide();
            },
          });
        },
      });
      dialog.show();
    });
  }
}

frappe.ui.form.on("VE Municipality Declaration Data", {
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

  let tax_by_aliquot = ((row.gross_income || 0) * (row.aliquot || 0)) / 100;

  let tax_by_mt = (row.mt_tcmmv || 0) * rate;

  row.calculated_tax = Math.max(tax_by_aliquot, tax_by_mt);
}

function check_branch_required(frm) {
  if (frm.doc.company) {
    frappe.call({
      method: "frappe.client.get_list",
      args: {
        doctype: "VE Branch",
        filters: { "company": frm.doc.company },
        limit: 1
      },
      callback: function (r) {
        let has_branches = (r.message && r.message.length > 0);
        frm.set_df_property('branch', 'reqd', has_branches ? 1 : 0);
        frm.doc.is_branch_required = has_branches;
      }
    });
  }
}
