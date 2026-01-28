frappe.ui.form.on('Installation Note', {
	refresh: function(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__('Imprimir Nota de Instalación'), function() {
				const method = "l10n_ve.utils.pdf_installation_note.generate_installation_note_pdf";
				const url = frappe.urllib.get_full_url("/api/method/" + method) + 
							"?docname=" + encodeURIComponent(frm.doc.name);
				
				window.open(url, '_blank');
			}, __('Imprimir'));
		}
	}
});