// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Municipality Taxes", {
  refresh(frm) {
    frm.set_query("municipality", function () {
      return {
        filters: {
          state: frm.doc.state,
        },
      };
    });
  },
  state(frm) {
    frm.set_value("municipality", "");
    frm.trigger("refresh");
  },
});
