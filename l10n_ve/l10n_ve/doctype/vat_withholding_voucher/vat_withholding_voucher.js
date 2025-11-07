// // Copyright (c) 2025, DominaERP and contributors
// // For license information, please see license.txt

frappe.ui.form.on("VAT Withholding Voucher", {
  refresh: function (frm) {
    if (!frm.is_new()) {
      frm.add_custom_button(__("Imprimir"), function () {
        frappe.call({
          method:
            "l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase.generate_vat_report",
          args: {
            voucher_name: frm.doc.name,
          },
          callback: function (r) {
            if (r.message) {
              var w = window.open("about:blank");
              w.document.write(r.message);
              w.document.close();
              w.print();
            }
          },
        });
      });

      const fields = ["start_date", "end_date", "empresa", "supplier", "fiscal_period", "issue_date", "vat_withholding_voucher_item"];
      fields_read_only(frm, fields);
    }
  },

  onload: function (frm) {
    if (frm.doc.__islocal) {
      const company_name = frm.doc.empresa;
      const today = new Date();

      if (company_name) {
        frm
          .call("get_withholding_correlative", {
            company_name: company_name,
            voucher_type: "vat",
          })
          .then((r) => {
            if (r.message) {
              const { voucher_number, year, month } = r.message;
              frm.set_value("voucher_number", voucher_number);
              frm.set_value("fiscal_period", `${month}/${year}`);
              frm.set_value("issue_date", today);
              frm.set_value("delivery_date", today);
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
    frm.clear_table("vat_withholding_voucher_item");
    frm.add_child("vat_withholding_voucher_item");
    frm.refresh_field("vat_withholding_voucher_item");

    frm.set_value("supplier_address", "");
    frm.refresh_field("supplier_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },

  empresa: function (frm) {
    frm.clear_table("vat_withholding_voucher_item");
    frm.add_child("vat_withholding_voucher_item");
    frm.refresh_field("vat_withholding_voucher_item");

    frm.set_value("company_address", "");
    frm.refresh_field("company_address");

    if (frm.doc.supplier && frm.doc.start_date && frm.doc.end_date) {
      load_invoices(frm);
    }
  },
});

frappe.ui.form.on('VAT Withholding Voucher Item', {
    vat_withholding_voucher_item_remove(frm, cdt, cdn) {
      console.log("Hola");
        calculate_totals(frm);
    }
});

function validar_fechas(frm, campo) {
  try {
    const startDate = new Date(frm.doc.start_date);
    const endDate = new Date(frm.doc.end_date);

    if (endDate < startDate) {
      frm.set_value(campo, null);
      frm.clear_table("vat_withholding_voucher_item");
      frm.add_child("vat_withholding_voucher_item");
      frm.refresh_field("vat_withholding_voucher_item");

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

  frm.clear_table("vat_withholding_voucher_item");

  frm.call({
    method:
      "get_valid_invoices",
    args: {
      supplier: frm.doc.supplier,
      start_date: frm.doc.start_date,
      end_date: frm.doc.end_date,
      company: frm.doc.empresa,
    },
    callback: function (r) {
      frm.doc.totals_grand_total = 0;
      frm.doc.totals_total_exempt = 0;
      frm.doc.totals_total = 0;
      frm.doc.totals_taxes_and_charges_added = 0;
      frm.doc.totals_tax_amount_vat = 0;


      if (r.message && r.message.length > 0) {
        r.message.forEach((invoice) => {
          let new_row = frm.add_child("vat_withholding_voucher_item");
          new_row.purchase_invoice = invoice.purchase_invoice;
          new_row.bill_no = invoice.bill_no;
          new_row.bill_control = invoice.bill_control;
          new_row.posting_date = invoice.posting_date;
          new_row.rate = invoice.rate;
          new_row.grand_total = invoice.grand_total;
          new_row.total_exempt = invoice.total_exempt;
          new_row.total = invoice.total;
          new_row.taxes_and_charges_added = invoice.taxes_and_charges_added;
          new_row.tax_amount_vat =
            invoice.tax_amount_vat;
          new_row.credit_note_no = invoice.credit_note_no;
          new_row.debit_note_no = invoice.debit_note_no;
          new_row.affected_invoice_number = invoice.affected_invoice_number;
          new_row.tax_amount = invoice.tax_amount;

          let negative = invoice.is_return ? -1 : 1;

          frm.doc.totals_grand_total += invoice.grand_total * negative || 0;
          frm.doc.totals_total_exempt += invoice.total_exempt * negative || 0;
          frm.doc.totals_total += invoice.total * negative || 0;
          frm.doc.totals_taxes_and_charges_added +=
            invoice.taxes_and_charges_added * negative || 0;
          frm.doc.totals_tax_amount_vat +=
            invoice.tax_amount_vat * negative || 0;
        });

        frm.refresh_fields([
          "totals_grand_total",
          "totals_total_exempt",
          "totals_total",
          "totals_taxes_and_charges_added",
          "totals_tax_amount_vat",
        ]);

        frm.refresh_fields();
      } else {
        frm.clear_table("vat_withholding_voucher_item");
        frm.add_child("vat_withholding_voucher_item");
        frm.refresh_field("vat_withholding_voucher_item");

        frm.doc.totals_grand_total = 0;
        frm.doc.totals_total_exempt = 0;
        frm.doc.totals_total = 0;
        frm.doc.totals_taxes_and_charges_added = 0;
        frm.doc.totals_tax_amount_vat = 0;
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

function calculate_totals(frm) {

  let total_grand_total = 0;
  let total_total_exempt = 0;
  let total_total = 0;
  let total_taxes_and_charges_added = 0;
  let total_tax_amount_vat = 0;

  frm.doc.vat_withholding_voucher_item.forEach(item => {
    let negative = item.credit_note_no ? -1 : 1;

    total_grand_total += item.grand_total * negative || 0;
    total_total_exempt += item.total_exempt * negative || 0;
    total_total += item.total * negative || 0;
    total_taxes_and_charges_added += item.taxes_and_charges_added * negative || 0;
    total_tax_amount_vat += item.tax_amount_vat * negative || 0;
  });

  frm.doc.totals_grand_total = total_grand_total;
  frm.doc.totals_total_exempt = total_total_exempt;
  frm.doc.totals_total = total_total;
  frm.doc.totals_taxes_and_charges_added = total_taxes_and_charges_added;
  frm.doc.totals_tax_amount_vat = total_tax_amount_vat;

  frm.refresh_fields([
      "totals_grand_total",
      "totals_total_exempt",
      "totals_total",
      "totals_taxes_and_charges_added",
      "totals_tax_amount_vat"
  ]);
};

function fields_read_only(frm, fields_read_only) {
  fields_read_only.forEach(field_read_only => {
    frm.set_df_property(field_read_only, 'read_only', true);
  });
}