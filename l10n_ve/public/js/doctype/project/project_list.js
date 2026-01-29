console.log("aqui");
frappe.listview_settings['Project'] = {
	add_fields: ["expected_start_date", "expected_end_date", "project_name", "status", "priority", "percent_complete"],
};

if (frappe.get_meta("Project")) {
	frappe.get_meta("Project").allow_calendar = 1;
}

