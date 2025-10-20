frappe.ui.form.on("Payment Entry", {
  setup: function (frm) {
    frm.events.get_current_tax_amount = function (frm, tax) {
      return tax.tax_amount;
    };
  },
  onload: function (frm) {
    reorganize_payment_entry_fields(frm);
  },

  refresh: function (frm) {
    set_payment_entry_buttons(frm);
  },

  paid_on_currency: function (frm) {
    set_custom_exchange_rate(frm);
  },
  paid_currency_amount: function (frm) {},

  party_type: function (frm) {
    set_payment_entry_buttons(frm);
  },
  party: function (frm) {
    set_payment_entry_buttons(frm);
  },
  company: function (frm) {
    set_payment_entry_buttons(frm);
  },
});

function set_payment_entry_buttons(frm) {
  if (
    frm.doc.docstatus == 0 &&
    frm.doc.party_type &&
    frm.doc.party &&
    frm.doc.company &&
    ["Supplier", "Customer"].includes(frm.doc.party_type)
  ) {
    frm.add_custom_button(__("Agregar concepto de ISLR"), function () {
      set_islr_concept(frm);
    });
  }
}

/**
 * @param {object} frm - Instancia del formulario actual
 * @returns {null}
 */

function reorganize_payment_entry_fields(frm) {
  let paid_amount = frm.get_field("paid_amount").$wrapper;
  let exchange_rate = frm.get_field("exchange_rate").$wrapper;
  let received_amount = frm.get_field("received_amount").$wrapper;

  paid_amount.insertAfter(received_amount);
  exchange_rate.insertAfter(paid_amount);

  if (frm.doc.exchange_rate) {
    frm.set_df_property("exchange_rate", "hidden", false);
  }
}

async function set_custom_exchange_rate(frm) {
  if (!frm.doc.default_company_currency || !frm.doc.paid_on_currency) {
    return;
  }

  // Obtiene el monto pendiente total de todas las facturas
  const outstanding_amount = (frm.doc.references || []).reduce(
    (total, ref) => total + flt(ref.outstanding_amount),
    0
  );

  if (frm.doc.default_company_currency != frm.doc.paid_on_currency) {
    await set_current_exchange_rate(
      frm,
      "exchange_rate",
      frm.doc.paid_on_currency,
      frm.doc.default_company_currency
    );

    const paid_currency_amount = outstanding_amount / frm.doc.exchange_rate;

    frm.set_value("paid_currency_amount", paid_currency_amount);

    frm.set_df_property("paid_currency_amount", "description", "");
    frm.set_df_property("exchange_rate", "hidden", false);

    set_igtf(frm);
  } else {
    frm.set_value("paid_currency_amount", outstanding_amount);
    frm.set_df_property("exchange_rate", "hidden", true);
    frm.set_value("exchange_rate", 1);

    set_igtf(frm);
  }
}

async function set_current_exchange_rate(
  frm,
  exchange_rate_field,
  from_currency,
  to_currency
) {
  try {
    const r = await frappe.call({
      method: "erpnext.setup.utils.get_exchange_rate",
      args: {
        transaction_date: frm.doc.posting_date,
        from_currency: from_currency,
        to_currency: to_currency,
      },
    });
    if (r && r.message) {
      const exchange_rate = flt(
        r.message,
        frm.get_field(exchange_rate_field).get_precision()
      );
      frm.set_value(exchange_rate_field, exchange_rate);
    }
  } catch (error) {
    console.error("Error al obtener la tasa de cambio:", error);
    frappe.msgprint(__("No se pudo obtener la tasa de cambio."));
  }
}

// Impuestos

async function set_igtf(frm) {
  if (!frm.doc.default_company_currency || !frm.doc.paid_on_currency) {
    return;
  }

  if (!frm.doc.paid_amount) {
    return;
  }

  // Si es la misma moneda, el IGTF queda en cero
  if (frm.doc.default_company_currency == frm.doc.paid_on_currency) {
    for (let tax of frm.doc.taxes || []) {
      if (tax.charge_type == "IGTF") {
        tax.tax_amount = 0;
        frm.refresh_field("taxes");

        if (frm.cscript.calculate_taxes_and_totals) {
          frm.cscript.calculate_taxes_and_totals();
        }
      }
    }
    return;
  }

  const igtf_amount = (frm.doc.paid_amount * frm.doc.igtf_rate) / 100;

  // En caso de que exista el IGTF en los impuestos:
  for (let tax of frm.doc.taxes || []) {
    if (tax.charge_type == "IGTF") {
      tax.tax_amount = igtf_amount;
      frm.refresh_field("taxes");
      if (frm.cscript.calculate_taxes_and_totals) {
        frm.cscript.calculate_taxes_and_totals();
      }
      return;
    }
  }

  // Si el codigo llega acá, es porque no existe y hay que agregar
  // el IGTF a la tabla de impuestos
  frm.add_child("taxes", {
    charge_type: "IGTF",
    rate: frm.doc.igtf_rate,
    tax_amount: igtf_amount,
    add_deduct_tax: "Add",
    account_head: frm.doc.igtf_account,
    description: "IGTF",
  });

  frm.refresh_field("taxes");

  if (frm.cscript.calculate_taxes_and_totals) {
    frm.cscript.calculate_taxes_and_totals();
  }
}

