frappe.ui.form.on('Item', {
	refresh: function (frm) {

		const is_saved = !frm.is_new();
		frm.toggle_display('sales_actual_price', is_saved);
		frm.toggle_display('purchase_actual_price', is_saved);
	},

	before_save: function (frm) {
		frm.was_new = frm.is_new();
	},

	after_save: function (frm) {
		if (frm.was_new) frm.reload_doc();
	}
});
