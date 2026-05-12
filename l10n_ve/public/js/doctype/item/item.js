frappe.ui.form.on("Item", {
  onload: function (frm) {
    if (frm.is_new()) {
      frm.set_value("has_batch_no", 1);
      frm.set_value("has_serial_no", 1);

      if (!frm.doc.reference_currency) {
        frappe.db
          .get_value("Company", frm.doc.company, "reference_currency")
          .then((r) => {
            if (r.message && r.message.reference_currency) {
              frm.set_value("reference_currency", r.message.reference_currency);
            }
          });
      }
    }
  },
  company: function (frm) {
    if (frm.is_new() && frm.doc.company) {
      frappe.db
        .get_value("Company", frm.doc.company, "reference_currency")
        .then((r) => {
          if (r.message && r.message.reference_currency) {
            frm
              .set_value("reference_currency", r.message.reference_currency)
              .then(() => {
                frm.refresh_field("price_sales");
                frm.refresh_field("price_purchase");
              });
          }
        });
    }
  },

  refresh: function (frm) {
    frm.set_query("economic_activity", function () {
      return {
        filters: {
          "is_group": 0
        }
      };
    });

    const is_saved = !frm.is_new();
    frm.toggle_display("price_sales", is_saved);
    frm.toggle_display("price_purchase", is_saved);

    if (frm.is_reloading) {
      frm.is_reloading = false;
      return;
    }

    if (is_saved) {
      if (!frm.is_dirty()) {
        frm.is_reloading = true;
        frm.reload_doc();
      } else {
        frappe.db.get_doc(frm.doctype, frm.doc.name).then((server_doc) => {
          if (server_doc.modified > frm.doc.modified) {
            frappe.show_alert({
              message: __("El precio del producto ha sido modificado"),
              indicator: "orange",
            });
            frm.set_value("price_sales", server_doc.price_sales);
            frm.set_value("price_purchase", server_doc.price_purchase);
            // Marcar el formulario como "sucio" para habilitar el guardado
            frm.dirty();
          }
        });
      }
    }

    if (frm.doc.reference_currency) {
      frm.refresh_field("price_sales");
      frm.refresh_field("price_purchase");
    }
  },

});
