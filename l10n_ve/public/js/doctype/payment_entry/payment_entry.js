frappe.ui.form.on("Payment Entry", {
  setup: function (frm) {
    frm.events.get_current_tax_amount = function (frm, tax) {
      return tax.tax_amount;
    };

    frm.set_query("branch", function () {
      return {
        filters: {
          company: frm.doc.company,
        },
      };
    });

    frm.set_query("mode_of_payment", function () {
      if (frm.doc.branch) {
        return {
          query: "l10n_ve.overrides.payment_entry.get_branch_payment_modes",
          filters: {
            branch: frm.doc.branch,
          },
        };
      }
    });

    if (
      erpnext.accounts &&
      erpnext.accounts.pos &&
      !erpnext.accounts.pos.is_branch_override_applied
    ) {
      let original_get_payment_mode_account =
        erpnext.accounts.pos.get_payment_mode_account;

      erpnext.accounts.pos.get_payment_mode_account = function (
        frm,
        mode_of_payment,
        callback
      ) {
        if (frm.doc.branch) {
          frappe.call({
            method:
              "l10n_ve.overrides.payment_entry.get_branch_payment_mode_account",
            args: {
              branch: frm.doc.branch,
              mode_of_payment: mode_of_payment,
            },
            callback: function (r) {
              if (r.message) {
                callback(r.message);
              } else {
                original_get_payment_mode_account(
                  frm,
                  mode_of_payment,
                  callback
                );
              }
            },
          });
        } else {
          original_get_payment_mode_account(frm, mode_of_payment, callback);
        }
      };

      erpnext.accounts.pos.is_branch_override_applied = true;
    }
  },
  onload: function (frm) {
    reorganize_payment_entry_fields(frm);

    realtime_numeric_validation(frm, "reference_no");

    if (frm.fields_dict.get_outstanding_invoices) {
      frm.fields_dict.get_outstanding_invoices.$input
        .off("click")
        .on("click", function () {
          frm.events.handle_get_outstanding_invoices(frm);
        });
    }

    if (frm.is_new()) {
      set_custom_exchange_rate(frm);
    }

    realtime_numeric_validation(frm, "reference_no");
  },

  refresh: function (frm) {
    set_payment_entry_buttons(frm);
  },

  paid_on_currency: function (frm) {
    set_custom_exchange_rate(frm);
  },

  paid_currency_amount: function (frm) {
    compute_paid_amount(frm);
  },

  party_type: function (frm) {
    set_payment_entry_buttons(frm);
  },
  party: function (frm) {
    set_payment_entry_buttons(frm);
    frm.toggle_display("get_outstanding_invoices", !!frm.doc.party);
  },
  company: function (frm) {
    set_payment_entry_buttons(frm);
  },

  before_submit: function (frm) {
    confirm_overpayment_on_submit(frm);
  },

  set_difference_amount: function (frm) {
    var difference_amount = 0;
    var base_unallocated_amount =
      flt(frm.doc.unallocated_amount) *
      (frm.doc.payment_type == "Receive"
        ? frm.doc.source_exchange_rate
        : frm.doc.target_exchange_rate);

    var base_party_amount =
      flt(frm.doc.base_total_allocated_amount) + base_unallocated_amount;

    const included_taxes = get_included_taxes(frm);

    if (frm.doc.payment_type == "Receive") {
      difference_amount =
        base_party_amount - flt(frm.doc.base_received_amount) + included_taxes;
    } else if (frm.doc.payment_type == "Pay") {
      difference_amount =
        flt(frm.doc.base_paid_amount) - base_party_amount - included_taxes;
    } else {
      difference_amount =
        flt(frm.doc.base_paid_amount) -
        flt(frm.doc.base_received_amount) -
        included_taxes;
    }

    var total_deductions = frappe.utils.sum(
      $.map(frm.doc.deductions || [], function (d) {
        return flt(d.amount);
      })
    );

    frm.set_value("difference_amount", difference_amount - total_deductions);
    frm.events.hide_unhide_fields(frm);
  },

  set_current_exchange_rate: function (
    frm,
    exchange_rate_field,
    from_currency,
    to_currency
  ) {
    frappe.call({
      method: "erpnext.setup.utils.get_exchange_rate",
      args: {
        transaction_date: frm.doc.posting_date,
        from_currency: from_currency || "VEF",
        to_currency: to_currency,
      },
      callback: function (r, rt) {
        const ex_rate = flt(
          r.message,
          frm.get_field(exchange_rate_field).get_precision()
        );
        frm.set_value(exchange_rate_field, ex_rate);
      },
    });
  },

  paid_from_account_currency: function (frm) {
    if (!frm.doc.paid_from_account_currency || !frm.doc.company) return;
    let company_currency = frappe.get_doc(
      ":Company",
      frm.doc.company
    ).default_currency;

    if (frm.doc.paid_from_account_currency == company_currency) {
      frm.set_value("source_exchange_rate", 1);
    } else if (frm.doc.paid_from) {
      if (["Internal Transfer", "Pay"].includes(frm.doc.payment_type)) {
        let company_currency = frappe.get_doc(
          ":Company",
          frm.doc.company
        )?.default_currency;
        frappe.call({
          method: "erpnext.setup.utils.get_exchange_rate",
          args: {
            from_currency: frm.doc.paid_from_account_currency || "VEF",
            to_currency: company_currency,
            transaction_date: frm.doc.posting_date,
          },
          callback: function (r, rt) {
            frm.set_value("source_exchange_rate", r.message);
          },
        });
      } else {
        frm.events.set_current_exchange_rate(
          frm,
          "source_exchange_rate",
          frm.doc.paid_from_account_currency,
          company_currency
        );
      }
    }
  },

  handle_get_outstanding_invoices: function (frm) {
    if (!frm.doc.mode_of_payment) {
      frappe.throw(
        __(
          'Debe seleccionar un "Modo de pago" para obtener las facturas pendientes de pago.'
        )
      );
      return;
    }

    frm.events.get_outstanding_invoices_or_orders(frm, true, false);
  },

  // handle_get_outstanding_invoices: function (frm) {
  //   if (!frm.doc.mode_of_payment) {
  //     frappe.throw(
  //       __(
  //         'Debe seleccionar un "Modo de pago" para obtener las facturas pendientes de pago.'
  //       )
  //     );
  //     return;
  //   }

  //   let allocate_amount = frm.doc.payment_type === "Receive" ? frm.doc.paid_amount : frm.doc.received_amount;

  //   frm.events.get_outstanding_documents(
  //     frm,
  //     { allocate_payment_amount: allocate_amount },
  //     true,
  //     false
  //   );
  // },

  get_outstanding_documents: function (
    frm,
    filters,
    get_outstanding_invoices,
    get_orders_to_be_billed
  ) {
    frm.doc.references = [];

    if (!frm.doc.party) {
      return;
    }

    frm.events.check_mandatory_to_fetch(frm);

    var args = {
      posting_date: frm.doc.posting_date,
      company: frm.doc.company,
      party_type: frm.doc.party_type,
      payment_type: frm.doc.payment_type,
      party: frm.doc.party,
      party_account:
        frm.doc.payment_type == "Receive" ? frm.doc.paid_from : frm.doc.paid_to,
      cost_center: frm.doc.cost_center,
    };

    for (let key in filters) {
      args[key] = filters[key];
    }

    if (get_outstanding_invoices) {
      args["get_outstanding_invoices"] = true;
    } else if (get_orders_to_be_billed) {
      args["get_orders_to_be_billed"] = true;
    }

    if (frm.doc.book_advance_payments_in_separate_party_account) {
      args["book_advance_payments_in_separate_party_account"] = true;
    }

    frappe.flags.allocate_payment_amount = filters["allocate_payment_amount"];

    return frappe.call({
      method:
        "erpnext.accounts.doctype.payment_entry.payment_entry.get_outstanding_reference_documents",
      args: {
        args: args,
      },
      callback: function (r) {
        let total_outstanding_in_currency = 0;

        if (r.message) {
          var total_positive_outstanding = 0;
          var total_negative_outstanding = 0;
          $.each(r.message, function (i, d) {
            var c = frm.add_child("references");
            c.reference_doctype = d.voucher_type;
            c.reference_name = d.voucher_no;
            c.due_date = d.due_date;
            c.total_amount = d.invoice_amount;
            c.outstanding_amount = d.outstanding_amount;
            c.bill_no = d.bill_no;
            c.payment_term = d.payment_term;
            c.payment_term_outstanding = d.payment_term_outstanding;
            c.allocated_amount = d.allocated_amount;
            c.account = d.account;

            if (d.base_total) {
              c.base_total = d.base_total;
            }

            if (!in_list(frm.events.get_order_doctypes(frm), d.voucher_type)) {
              if (flt(d.outstanding_amount) > 0) {
                total_positive_outstanding += flt(d.outstanding_amount);
                total_outstanding_in_currency += flt(d.outstanding_amount);
              } else {
                total_negative_outstanding += Math.abs(
                  flt(d.outstanding_amount)
                );
              }
            }
          });
        }

        frm.set_value("paid_currency_amount", total_outstanding_in_currency);

        frm.events.allocate_party_amount_against_ref_docs(
          frm,
          frm.doc.payment_type == "Receive"
            ? frm.doc.paid_amount
            : frm.doc.received_amount,
          false
        );

        frm.refresh_field("references");
      },
    });
  },

  calculate_total_allocated: function (frm) {
    const total_allocated = frm.doc.references.reduce((total, ref) => {
      return total + flt(ref.allocated_amount);
    }, 0);

    frm.set_value("paid_currency_amount", total_allocated);
    frm.refresh_fields();
  },
});

