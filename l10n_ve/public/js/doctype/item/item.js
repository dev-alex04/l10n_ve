frappe.ui.form.on('Item', {
	refresh: function (frm) {
		const is_saved = !frm.is_new();

		if (is_saved) {
			format_price_fields(frm);
		}

		frm.toggle_display('price_sales', is_saved);
		frm.toggle_display('price_purchase', is_saved);
	},

	before_save: function (frm) {
		frm.was_new = frm.is_new();
	},

	after_save: function (frm) {
		if (frm.was_new) frm.reload_doc();
	}
});

function format_price_fields(frm) {
	const fields_to_format = ['price_sales', 'price_purchase'];

	fields_to_format.forEach(fieldname => {
		if (frm.doc[fieldname]) {
			let value = parseFloat(frm.doc[fieldname]).toFixed(2);
			let formatted_value = value.replace('.', ',');
			frm.set_value(fieldname, formatted_value);
		}
	});
}
