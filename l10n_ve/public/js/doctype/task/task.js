frappe.ui.form.on("Task", {
	refresh: function(frm) {
		if (!frappe.user.has_role(["Projects Manager", "System Manager", "Administrator"])) {
			const fields_to_hide = [
				"total_billing_amount",
				"total_costing_amount",
				"priority"
			];
			fields_to_hide.forEach(field => frm.set_df_property(field, 'hidden', 1));
		}

		frm.toggle_display("actual_time", false);
		frm.toggle_display("parent_task", false);
		frm.toggle_display("task_weight", false);
		frm.toggle_display("type", false);
		frm.toggle_display("is_group", false);
		frm.toggle_display("color", false);

		frm.set_df_property("hour", "read_only", 1);
		
	}
});