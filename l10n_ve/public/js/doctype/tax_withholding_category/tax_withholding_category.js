frappe.ui.form.on("Tax Withholding Category", {
  setup: function (frm) {
    frm.set_query("account", "accounts", function (doc, cdt, cdn) {
      var child = locals[cdt][cdn];
      if (child.company) {
        return {
          filters: {
            is_group: 0,
            company: child.company,
            root_type: ["in", ["Asset", "Liability", "Tax"]],
          },
        };
      }
    });
  },
});
