frappe.ui.form.on("Bank Statement Import", {
  refresh: function (frm) {
    if (frm.doc.import_file) {
      frm.add_custom_button(__("Cargar Extractos"), function () {
        frm.call({
          method: "l10n_ve.overrides.bank_statement_import.start_custom_import",
          args: {
            docname: frm.doc.name,
          },
          freeze: true,
          freeze_message: __("Procesando extractos bancarios..."),
          callback: function (r) {
            frm.reload_doc();
          },
        });
      });
    }
  },
  import_file: function (frm) {
    if (frm.doc.import_file) {
      frm.page.clear_custom_buttons();
      frm.trigger("refresh");
    }
  },
});
