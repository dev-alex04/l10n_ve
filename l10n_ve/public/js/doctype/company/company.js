frappe.ui.form.on("Company", {
  refresh: function (frm) {
    frm.set_query("custom_company_primary_address", function () {
      return {
        filters: {
          link_doctype: "Company",
          link_name: frm.doc.name,
        },
      };
    });

    for (const account_name of [
      "sales_vat_account",
      "sales_islr_account",
      "purchase_vat_account",
      "purchase_islr_account",
      "sales_vat_withholding_account",
      "purchase_vat_withholding_account",
    ]) {
      frm.set_query(account_name, function (doc, cdt, cdn) {
        return {
          filters: {
            is_group: false,
            company: doc.company,
          },
        };
      });
    }
  },
});