frappe.ui.form.on("Payment Entry Reference", {
  references_remove: function (frm, cdt, cdn) {
    frm.events.calculate_total_allocated(frm);
  },
});

function get_included_taxes(frm) {
  let included_taxes = 0;
  for (const tax of frm.doc.taxes) {
    if (!tax.included_in_paid_amount) continue;

    if (tax.add_deduct_tax == "Add") {
      included_taxes += tax.base_tax_amount;
    } else {
      included_taxes -= tax.base_tax_amount;
    }
  }
  return included_taxes;
}

function set_payment_entry_buttons(frm) {
  if (
    frm.doc.docstatus == 0 &&
    frm.doc.party_type &&
    frm.doc.party &&
    frm.doc.company &&
    !frm.is_new() &&
    ["Supplier", "Customer"].includes(frm.doc.party_type)
  ) {
    frm.add_custom_button(__("Agregar concepto de ISLR"), function () {
      set_islr_concept(frm);
    });
  }
}

async function compute_paid_amount(frm) {
  frm.set_value(
    "paid_amount",
    flt(frm.doc.paid_currency_amount) * flt(frm.doc.exchange_rate)
  );

  if (
    frm.doc.igtf_rate > 0 &&
    frm.doc.paid_on_currency != frm.doc.default_company_currency
  ) {
    const igtf_amount =
      (flt(frm.doc.paid_currency_amount) * flt(frm.doc.igtf_rate)) / 100;
    const total_with_igtf = flt(frm.doc.paid_currency_amount) + igtf_amount;

    if (flt(frm.doc.igtf_amount) !== flt(igtf_amount)) {
      frm.set_value("igtf_amount", igtf_amount);
    }

    if (flt(frm.doc.total_with_igtf) !== flt(total_with_igtf)) {
      frm.set_value("total_with_igtf", total_with_igtf);
    }
  }

  await set_igtf(frm);
}

