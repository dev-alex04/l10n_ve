// Copyright (c) 2025, DominaERP and contributors
// For license information, please see license.txt

frappe.listview_settings["Currency Exchange"] = {
  onload: function (listview) {
    const btn = listview.page.add_inner_button(
      __("Actualizar Tasas del BCV"),
      function () {
        const original_text = btn.text();
        btn.prop("disabled", true).text(__("Actualizando..."));

        frappe.show_alert({
          message: __("Iniciando actualización..."),
          indicator: "blue",
        });

        frappe.call({
          method: "l10n_ve.tasks.create_currency_exchange",
          callback: function (r) {
            frappe.show_alert(
              { message: __("Actualización completada."), indicator: "green" },
              5
            );
          },
          error: function (r) {
            frappe.msgprint({
              title: __("Error"),
              indicator: "red",
              message:
                r.message ||
                __("Ocurrió un error al actualizar las tasas de cambio."),
            });
          },
          always: function () {
            btn.prop("disabled", false).text(original_text);
            frappe.hide_alert();
            listview.refresh();
          },
        });
      }
    );
  },
};