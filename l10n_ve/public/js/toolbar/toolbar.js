frappe.ui.toolbar.toggle_full_width = function() {
    // Forzamos el valor a 'true' en el almacenamiento local.
    if (window.localStorage) {
        localStorage.container_fullwidth = "true";
    }
    // Aplicamos el estilo CSS.
    frappe.ui.toolbar.set_fullwidth_if_enabled();
};
s