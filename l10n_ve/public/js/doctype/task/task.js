frappe.ui.form.on("Task", {
	refresh: function(frm) {
		if (!frappe.user.has_role(["Projects Manager", "System Manager", "Administrator"])) {
			const fields_to_hide = [
				"total_billing_amount",
				"total_costing_amount"
			];
			fields_to_hide.forEach(field => frm.set_df_property(field, 'hidden', 1));
		}
	}
});