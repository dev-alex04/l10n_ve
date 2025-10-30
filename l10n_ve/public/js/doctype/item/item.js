frappe.ui.form.on('Item', {
	onload: function(frm) {

		if (frm.is_new() && !frm.doc.reference_currency) {

			frappe.db.get_value("Company", frm.doc.company, "reference_currency")
				.then(r => {
					if (r.message && r.message.reference_currency) {
						frm.set_value("reference_currency", r.message.reference_currency);
					}
				});
		}
	},
	refresh: function (frm) {
		const is_saved = !frm.is_new();

		frm.toggle_display('price_sales', is_saved);
		frm.toggle_display('price_purchase', is_saved);

		if (frm.doc.reference_currency) {

			frm.refresh_field("price_sales");
			frm.refresh_field("price_purchase");
		}
	},

	before_save: function (frm) {
		frm.was_new = frm.is_new();
	},

	after_save: function (frm) {
		if (frm.was_new) frm.reload_doc();
	}
});
