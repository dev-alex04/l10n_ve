// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Branch", {
  refresh(frm) {
    frm.trigger("setup_fields");
  },

  setup(frm) {
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
    }
  },

  setup_fields(frm) {
    const has_parent = !!frm.doc.parent_ve_branch;

    if (has_parent) {
      // Sucursal hija: empresa heredada y solo lectura
      frm.set_df_property("company", "reqd", 0);
      frm.set_df_property("company", "read_only", 1);
      frm.set_df_property("parent_ve_branch", "hidden", 0);
      frm.set_df_property("parent_ve_branch", "reqd", 1);
      frm.set_df_property("is_group", "read_only", 0);
    } else {
      // Sucursal raíz: empresa obligatoria, is_group forzado
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