function set_islr_concept(frm) {
  const islr_invoices = get_islr_invoices(frm);
  const party_type_for_person =
    frm.doc.party_type === "Supplier" ? "Supplier" : "Company";
  const party_for_person =
    frm.doc.party_type === "Supplier" ? frm.doc.party : frm.doc.company;

  frappe.db
    .get_value(party_type_for_person, party_for_person, "type_of_person")
    .then((r) => {
      const type_of_person = r.message.type_of_person;

      let dialog = new frappe.ui.Dialog({
        title: "Agregar concepto de ISLR",
        size: "extra-large",
        fields: [
          {
            data: islr_invoices,
            fieldtype: "Table",
            fieldname: "islr_concepts",
            fields: [
              {
                fieldtype: "Data",
                fieldname: "bill_no",
                in_list_view: true,
                label: "Factura",
                reqd: true,
              },
              {
                in_list_view: 1,
                fieldtype: "Link",
                fieldname: "concept_islr",
                label: "Concepto",
                options: "Tabulator ISLR",
                reqd: 1,
                get_query: function () {
                  return {
                    filters: {
                      types_of_person: type_of_person,
                    },
                  };
                },
              },
              {
                fieldtype: "Float",
                fieldname: "base_amount",
                in_list_view: true,
                label: "Monto Base",
                reqd: true,
              },
              {
                fieldtype: "Float",
                fieldname: "base_amount_reference",
                in_list_view: true,
                label: "Monto Pendiente",
                read_only: true,
              },
              {
                fieldtype: "Data",
                fieldname: "reference_name",
                in_list_view: false,
                label: "Reference Name",
                hidden: true,
                read_only: true,
              },
            ],
          },
        ],
        primary_action_label: "Cargar conceptos",
        primary_action(values) {
          let error_messages = [];

          for (const concept of values.islr_concepts) {
            if (concept.base_amount > concept.base_amount_reference) {
              error_messages.push(
                `Línea ${concept.idx}: El monto base ${concept.base_amount} no puede ser mayor a ${concept.base_amount_reference}`
              );
            }
          }

          if (error_messages.length > 0) {
            frappe.msgprint({
              title: __("Cargando conceptos"),
              message: error_messages.join("\n"),
              indicator: "red",
            });
            return;
          }

          dialog.hide();
          frappe.dom.freeze(`Cargando conceptos`);

          frm
            .call("set_islr_concept", {
              islr_concepts: values.islr_concepts,
            })
            .then((r) => {
              frappe.dom.unfreeze();
              frappe.show_alert({
                message: "Concepto cargado satisfactoriamente",
                indicator: "green",
              });
              if (frm.is_new()) {
                frappe.set_route("Form", frm.doc.doctype, r.message);
              }
            })
            .catch((error) => {
              frappe.dom.unfreeze();
              console.log(error);
              frappe.msgprint({
                title: __("Error"),
                message:
                  "Ocurrió un error al cargar al concepto, intente nuevamente o comuníquese con el administrador del sistema",
                indicator: "red",
              });
            });
        },
      });

      let table_control = dialog.get_field("islr_concepts");
      table_control.df.cannot_add_rows = true;
      table_control.df.cannot_delete_rows = true;
      table_control.refresh();

      dialog.show();
    });
}

/**
 * Devuelve un array con la factura y el monto de la factura
 * @param {object} frm - Instancia del formulario actual
 * @returns {array}
 */

function get_islr_invoices(frm) {
  let islr_invoices = [];

  for (const reference of frm.doc.references || []) {
    islr_invoices.push({
      bill_no: reference.bill_no,
      reference_name: reference.reference_name,
      base_amount: reference.outstanding_amount,
      base_amount_reference: reference.outstanding_amount,
    });
  }

  return islr_invoices;
}
