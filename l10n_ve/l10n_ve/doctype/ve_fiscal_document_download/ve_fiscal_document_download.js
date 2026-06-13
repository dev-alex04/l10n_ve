// Copyright (c) 2026, Alexander and Contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Fiscal Document Download", {
	onload: function (frm) {
		// Escuchar notificaciones de segundo plano en tiempo real
		frappe.realtime.on("hka_download_completed", function (data) {
			if (data && data.docname === frm.docname) {
				frm.reload_doc();
				frappe.show_alert({
					message: __("Proceso de descarga finalizado: {0}", [__(data.status)]),
					indicator: data.status === "Completed" ? "green" : "red"
				});
			}
		});
	},

	refresh: function (frm) {
		// Limpiar alertas previas del headline
		frm.clear_headline_alert();

		if (frm.doc.files_html && frm.fields_dict.files_html) {
			frm.fields_dict.files_html.$wrapper.html(frm.doc.files_html);
		}

		if (frm.doc.__islocal) {
			return;
		}

		// Si el proceso está corriendo
		if (frm.doc.status === "Processing") {
			frm.set_headline_alert(
				__("El proceso se está ejecutando en segundo plano. Los archivos ZIP se adjuntarán aquí cuando finalice."),
				"orange"
			);
			
			// Añadir botón de recarga rápida
			frm.add_custom_button(__("Actualizar Estado"), function () {
				frm.reload_doc();
			});
		}

		// Mostrar botón para iniciar la descarga si está pendiente o fallido
		if (frm.doc.status === "Pending" || frm.doc.status === "Failed") {
			frm.add_custom_button(__("Generar Descarga"), function () {
				frappe.call({
					method: "l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.start_bulk_download",
					args: {
						docname: frm.doc.name
					},
					freeze: true,
					freeze_message: __("Iniciando descarga en segundo plano..."),
					callback: function (r) {
						frm.reload_doc();
					}
				});
			});
			frm.change_custom_button_type(__("Generar Descarga"), null, "primary");
		}
	}
});
