frappe.pages['reporte-pro'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Reporte Pro',
		single_column: true
	});

	// Redirect to the portal dashboard
	window.location.href = "/reporte-pro";
};
