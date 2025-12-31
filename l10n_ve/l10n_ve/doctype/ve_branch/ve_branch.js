// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Branch", {
  refresh(frm) {
    frm.trigger("setup_fields");
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
    }
  },

  setup_fields(frm) {
    const has_parent = !!frm.doc.parent_ve_branch;

    if (has_parent) {
      frm.set_df_property("company", "reqd", 0);
      frm.set_df_property("company", "read_only", 1);
      frm.set_df_property("parent_ve_branch", "hidden", 0);
      frm.set_df_property("parent_ve_branch", "reqd", 1);
      frm.set_df_property("is_group", "read_only", 0);
    } else {
      frm.set_df_property("company", "reqd", 1);
      frm.set_df_property("company", "read_only", 0);
      frm.set_df_property("parent_ve_branch", "hidden", 1);
      frm.set_df_property("parent_ve_branch", "reqd", 0);
      frm.set_df_property("is_group", "read_only", 1);
      if (frm.doc.is_group !== 1) {
        frm.set_value("is_group", 1);
      }
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
