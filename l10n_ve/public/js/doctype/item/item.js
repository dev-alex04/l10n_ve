frappe.ui.form.on("Item", {
  onload: function (frm) {
    if (frm.is_new() && !frm.doc.reference_currency) {
      frappe.db
        .get_value("Company", frm.doc.company, "reference_currency")
        .then((r) => {
          if (r.message && r.message.reference_currency) {
            frm.set_value("reference_currency", r.message.reference_currency);
          }
        });
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
    const is_saved = !frm.is_new();
    frm.toggle_display("price_sales", is_saved);
    frm.toggle_display("price_purchase", is_saved);

    if (is_saved) {
      frappe.db
        .get_value(frm.doctype, frm.doc.name, [
          "price_sales",
          "price_purchase",
        ])
        .then((r) => {
          if (r.message) {
            frm.set_value("price_sales", r.message.price_sales);
            frm.set_value("price_purchase", r.message.price_purchase);
          }
        });
    }
    if (frm.doc.reference_currency) {
      frm.refresh_field("price_sales");
      frm.refresh_field("price_purchase");
    }
  },
  price_sales: function (frm) {
    if (!frm.is_new() && frm.doc.price_sales !== frm.get_doc_before_save().price_sales) {
      frm.save().then(() => {
        frm.reload_doc();
      });
    }
  },
  price_purchase: function (frm) {
    if (!frm.is_new() && frm.doc.price_purchase !== frm.get_doc_before_save().price_purchase) {
      frm.save().then(() => {
        frm.reload_doc();
      });
    }
  },
});
