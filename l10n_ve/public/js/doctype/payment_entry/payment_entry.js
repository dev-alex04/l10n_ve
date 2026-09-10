// Modos de pago que NO generan extracto bancario, o sea que no hay nada contra qué
// conciliarlos: decir «Por conciliar» seria anunciar algo que nunca va a ocurrir.
//
// Es la misma lista que `CASH_LIKE_TYPES` en `mint/apis/reconciliation.py`, y tiene que
// seguir siendolo. Antes aca solo estaba `Cash`, y con eso los dos modos de tipo
// `Gangway` que hay en produccion --Biopago y BANCARIBE C2P-- quedaban «Por conciliar»
// PARA SIEMPRE, con cobranza persiguiendo una conciliacion bancaria que no puede
// existir. Medido: 56 pagos emitidos con BANCARIBE C2P.
//
// Se compara por TIPO y no por nombre a proposito: un modo de tipo Cash llamado «Caja»
// se le escapa a cualquier busqueda de texto.
const TIPOS_SIN_EXTRACTO = ["Cash", "Gateway", "Gangway"];

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

    frm.set_query("paid_to", function () {
      frm.events.validate_company(frm);
      return {
        filters: {
          is_group: 0,
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

    frm.events.set_reference_no_required(frm);
  },
  onload: function (frm) {
    const original_set_current_exchange_rate = frm.events.set_current_exchange_rate;
    frm.events.set_current_exchange_rate = function (frm, exchange_rate_field, from_currency, to_currency) {
      if (!from_currency || !to_currency) return;
      if (original_set_current_exchange_rate) {
        return original_set_current_exchange_rate(frm, exchange_rate_field, from_currency, to_currency);
      }
    };

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

    frm.events.set_reference_no_required(frm);
  },

  refresh: function (frm) {
    set_payment_entry_buttons(frm);
    frm.events.set_reference_no_required(frm);
    frm.events.set_branch_description(frm);
    frm.events.toggle_is_batch_payment(frm);

    if (frm.doc.docstatus === 1) {
      frm.events.set_reconciliation_indicator(frm);
    }

    setup_payment_exchange_difference_button(frm);
  },

  mode_of_payment: function (frm) {
    frm.events.set_reference_no_required(frm);
  },

  payment_type: function (frm) {
    frm.events.set_branch_description(frm);
    frm.events.toggle_is_batch_payment(frm);
    set_payment_entry_buttons(frm);
  },

  /**
   * En qué punto de la conciliación está este cobro/pago, en la cabecera.
   *
   * La regla es la misma para cobros y pagos y por eso está escrita una sola vez: antes
   * eran dos ramas casi idénticas, y la de `Pay` se quedó sin caso final. Un pago emitido
   * cuyo estado no fuera exactamente «Conciliación Pendiente» --por ejemplo uno viejo, de
   * antes de que existiera el campo-- no recibía ningún indicador, así que el usuario veía
   * el de Frappe y no sabía si estaba conciliado o no.
   *
   * El efectivo se trata aparte a propósito: no pasa por el banco, así que no hay extracto
   * contra el cual conciliarlo y decir «Por conciliar» sería anunciar algo que nunca va a
   * ocurrir. Cambia sólo la palabra según de qué lado esté el dinero.
   */
  set_reconciliation_indicator: function (frm) {
    const estado = frm.doc.custom_reconciliation_status;

    if (estado === "Conciliado" || frm.doc.clearance_date) {
      frm.page.set_indicator(__("Conciliado"), "green");
      return;
    }

    if (estado === "Revisar") {
      frm.page.set_indicator(__("Revisar"), "orange");
      return;
    }

    if (!frm.doc.mode_of_payment) {
      frm.page.set_indicator(__("Por conciliar"), "orange");
      return;
    }

    // El TIPO del modo de pago, no su nombre. Buscar «efectivo» dentro del nombre deja
    // fuera a un modo de tipo Cash que se llame «Caja», y ese pago se quedaría en «Por
    // conciliar» para siempre: cobranza perseguiría una conciliación bancaria que no
    // puede existir, que es justo lo que este caso viene a evitar. Es el mismo criterio
    // que usa `set_reference_no_required` unas líneas más abajo, y el que tiene el
    // servidor en `CASH_LIKE_TYPES` (payment_reconciliation.py) por si algún día hay que
    // extenderlo a los otros tipos sin extracto.
    frappe.db
      .get_value("Mode of Payment", frm.doc.mode_of_payment, "type")
      .then((r) => {
        if (TIPOS_SIN_EXTRACTO.includes(r.message?.type)) {
          frm.page.set_indicator(
            frm.doc.payment_type === "Pay" ? __("Pagado") : __("Recibido"),
            "green"
          );
        } else {
          frm.page.set_indicator(__("Por conciliar"), "orange");
        }
      });
  },

  toggle_is_batch_payment: function (frm) {
    if (!frm.fields_dict.is_batch_payment) {
      return;
    }

    const es_pago = frm.doc.payment_type === "Pay";
    frm.toggle_display("is_batch_payment", es_pago);

    // Ocultar no es limpiar. Sin este reset alcanza con Pay -> tildar la casilla ->
    // volver a Receive para que el cobro quede marcado como lote con el campo invisible,
    // y entonces «Intentar conciliar» desaparece de un cobro legítimo. El lote es una
    // figura de los pagos a proveedor: en un cobro no significa nada.
    if (!es_pago && frm.doc.is_batch_payment) {
      frm.set_value("is_batch_payment", 0);
    }
  },

  /**
   * Aclara qué significa la sucursal del cobro/pago según el tipo de movimiento.
   *
   * A diferencia de las facturas —donde el verbo es fijo (vende / compra)—, aquí
   * depende de payment_type: en un cobro (Receive) la sucursal COBRA y en un pago
   * (Pay) PAGA. El texto del custom field dice "cobra o paga" y cubre el caso sin
   * tipo definido todavía (y las vistas que no ejecutan este JS).
   */
  set_branch_description: function (frm) {
    if (!frm.get_field("branch")) return;

    const descripciones = {
      Receive: "Sucursal que cobra",
      Pay: "Sucursal que paga",
    };

    frm.set_df_property(
      "branch",
      "description",
      descripciones[frm.doc.payment_type] || "Sucursal que cobra o paga",
    );
  },

  set_reference_no_required: function (frm) {
    if (!frm.doc.mode_of_payment) {
      frm.set_df_property("reference_no", "reqd", false);
      return;
    }

    frappe.db
      .get_value("Mode of Payment", frm.doc.mode_of_payment, "type")
      .then((r) => {
        const mop_type = r.message?.type;
        const is_required = mop_type !== "Cash";
        frm.set_df_property("reference_no", "reqd", is_required);
      });
  },

  paid_on_currency: function (frm) {
    set_custom_exchange_rate(frm);
  },

  posting_date: function (frm) {
    if (frm.doc.posting_date) {
      set_custom_exchange_rate(frm);
    }
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

  paid_from_account_currency: async function (frm) {
    if (!frm.doc.paid_from_account_currency || !frm.doc.company) return;

    // default_company_currency se asegura vía ensure_igtf_context (antes se leía
    // con frappe.get_doc síncrono, que podía dar undefined si la compañía no
    // estaba en caché). Una sola ruta para la tasa: set_current_exchange_rate.
    await ensure_igtf_context(frm);
    const company_currency = frm.doc.default_company_currency;

    if (frm.doc.paid_from_account_currency == company_currency) {
      frm.set_value("source_exchange_rate", 1);
    } else if (frm.doc.paid_from) {
      await set_current_exchange_rate(
        frm,
        "source_exchange_rate",
        frm.doc.paid_from_account_currency,
        company_currency
      );
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
  frm.remove_custom_button(__("Agregar concepto de ISLR"));
  frm.remove_custom_button(__("Intentar conciliar"));

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

  // Cobro en borrador: intentar conciliar con su depósito bancario y aprobar.
  //
  // `is_batch_payment` se comprueba porque un cobro SÍ puede acabar marcado como lote:
  // basta pasar el documento por `Pay`, tildar la casilla y volver a `Receive` --ocultar
  // un campo no limpia su valor--. `toggle_is_batch_payment` lo resetea justamente para
  // eso, y esta condición es la segunda red, por si el flag llega por API o por una carga
  // de datos. Si ocurre, conciliarlo por acá se saltaría el módulo de lotes, que es quien
  // lleva la cuenta de cuánto del movimiento queda por asignar.
  if (
    frm.doc.docstatus == 0 &&
    frm.doc.payment_type === "Receive" &&
    frm.doc.reference_no &&
    !frm.doc.is_batch_payment &&
    !frm.is_new()
  ) {
    frm.add_custom_button(__("Intentar conciliar"), async function () {
      if (frm.is_dirty()) {
        await frm.save();
      }
      frappe.call({
        method:
          "l10n_ve.overrides.payment_reconciliation.reconcile_and_approve",
        args: { payment_entry: frm.doc.name },
        freeze: true,
        freeze_message: __("Conciliando con el depósito bancario..."),
        callback: function (r) {
          const msg = r.message || {};
          if (msg.reconciled) {
            frappe.show_alert({ message: msg.message, indicator: "green" });
          } else if (msg.review) {
            frappe.msgprint({
              title: __("Revisar"),
              message:
                msg.message || __("El cobro quedó marcado para revisión."),
              indicator: "red",
            });
          } else {
            frappe.msgprint({
              title: __("Sin depósito"),
              message:
                msg.message ||
                __("Aún no se encontró el depósito de esta referencia."),
              indicator: "orange",
            });
          }
          frm.reload_doc();
        },
      });
    });
  }
}

// Asegura que estén cargados los datos que el cálculo de IGTF / tasa necesita:
// la moneda de la compañía y, en pagos en divisa, la tasa y la cuenta de IGTF.
// Antes esto se cargaba DENTRO de set_igtf, después de intentar usar igtf_rate,
// por eso el IGTF salía en 0 en la primera pasada.
async function ensure_igtf_context(frm) {
  if (!frm.doc.default_company_currency && frm.doc.company) {
    const r = await frappe.db.get_value(
      "Company",
      frm.doc.company,
      "default_currency"
    );
    if (r?.message?.default_currency) {
      frm.doc.default_company_currency = r.message.default_currency;
    }
  }

  const is_foreign =
    frm.doc.default_company_currency &&
    frm.doc.paid_on_currency &&
    frm.doc.default_company_currency != frm.doc.paid_on_currency;

  if (!is_foreign) return;

  if (!frm.doc.igtf_rate) {
    const rate = await frappe.db.get_single_value(
      "Venezuela Account Settings",
      "igtf_rate"
    );
    frm.doc.igtf_rate = flt(rate);
  }
  if (!frm.doc.igtf_account) {
    const fld =
      frm.doc.payment_type == "Pay"
        ? "purchase_igtf_account"
        : "sales_igtf_account";
    const r = await frappe.db.get_value("Company", frm.doc.company, fld);
    if (r?.message) frm.doc.igtf_account = r.message[fld];
  }
}

async function compute_paid_amount(frm) {
  await ensure_igtf_context(frm);

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
  await ensure_igtf_context(frm);

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
      outstanding_amount / (flt(frm.doc.exchange_rate) || 1)
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

// ─────────────────────────────────────────────────────────────────────────────
// Diferencial Cambiario (Pérdida) en Pago a Proveedor
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Muestra el botón "Generar Diferencial Cambiario" (Pérdida) en el menú Acciones.
 *
 * Condiciones estrictas para que aparezca:
 *   1. Documento enviado (docstatus === 1).
 *   2. Tipo de pago: exclusivamente Pay (NO Receive — nunca en cobros a clientes).
 *   3. Tipo de tercero: exclusivamente Supplier.
 *   4. Monto sin asignar positivo (unallocated_amount > 0).
 *
 * Al confirmar, llama al backend para crear el Journal Entry y cruzarlo
 * automáticamente con el pago, dejando unallocated_amount en 0.
 *
 * @param {object} frm - Instancia del formulario Payment Entry
 */
function setup_payment_exchange_difference_button(frm) {
  if (
    frm.doc.docstatus === 1 &&
    frm.doc.payment_type === "Pay" &&
    frm.doc.party_type === "Supplier" &&
    flt(frm.doc.unallocated_amount) > 0
  ) {
    frm.add_custom_button(
      __("Generar Diferencial Cambiario"),
      function () {
        const currency =
          frm.doc.paid_to_account_currency ||
          frm.doc.party_account_currency ||
          frm.doc.currency;
        const monto = format_currency(flt(frm.doc.unallocated_amount), currency);

        frappe.confirm(
          `¿Desea registrar el monto sin asignar (<b>Pérdida</b>) por <b>${monto}</b>?<br><br>` +
            `Se creará y enviará un Asiento Contable que extinguirá el remanente del proveedor.`,
          () => {
            frappe.call({
              method:
                "l10n_ve.overrides.payment_entry.create_payment_exchange_difference_entry",
              args: { docname: frm.doc.name },
              freeze: true,
              freeze_message: __("Registrando diferencial cambiario (Pérdida)..."),
              callback: function (r) {
                if (r.message && r.message.status === "success") {
                  frappe.show_alert({
                    message: __(
                      `Diferencial cambiario registrado: ${r.message.journal_entry}`
                    ),
                    indicator: "green",
                  });
                  frm.reload_doc();
                }
              },
            });
          }
        );
      }
    );
  }
}


