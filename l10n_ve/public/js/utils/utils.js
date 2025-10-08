frappe.provide("frappe.l10n_ve");

frappe.l10n_ve.utils = {
  /**
   * @param {object} frm
   * @param {string} doctype_name
   */
  setup_void_button: function (frm, doctype_name) {
    if (frm.doc.docstatus === 2 && !frm.doc.is_void) {
      frm.add_custom_button(
        __("Anular Documento"),
        function () {
          frappe.confirm(
            __(
              "¿Estás seguro de que deseas anular este documento?"
            ),
            () => {
              frappe.call({
                method:
                  "l10n_ve.overrides." +
                  doctype_name.toLowerCase().replace(/ /g, "_") +
                  ".void_document",
                args: {
                  doctype: frm.doc.doctype,
                  name: frm.doc.name,
                },
                callback: function (r) {
                  if (!r.exc) {
                    frappe.show_alert({
                      message: __("Documento anulado correctamente."),
                      indicator: "green",
                    });
                    frm.reload_doc();
                  }
                },
                error: () => {
                  frappe.show_alert({
                    message: __("Ocurrió un error al anular el documento."),
                    indicator: "red",
                  });
                },
              });
            }
          );
        },
        __("Acciones")
      );
    }
  },
};
