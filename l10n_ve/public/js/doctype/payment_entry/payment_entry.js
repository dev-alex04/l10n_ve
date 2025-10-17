frappe.ui.form.on("Payment Entry", {
  refresh: function (frm) {
    set_payment_entry_buttons(frm);
  },
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

function set_islr_concept(frm) {
  const islr_invoices = get_islr_invoices(frm);

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
          dialog.hide();
        });
    },
  });

  let table_control = dialog.get_field("islr_concepts");

  // 2. Establece las propiedades para deshabilitar botones
  table_control.df.cannot_add_rows = true;
  table_control.df.cannot_delete_rows = true;

  // 3. Refresca el control para que los cambios se apliquen en la UI
  table_control.refresh();

  dialog.show();
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
      base_amount: reference.outstanding_amount,
      base_amount_reference: reference.outstanding_amount,
    });
  }

  return islr_invoices;
}
