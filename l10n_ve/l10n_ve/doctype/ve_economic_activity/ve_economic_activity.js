frappe.ui.form.on("VE Economic Activity", {
  onload: function (frm) {
    if (frm.is_new()) {
      // Limpiar las opciones para forzar la selección desde el inicio
      frm.set_df_property("group", "options", []);
      frm.set_df_property("branch", "options", []);

      if (frm.doc.sector) {
        frm.trigger("sector");
      }
    }
  },

  sector: function (frm) {

    frm.set_value("group", "");
    frm.set_value("branch", "");

    if (!frm.doc.sector) {
      return;
    }
    frappe.call({
      method:
        "l10n_ve.l10n_ve.doctype.ve_economic_activity.ve_economic_activity.get_economic_activity_options",
      args: {
        sector: frm.doc.sector,
      },
      callback: function (r) {
        if (r.message) {
          frm.set_df_property("group", "options", r.message);
          frm.refresh_field("group");
        }
      },
    });
  },

  group: function (frm) {
    // Limpiar el campo 'branch'
    frm.set_value("branch", "");

    // Obtener y actualizar las opciones para 'branch'
    if (frm.doc.sector && frm.doc.group) {
      frappe.call({
        method:
          "l10n_ve.l10n_ve.doctype.ve_economic_activity.ve_economic_activity.get_economic_activity_options",
        args: {
          sector: frm.doc.sector,
          group: frm.doc.group,
        },
        callback: function (r) {
          if (r.message) {
            frm.set_df_property("branch", "options", r.message);
            frm.refresh_field("branch");
          }
        },
      });
    }
  },
});