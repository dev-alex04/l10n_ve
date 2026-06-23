// Copyright (c) 2026, Alexander and Contributors
// For license information, please see license.txt

frappe.ui.form.on("VE Withholding Voucher Download", {
	onload: function (frm) {
		// Listen for realtime background job updates
		frappe.realtime.on("withholding_download_completed", function (data) {
			if (data && data.docname === frm.docname) {
				frm.reload_doc();
				const msg = data.status === "Completed" ? 
					__("Su descarga de comprobantes de retención fue exitosa") : 
					__("La descarga de comprobantes de retención falló");
				frappe.show_alert({
					message: msg,
					indicator: data.status === "Completed" ? "green" : "red"
				});
			}
		});
	},

	refresh: function (frm) {
		// Clear previous headline alerts
		frm.dashboard.clear_headline();

		if (frm.doc.files_html && frm.fields_dict.files_html && frm.fields_dict.files_html.$wrapper) {
			frm.fields_dict.files_html.$wrapper.html(frm.doc.files_html);
		}

		console.log("VE Withholding Voucher Download - Name:", frm.doc.name, "Status:", frm.doc.status, "Is New:", frm.is_new());

		if (frm.is_new()) {
			return;
		}

		const status = frm.doc.status;
		const is_pending = status === "Pending" || status === "Pendiente" || status === __("Pending");
		const is_failed = status === "Failed" || status === "Fallido" || status === __("Failed");
		const is_processing = status === "Processing" || status === "Procesando" || status === __("Processing");

		// If process is running
		if (is_processing) {
			frm.dashboard.set_headline_alert(
				__("El proceso se está ejecutando en segundo plano. Los archivos ZIP se adjuntarán aquí cuando finalice."),
				"orange"
			);
			
			// Add quick refresh button
			frm.add_custom_button(__("Actualizar Estado"), function () {
				frm.reload_doc();
			});
		}

		// Show generate download button if pending or failed
		if (is_pending || is_failed) {
			frm.add_custom_button(__("Generar Descarga"), function () {
				frappe.call({
					method: "l10n_ve.l10n_ve.doctype.ve_withholding_voucher_download.ve_withholding_voucher_download.get_voucher_count",
					args: {
						from_date: frm.doc.from_date,
						to_date: frm.doc.to_date,
						company: frm.doc.empresa,
						supplier: frm.doc.supplier,
						withholding_type: frm.doc.withholding_type
					},
					freeze: true,
					freeze_message: __("Verificando cantidad de comprobantes..."),
					callback: function (r) {
						const count = r.message || 0;
						if (count === 0) {
							frappe.msgprint({
								title: __("Sin Comprobantes"),
								indicator: "orange",
								message: __("No se encontraron comprobantes de retención en el rango seleccionado.")
							});
							return;
						}

						frappe.call({
							method: "l10n_ve.l10n_ve.doctype.ve_withholding_voucher_download.ve_withholding_voucher_download.start_bulk_download",
							args: {
								docname: frm.doc.name
							},
							freeze: true,
							freeze_message: __("Iniciando descarga en segundo plano..."),
							callback: function (res) {
								frm.reload_doc();
								frappe.msgprint({
									title: __("Descarga Iniciada"),
									indicator: "green",
									message: __("La solicitud de descarga ha sido iniciada en segundo plano. Se le notificará cuando finalice.")
								});
							}
						});
					}
				});
			});
			frm.change_custom_button_type(__("Generar Descarga"), null, "primary");
		}

	}
});
