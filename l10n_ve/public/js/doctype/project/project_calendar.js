frappe.views.calendar["Project"] = {
    field_map: {
        start: "expected_start_date",
        end: "expected_end_date",
        id: "name",
        title: "project_name",
        allDay: "all_day",
        status: "status"
    },
    style_field: "status",
    get_events_method: "l10n_ve.overrides.project.get_events",

    get_css_class: function(data) {
        // Colores estándar de Frappe
        const status = data.status;
        if (["Completado", "Completed"].includes(status)) return "success";
        if (["Cancelado", "Cancelled"].includes(status)) return "gray";
        if (["Abierto", "Open", "Abierta"].includes(status)) return "danger";
        return "warning";
    }
};