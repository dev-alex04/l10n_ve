frappe.ui.form.on("Stock Entry", {
	refresh: function(frm) {
		set_currency_label_based_on_reference(frm);
	}
});

function set_currency_label_based_on_reference(frm) {
	if (frm.doc.company) {
		frappe.db.get_value("Company", frm.doc.company, "reference_currency").then(r => {
			if (r.message && r.message.reference_currency === "USD") {
				// Cambia la etiqueta del campo 'total_incoming_value'.
				frm.set_df_property(
					"total_incoming_value",
					"label",
					"Valor de Entrada Total (REF)"
				);
			} else {
				// Restaura la etiqueta original
				frm.set_df_property("total_incoming_value", "label", "Valor de Entrada Total");
			}
		});
	}
}