/**
 * @param {object} frm - Instancia del formulario actual
 * @returns {null}
 */

function reorganize_payment_entry_fields(frm) {
  let paid_to = frm.get_field("paid_to").$wrapper;
  let party_field = frm.get_field("party").$wrapper;
  let paid_from = frm.get_field("paid_from").$wrapper;
  let paid_amount = frm.get_field("paid_amount").$wrapper;
  let reference_no = frm.get_field("reference_no").$wrapper;
  let exchange_rate = frm.get_field("exchange_rate").$wrapper;
  let reference_date = frm.get_field("reference_date").$wrapper;
  let received_amount = frm.get_field("received_amount").$wrapper;

  let get_outstanding_invoices_button = frm.get_field(
    "get_outstanding_invoices"
  ).$wrapper;

  paid_amount.insertAfter(received_amount);
  exchange_rate.insertAfter(paid_amount);
  reference_no.insertAfter(paid_from);
  reference_date.insertAfter(paid_to);
  get_outstanding_invoices_button.insertAfter(party_field);

  frm.toggle_display("get_outstanding_invoices", !!frm.doc.party);

  if (frm.doc.exchange_rate) {
    frm.set_df_property("exchange_rate", "hidden", false);
  }
}

async function set_custom_exchange_rate(frm) {
  if (!frm.doc.default_company_currency || !frm.doc.paid_on_currency) {
    return;
  }

  const total_withholdings = get_total_withholdings_base(frm);

  let outstanding_amount =
    (frm.doc.references || []).reduce(
      (total, ref) => total + flt(ref.outstanding_amount),
      0
    ) - total_withholdings;

  if (frm.doc.default_company_currency != frm.doc.paid_on_currency) {
    await set_current_exchange_rate(
      frm,
      "exchange_rate",
      frm.doc.paid_on_currency,
      frm.doc.default_company_currency
    );

    const paid_currency_amount = flt(
      outstanding_amount / frm.doc.exchange_rate
    );

    const igtf_amount = (paid_currency_amount * frm.doc.igtf_rate) / 100;
    const total_with_igtf = paid_currency_amount + igtf_amount;

    frm.set_df_property("exchange_rate", "hidden", false);
    frm.set_df_property("igtf_amount", "hidden", false);
    frm.set_df_property("total_with_igtf", "hidden", false);

    if (flt(frm.doc.paid_currency_amount) !== flt(paid_currency_amount)) {
      frm.set_value("paid_currency_amount", paid_currency_amount);
      frm.set_value("igtf_amount", igtf_amount);
      frm.set_value("total_with_igtf", total_with_igtf);
    }

    await compute_paid_amount(frm);
  } else {
    frm.set_value("igtf_amount", 0);
    frm.set_value("total_with_igtf", 0);
    frm.set_value("exchange_rate", 1);
    if (flt(frm.doc.paid_currency_amount) !== flt(outstanding_amount)) {
      frm.set_value("paid_currency_amount", flt(outstanding_amount));
    }
    await compute_paid_amount(frm);
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
    frm.set_df_property("exchange_rate", "hidden", true);
    frm.set_df_property("igtf_amount", "hidden", true);
    frm.set_df_property("total_with_igtf", "hidden", true);
    return;
  }

  if (!frm.doc.igtf_account || !frm.doc.igtf_rate) {
    const igtf_field =
      frm.doc.payment_type == "Pay"
        ? "purchase_igtf_account"
        : "sales_igtf_account";

    await frappe.db
      .get_value("Company", frm.doc.company, igtf_field)
      .then((r) => {
        frm.set_value("igtf_account", r.message[igtf_field]);
      });

    await frappe.db
      .get_single_value("Venezuela Account Settings", "igtf_rate")
      .then((igtf_rate) => {
        frm.set_value("igtf_rate", igtf_rate);
      });
  }

  const igtf_amount = frm.doc.igtf_amount * frm.doc.exchange_rate;

  // En caso de que exista el IGTF en los impuestos:
  for (let tax of frm.doc.taxes || []) {
    if (tax.charge_type == "IGTF") {
      tax.tax_amount = igtf_amount;
      tax.rate = frm.doc.igtf_rate;
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
    description: "IGTF",
    add_deduct_tax: "Add",
    rate: frm.doc.igtf_rate,
    tax_amount: igtf_amount,
    account_head: frm.doc.igtf_account,
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

              if (frm.is_new()) {
                frappe.set_route("Form", frm.doc.doctype, r.message);
              } else {
                frm.reload_doc().then(() => {
                  set_custom_exchange_rate(frm).then(() => {
                    frappe.show_alert({
                      message: "Concepto cargado y recalculado",
                      indicator: "green",
                    });
                    frm.save();
                  });
                });
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
      base_amount: reference.base_total,
      base_amount_reference: reference.base_total,
    });
  }

  return islr_invoices;
}

