
frappe.ui.form.on("Project", {
	refresh: function(frm) {
		if (!frappe.user.has_role(["Projects Manager", "System Manager", "Administrator"])) {
			const fields_to_hide = [
				"estimated_costing", "per_gross_margin", "gross_margin",
				"total_consumed_material_cost", "total_billed_amount",
				"total_billable_amount", "total_sales_amount",
				"total_purchase_cost", "total_costing_amount"
			];
			fields_to_hide.forEach(field => frm.set_df_property(field, 'hidden', 1));
		}
	}
});