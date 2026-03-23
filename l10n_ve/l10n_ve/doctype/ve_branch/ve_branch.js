// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Branch", {
  refresh(frm) {
    frm.trigger("setup_fields");
  },

  onload(frm) {
    frm.set_query("parent_ve_branch", function () {
      return {
        filters: {
          "is_group": 1
        }
      };
    });
  },

  setup(frm) {
    frm.trigger("setup_fields");

    frm.set_query("mode_of_payment", "mode_of_payments", function () {
      return {
        query:
          "l10n_ve.l10n_ve.doctype.ve_branch.ve_branch.get_modes_of_payment_for_company",
        filters: {
          company: frm.doc.company,
        },
      };
    });

    frm.set_query("account", "mode_of_payments", function () {
      return {
        filters: {
          company: frm.doc.company,
          is_group: 0,
        },
      };
    });

    frm.set_query("cost_center", function () {
      return {
        filters: {
          "is_group": 0,
          "company": frm.doc.company
        }
      };
    });
  },

  is_group(frm) {
    frm.trigger("setup_fields");
  },

  parent_ve_branch(frm) {
    frm.trigger("setup_fields");

    if (frm.doc.parent_ve_branch) {
      frappe.db
        .get_value("VE Branch", frm.doc.parent_ve_branch, "company")
        .then((r) => {
          if (r.message && r.message.company) {
            frm.set_value("company", r.message.company);
          }
        });

      frappe.call({
        doc: frm.doc,
        method: "get_details_from_parent",
        args: {
          parent_branch: frm.doc.parent_ve_branch,
        },
        callback: function (r) {
          if (r.message) {
            if (r.message.users) {
              frm.clear_table("users");
              r.message.users.forEach(d => frm.add_child("users", d));
              frm.refresh_field("users");
            }
            if (r.message.mode_of_payments) {
              frm.clear_table("mode_of_payments");
              r.message.mode_of_payments.forEach(d => frm.add_child("mode_of_payments", d));
              frm.refresh_field("mode_of_payments");
            }
          }
        },
      });
    }
  },

  setup_fields(frm) {
    const is_group = frm.doc.is_group;

    if (is_group) {
      frm.set_df_property("company", "reqd", 1);
      frm.set_df_property("company", "read_only", 0);
      frm.set_df_property("parent_ve_branch", "hidden", 1);
      frm.set_df_property("parent_ve_branch", "reqd", 0);
    } else {
      frm.set_df_property("company", "reqd", 0);
      frm.set_df_property("company", "read_only", 1);
      frm.set_df_property("parent_ve_branch", "hidden", 0);
      frm.set_df_property("parent_ve_branch", "reqd", 1);
    }
  },
});

frappe.ui.form.on("VE Branch Payment Modes", {
  mode_of_payment(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row.mode_of_payment || !frm.doc.company) {
      return;
    }

    frappe.call({
      method:
        "erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account",
      args: {
        mode_of_payment: row.mode_of_payment,
        company: frm.doc.company,
      },
      callback: function (r) {
        if (r.message && r.message.account) {
          frappe.model.set_value(cdt, cdn, "account", r.message.account);
        }
      },
    });
  },
});
