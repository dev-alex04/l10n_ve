// Documento fiscal 04 (Orden de Entrega / Guía de Despacho): lo común a la nota de entrega y
// al traslado de material. Cada formulario llama a l10n_ve.dispatch_note.refresh en su
// refresh; este archivo solo define el espacio de nombres, así que cargarlo en los dos
// doctypes no registra nada dos veces.

frappe.provide("l10n_ve.dispatch_note");

l10n_ve.dispatch_note.METHOD = "l10n_ve.digital_invoice.dispatch_note_integration";

// Estado HKA → color del aviso (los que admite frm.layout.show_message).
l10n_ve.dispatch_note.COLORS = { Pendiente: "blue", Error: "red", Emitida: "green", Anulada: "orange" };

// ¿La empresa emite el 04? Serie digital activa y el sitio con el 04 encendido: el mismo
// criterio que aplica el servidor al aprobar, que llega en el boot (dispatch_note_companies).
l10n_ve.dispatch_note.company_emits = function (company) {
	return Boolean(company) && (frappe.boot.dispatch_note_companies || []).includes(company);
};

// Tipo de documento del borrador: lo propone si el documento va a emitir el 04 --la nota de
// entrega como Orden de Entrega, el traslado de material que pide guía como Guía de
// Despacho-- y lo borra si deja de emitirlo: una devolución (hereda el tipo de la nota
// original), otro propósito, el traslado sin guía, una empresa que no emite con HKA. Si ya
// hay uno y aplica, se respeta: es lo que eligió el usuario.
//
// Es solo una propuesta a la vista. El campo no tiene valor por defecto a propósito: con uno,
// cada documento nacía con un tipo aunque no fuera a emitirse, y el filtro de la lista lo
// contaba. Y el servidor no lo completa: al aprobar, un 04 sin tipo se corta, porque el tipo
// sale impreso en el documento fiscal.
l10n_ve.dispatch_note.sync_kind = function (frm) {
	if (frm.doc.docstatus !== 0) {
		return;
	}
	const emits = l10n_ve.dispatch_note.company_emits(frm.doc.company);
	let kind = null;
	if (emits && frm.doctype === "Delivery Note" && !frm.doc.is_return) {
		kind = "Orden de Entrega";
	} else if (
		emits &&
		frm.doctype === "Stock Entry" &&
		frm.doc.purpose === "Material Transfer" &&
		frm.doc.ve_issue_dispatch_note
	) {
		kind = "Guía de Despacho";
	}
	if (!kind && frm.doc.ve_dispatch_document_kind) {
		frm.set_value("ve_dispatch_document_kind", "");
	} else if (kind && !frm.doc.ve_dispatch_document_kind) {
		frm.set_value("ve_dispatch_document_kind", kind);
	}
};

// El bloque del 04 (tipo, motivo, origen y destino, vehículo, datos fiscales) solo en las
// empresas que lo emiten: en las demás, la nota de entrega y el traslado quedan como siempre.
// Un documento que ya pasó por el 04 lo sigue mostrando aunque la empresa haya dejado de
// emitir: son sus datos fiscales.
l10n_ve.dispatch_note.toggle_section = function (frm) {
	const show = l10n_ve.dispatch_note.company_emits(frm.doc.company) || Boolean(frm.doc.hka_status);
	frm.toggle_display("ve_dispatch_section", show);
};

l10n_ve.dispatch_note.refresh = function (frm) {
	l10n_ve.dispatch_note.toggle_section(frm);

	const status = frm.doc.hka_status;
	if (frm.doc.docstatus === 0 || !status) {
		return;
	}
	// Cancelado antes de emitirse: no hay documento fiscal que mostrar.
	if (frm.doc.docstatus === 2 && status !== "Anulada") {
		return;
	}

	l10n_ve.dispatch_note.show_status(frm);
	l10n_ve.dispatch_note.setup_buttons(frm);

	// El mismo panel que la factura y los comprobantes: número, control, enlace a HKA y el PDF.
	frappe.l10n_ve.render_fiscal_preview(frm, {
		doctype: frm.doc.doctype,
		title: `${frm.doc.ve_dispatch_document_kind || "Documento de despacho"} · Documento Fiscal Digital`,
	});
};

