// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("ISLR Withholding Voucher", {
  refresh: function (frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__("Imprimir"), function () {
        const printWindow = window.open("", "_blank");
        if (!printWindow) {
          frappe.msgprint(__("Por favor, deshabilite el bloqueador de ventanas emergentes para este sitio."));
          return;
        }

        frappe.call({
          method:
            "l10n_ve.l10n_ve.report.islr_withholding_voucher_purchase.islr_withholding_voucher_purchase.generate_islr_report",
          args: {
            voucher_name: frm.doc.name,
          },
          callback: function (r) {
            if (r.message) {
              printWindow.document.write(r.message);
              printWindow.document.close();
              setTimeout(function() {
                  printWindow.print();
              }, 100);

              if (printWindow.document.readyState === 'complete') {
                  printWindow.onload();
              }
            } else {
              printWindow.close();
              if (r.exc) {
                frappe.throw(__("Error al generar el comprobante."));
              }
            }
          },
        });
      });
    }
  },

  onload: function (frm) {
    if (frm.doc.__islocal) {
      const company_name = frm.doc.empresa;

      if (company_name) {
        frm
          .call("get_withholding_correlative", {
            company_name: company_name,
            voucher_type: "islr",
          })
          .then((r) => {
            if (r.message) {
              frm.set_value("voucher_number", r.message);
            }
          });
      }
    }
  },

  start_date: function (frm) {
    if (frm.doc.start_date && frm.doc.end_date) {
      validar_fechas(frm, "start_date");
    }

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  end_date: function (frm) {
    if (frm.doc.start_date && frm.doc.end_date) {
      validar_fechas(frm, "end_date");
    }

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  supplier: function (frm) {
    frm.clear_table("islr_withholding_voucher_item");
    frm.add_child("islr_withholding_voucher_item");
    frm.refresh_field("islr_withholding_voucher_item");

    frm.set_value("supplier_address", "");
    frm.refresh_field("supplier_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  empresa: function (frm) {
    frm.clear_table("islr_withholding_voucher_item");
    frm.add_child("islr_withholding_voucher_item");
    frm.refresh_field("islr_withholding_voucher_item");

    frm.set_value("company_address", "");
    frm.refresh_field("company_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },
});

function validar_fechas(frm, campo) {
  try {
    const startDate = new Date(frm.doc.start_date);
    const endDate = new Date(frm.doc.end_date);

    if (endDate < startDate) {
      frm.set_value(campo, null);
      frm.clear_table("islr_withholding_voucher_item");
      frm.add_child("islr_withholding_voucher_item");
      frm.refresh_field("islr_withholding_voucher_item");

      throw new Error(
        "La fecha de fin no puede ser menor que la fecha de inicio."
      );
    }
  } catch (e) {
    frappe.throw(e.message);
  }
}

function load_invoices(frm) {
  if (
    !frm.doc.supplier ||
    !frm.doc.start_date ||
    !frm.doc.end_date ||
    !frm.doc.empresa
  ) {
    return;
  }

  frm.clear_table("islr_withholding_voucher_item");

  frappe.call({
    method:
      "l10n_ve.l10n_ve.doctype.islr_withholding_voucher.islr_withholding_voucher.get_valid_invoices",
    args: {
      supplier: frm.doc.supplier,
      start_date: frm.doc.start_date,
      end_date: frm.doc.end_date,
      company: frm.doc.empresa,
    },
    callback: function (r) {
      frm.doc.totals_total_exempt = 0;
      frm.doc.totals_tax_amount = 0;

      if (r.message && r.message.length > 0) {
        r.message.forEach((invoice) => {
          let new_row = frm.add_child("islr_withholding_voucher_item");
          new_row.purchase_invoice = invoice.purchase_invoice;
          new_row.doc_no = invoice.doc_no;
          new_row.doc_type = invoice.doc_type;
          new_row.bill_control = invoice.bill_control;
          new_row.posting_date = invoice.posting_date;
          new_row.grand_total = invoice.grand_total;
          new_row.payment_entry_name = invoice.payment_entry_name || "";
          new_row.total_exempt = invoice.total_exempt;
          new_row.amount_paid = invoice.grand_total;
          new_row.rate = invoice.rate;
          new_row.subtracting = invoice.subtracting;
          new_row.code = invoice.code;
          new_row.tax_amount = invoice.tax_amount;

          frm.doc.totals_total_exempt += invoice.total_exempt || 0;
          frm.doc.totals_tax_amount += invoice.tax_amount || 0;
        });

        frm.refresh_fields(["totals_total_exempt", "totals_tax_amount"]);

        frm.refresh_fields();
      } else {
        frm.clear_table("islr_withholding_voucher_item");
        frm.add_child("islr_withholding_voucher_item");
        frm.refresh_field("islr_withholding_voucher_item");

        frm.doc.totals_total_exempt = 0;
        frm.doc.totals_tax_amount = 0;
        frm.refresh_fields();

        frappe.show_alert({
          message: __(
            "No se encontraron facturas de compra que cumplan con los criterios."
          ),
          indicator: "orange",
        });
      }
    },
  });
}
