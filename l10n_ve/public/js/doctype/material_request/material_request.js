frappe.ui.form.on("Material Request", {
  refresh: function (frm) {
    frm.set_query("set_warehouse", function () {
      return {
        filters: {
          is_group: 0,
          company: frm.doc.company || "non-existent-company",
        },
      };
    });
  },
});
