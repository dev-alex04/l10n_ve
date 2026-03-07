frappe.ui.form.on("Sales Taxes and Charges Template", {
  refresh: function (frm) {
    frm.set_query("account_head", "taxes", function (doc, cdt, cdn) {
      return {
        filters: {
          is_group: 0,
          account_type: "Tax",
          company: doc.company,
        },
      };
    });
  },
});
