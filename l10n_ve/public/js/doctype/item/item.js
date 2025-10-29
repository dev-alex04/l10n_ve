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
			// Parsea el valor, que puede venir con punto o coma como separador decimal.
			const value = parseFloat(String(frm.doc[fieldname]).replace(',', '.'));
			if (!isNaN(value)) {
				// Formatea el valor con coma para la visualización.
				const formatted_value = value.toFixed(2).replace('.', ',');
				// Actualiza solo la vista del campo para no "ensuciar" el formulario.
				frm.get_field(fieldname).$wrapper.find('.control-value').text(formatted_value);
			}
		}
	});
}
