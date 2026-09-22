frappe.ui.form.on("Delivery Note", {
	onload(frm) {
		// Documento fiscal 04: propone Orden de Entrega si la nota lo va a emitir, y quita el
		// tipo que una devolución hereda de la nota original.
		l10n_ve.dispatch_note.sync_kind(frm);
	},

	is_return(frm) {
		l10n_ve.dispatch_note.sync_kind(frm);
	},

	company(frm) {
		// La otra empresa puede no emitir el 04: el bloque y la propuesta de tipo la siguen.
		l10n_ve.dispatch_note.sync_kind(frm);
		l10n_ve.dispatch_note.toggle_section(frm);
	},

	refresh(frm) {
		// Documento fiscal 04 (Orden de Entrega o Guía de Despacho): aviso, panel y botones.
		l10n_ve.dispatch_note.refresh(frm);
	},
});