function confirm_overpayment_on_submit(frm) {
  // Si la bandera `is_submitting` está activa, permite el envío sin confirmación.
  if (frm.is_submitting) {
    frm.is_submitting = false; // Resetea la bandera para futuros envíos.
    return;
  }

  if (frm.doc.payment_type !== "Pay" || flt(frm.doc.unallocated_amount) <= 0) {
    return;
  }
  // Si es un pago con monto sin asignar, muestra la confirmación.
  frappe.validated = false;

  const unallocated_amount_formatted = frappe.format(
    frm.doc.unallocated_amount,
    {
      fieldtype: "Currency",
      currency:
        frm.doc.paid_from_account_currency || frm.doc.paid_to_account_currency,
    }
  );

  frappe.confirm(
    `Está a punto de realizar un pago que excede el monto de la factura
      por: <b>${unallocated_amount_formatted}</b>. ¿Desea continuar?`,
    () => {
      // Si el usuario confirma, activa la bandera y vuelve a enviar.
      frm.is_submitting = true;
      frm.save("Submit");
    },
    () => {}
  );
}

/**
 * Suma el monto base de todos los impuestos que son retenciones (Deduct)
 * y que no están marcados como "incluidos en el monto pagado".
 * @param {object} frm - Instancia del formulario actual
 * @returns {float} - Total de retenciones
 */
function get_total_withholdings_base(frm) {
  let withholding_amount = 0;
  for (const tax of frm.doc.taxes || []) {
    // Solo nos interesan las retenciones (Deduct)
    if (tax.add_deduct_tax == "Deduct" && !tax.included_in_paid_amount) {
      // Usamos base_tax_amount para cuadrar con los otros campos base
      withholding_amount += flt(tax.base_tax_amount);
    }
  }
  return withholding_amount;
}
