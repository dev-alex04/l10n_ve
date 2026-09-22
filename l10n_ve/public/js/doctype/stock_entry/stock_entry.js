frappe.ui.form.on("Stock Entry", {
	// Documento fiscal 04: propone Guía de Despacho si el traslado la va a emitir, y quita el
	// tipo si deja de emitirla. También al abrir: un traslado armado desde una solicitud de
	// material llega con el propósito ya puesto, sin pasar por el evento.
	onload: function(frm) {
		l10n_ve.dispatch_note.sync_kind(frm);
	},

	purpose: function(frm) {
		l10n_ve.dispatch_note.sync_kind(frm);
	},

	ve_issue_dispatch_note: function(frm) {
		l10n_ve.dispatch_note.sync_kind(frm);
	},

	company: function(frm) {
		// La otra empresa puede no emitir el 04: el bloque y la propuesta de tipo la siguen.
		l10n_ve.dispatch_note.sync_kind(frm);
		l10n_ve.dispatch_note.toggle_section(frm);
	},

	refresh: function(frm) {
        // Documento fiscal 04 (Guía de Despacho): aviso, panel y botones.
        l10n_ve.dispatch_note.refresh(frm);

        if (!frm.doc.reference_currency) {
            frappe.msgprint({
                title: __('Advertencia'),
                indicator: 'orange',
                message: __('La moneda de referencia para la compañía seleccionada no está configurada.')
            });
        }
	}
});