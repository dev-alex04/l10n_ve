frappe.ui.form.on("Company", {
  refresh: function (frm) {

    if (frm.is_new()) {
      frm.set_value('nature_of_the_taxpayer', '');
      frm.set_value('type_of_person', '');
    }

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
      "sales_igtf_account",
      "sales_islr_account",
      "purchase_vat_account",
      "purchase_islr_account",
      "purchase_igtf_account",
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

  nature_of_the_taxpayer: function (frm) {
    set_person_type_filter(frm);
    build_rif(frm);
  },

  type_of_person: function (frm) {

  },

  tax_id: function (frm) {
    build_rif(frm);
  },
});

erpnext.company.set_custom_query = function (frm, v) {
  var filters = {
    company: frm.doc.name,
    is_group: 0,
  };

  frm.set_query(v[0], function () {
    return {
      filters: filters,
    };
  });
};