// Aviso arriba del formulario, visible en todas las pestañas: qué documento fiscal es y en
// qué estado está. Frappe lo limpia solo en cada refresh.
l10n_ve.dispatch_note.show_status = function (frm) {
	const esc = frappe.utils.escape_html;
	const kind = esc(frm.doc.ve_dispatch_document_kind || "Documento de despacho");
	const number = frm.doc.bill_no ? ` N° ${esc(frm.doc.bill_no)}` : "";
	const control = frm.doc.bill_control ? ` · control ${esc(frm.doc.bill_control)}` : "";
	const messages = {
		Emitida: `<b>${kind}${number}</b>${control} · emitida ante HKA (documento fiscal 04).`,
		Pendiente: `<b>${kind}</b> pendiente de emisión ante HKA (documento fiscal 04). Sale en el próximo envío automático o con HKA → Enviar a HKA.`,
		Error: `<b>${kind}</b>: HKA no la emitió. El motivo está en el registro de facturación digital; corrija y use HKA → Enviar a HKA.`,
		Anulada: `<b>${kind}${number}</b>${control} · anulada ante HKA.`,
	};
	const status = frm.doc.hka_status;
	if (messages[status]) {
		frm.layout.show_message(messages[status], l10n_ve.dispatch_note.COLORS[status], true);
	}
};

l10n_ve.dispatch_note.setup_buttons = function (frm) {
	if (frm.doc.docstatus !== 1) {
		return;
	}
	const status = frm.doc.hka_status;

	// Enviar solo si la empresa emite el 04: si no, el servidor lo rechazaría.
	if ((status === "Pendiente" || status === "Error") && l10n_ve.dispatch_note.company_emits(frm.doc.company)) {
		frm.add_custom_button(
			__("Enviar a HKA"),
			() => l10n_ve.dispatch_note.send(frm),
			"HKA"
		);
	}

	// Anular no depende de la empresa ni del interruptor: el documento ya existe en HKA.
	if (status === "Emitida") {
		frm.add_custom_button(
			__("Anular en HKA"),
			() => l10n_ve.dispatch_note.void(frm),
			"HKA"
		);
	}
};

l10n_ve.dispatch_note.send = function (frm) {
	frappe.call({
		method: `${l10n_ve.dispatch_note.METHOD}.send_dispatch_note_manually`,
		args: { doctype: frm.doc.doctype, name: frm.doc.name },
		freeze: true,
		freeze_message: "Enviando a HKA…",
		callback: (r) => {
			if (r.message) {
				frappe.show_alert({ message: r.message, indicator: "green" });
			}
			frm.reload_doc();
		},
		error: () => frm.reload_doc(),
	});
};

l10n_ve.dispatch_note.void = function (frm) {
	frappe.prompt(
		[
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: "Motivo de la anulación",
				reqd: 1,
			},
		],
		(values) => {
			frappe.call({
				method: `${l10n_ve.dispatch_note.METHOD}.void_dispatch_note`,
				args: { doctype: frm.doc.doctype, name: frm.doc.name, reason: values.reason },
				freeze: true,
				freeze_message: "Anulando ante HKA…",
				callback: (r) => {
					if (r.message && r.message.message) {
						frappe.show_alert({ message: r.message.message, indicator: "green" });
					}
					frm.reload_doc();
				},
				// HKA pudo haber anulado y fallar después la cancelación (un documento vinculado,
				// el stock): el documento ya quedó «Anulada» y el formulario tiene que mostrarlo.
				error: () => frm.reload_doc(),
			});
		},
		"Anular el documento fiscal ante HKA",
		"Anular"
	);
};
