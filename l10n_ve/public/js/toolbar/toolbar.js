
// 1. Forzar el modo de ancho completo al cargar la página.
if (window.localStorage) {
    localStorage.container_fullwidth = "true";
}

// 2. Aplicar el estilo CSS correspondiente.
frappe.ui.toolbar.set_fullwidth_if_enabled();

// 3. Sobrescribir la función que alterna el ancho de la pantalla.

frappe.ui.toolbar.toggle_full_width_original = frappe.ui.toolbar.toggle_full_width;

frappe.ui.toolbar.toggle_full_width = function() {
    console.log("toggle_full_width sobreescrito por l10n_ve para mantener el ancho completo.");

    // Forzamos el valor a 'true' en el almacenamiento local.
    localStorage.container_fullwidth = "true";
    // Aplicamos el estilo CSS.
    frappe.ui.toolbar.set_fullwidth_if_enabled();
};
