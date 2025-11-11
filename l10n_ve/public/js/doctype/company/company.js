frappe.ui.form.on("Company", {
  refresh: function (frm) {
    get_address_link(frm);
    reorganize_customer_fields(frm);
    if (frm.is_new()) {
      frm.set_value("nature_of_the_taxpayer", "");
      frm.set_value("type_of_person", "");
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

  type_of_person: function (frm) {},

  tax_id: function (frm) {
    build_rif(frm);
  },

  create_chart_of_accounts_based_on: function (frm) {
    set_df_company_fields(frm);
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

erpnext.company.set_chart_of_accounts_options = function (doc) {
  var selected_value = doc.chart_of_accounts;
  if (doc.country) {
    return frappe.call({
      method:
        "erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_charts_for_country",
      args: {
        country: doc.country,
        with_standard: true,
      },
      callback: function (r) {
        if (!r.message.length) {
          return;
        }

        if (!r.exc) {
          set_field_options(
            "chart_of_accounts",
            [""].concat(r.message).join("\n")
          );
          if (in_list(r.message, selected_value)) {
            cur_frm.set_value("chart_of_accounts", selected_value);
          }
        }
      },
    });
  }
};
// Se utiliza 'var' para sobreescribir la función existente en ERPNext y evitar su doble ejecución.
var set_df_company_fields = function (frm) {
  if (!frm.is_new()) {
    return;
  }
  frm.set_df_property("create_chart_of_accounts_based_on", "reqd", true);
  frm.set_df_property(
    "chart_of_accounts",
    "reqd",
    frm.doc.create_chart_of_accounts_based_on === "Standard Template"
  );
  frm.set_df_property(
    "existing_company",
    "reqd",
    frm.doc.create_chart_of_accounts_based_on === "Existing Company"
  );
};

function reorganize_customer_fields(frm) {
  let num_license_wrapper = frm.get_field("num_license").$wrapper;
  let is_special_taxpayer_wrapper = frm.get_field("is_special_taxpayer").$wrapper;

 num_license_wrapper.insertAfter(is_special_taxpayer_wrapper);
}
