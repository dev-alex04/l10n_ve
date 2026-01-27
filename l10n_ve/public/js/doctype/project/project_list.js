frappe.listview_settings['Project'] = {
	add_fields: ["expected_start_date", "expected_end_date", "project_name", "status", "priority", "percent_complete"],
};

if (frappe.get_meta("Project")) {
	frappe.get_meta("Project").allow_calendar = 1;
}

frappe.views.calendar["Project"] = {
	field_map: {
		"start": "expected_start_date",
		"end": "expected_end_date",
		"id": "name",
		"title": "project_name",
		"allDay": "allDay",
		"progress": "percent_complete"
	},
	style_map: {
		"Completed": "success",
		"Cancelled": "danger",
		"Open": "primary"
	},
	get_events_method: "frappe.desk.calendar.get_events"
};