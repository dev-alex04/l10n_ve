// Lista del documento fiscal 04: en el título de cada fila, qué documento es --Orden de
// Entrega o Guía de Despacho--, con su número y su estado ante HKA. Para ver solo uno de los
// dos está el filtro «Tipo de documento de despacho» de la barra, que mira el mismo campo:
// toda fila que el filtro trae dice qué es.
//
// Sin columnas nuevas, a propósito: una columna aparecería en todos los sitios, también en
// los que no emiten el 04, vacía en cada fila. Esto solo toca las filas con tipo --las que
// pasaron por el 04 y los borradores que lo van a emitir--; las demás quedan igual.
//
// El mismo archivo se carga en la lista de los dos doctypes (hooks.doctype_list_js) y
// extiende la configuración que ya trae ERPNext, sin reemplazarla.

frappe.provide("l10n_ve.dispatch_note");

// Dónde va la etiqueta. En la nota de entrega el título es el cliente, lo primero que se busca:
// la etiqueta va detrás. En el traslado el título es el tipo de entrada, que la columna
// «Propósito» ya muestra, y la columna es angosta: va adelante para que no se corte el número.
l10n_ve.dispatch_note.LIST_TITLES = {
	"Delivery Note": { field: "title", position: "after" },
	"Stock Entry": { field: "stock_entry_type", position: "before" },
};

// «Guía de Despacho N° 6», «Orden de Entrega (pendiente)»... Vacío si la fila no tiene tipo:
// al aprobar, el servidor se lo quita a lo que no emite el 04. El borrador lleva solo el tipo;
// que es borrador ya lo dice la columna de estado. Texto plano: la lista lo inserta con
// textContent.
l10n_ve.dispatch_note.list_label = function (doc) {
	const kind = doc.ve_dispatch_document_kind;
	if (!kind) {
		return "";
	}
	const status = doc.hka_status;
	const issued = status === "Emitida" || status === "Anulada";
	const number = issued && doc.bill_no ? ` N° ${doc.bill_no}` : "";
	let state = { Pendiente: "pendiente", Error: "con error", Anulada: "anulada" }[status];
	if (doc.docstatus === 2 && !issued) {
		state = "sin emitir"; // se canceló antes de que HKA lo emitiera
	}
	return `${kind}${number}${state ? ` (${state})` : ""}`;
};

l10n_ve.dispatch_note.extend_list = function (doctype) {
	const settings = frappe.listview_settings[doctype];
	const title = l10n_ve.dispatch_note.LIST_TITLES[doctype];
	// Una sola vez por doctype, y solo si el sitio ya tiene los campos: pedir una columna que
	// no existe (entre el despliegue y el migrate) rompería la consulta de toda la lista.
	if (!settings || settings.__l10n_ve_dispatch || !frappe.meta.get_docfield(doctype, "hka_status")) {
		return;
	}
	settings.__l10n_ve_dispatch = true;

	settings.add_fields = [
		...new Set([...(settings.add_fields || []), "hka_status", "ve_dispatch_document_kind", "bill_no"]),
	];
	settings.formatters = settings.formatters || {};
	const previous = settings.formatters[title.field];
	settings.formatters[title.field] = function (value, df, doc) {
		const base = (previous ? previous(value, df, doc) : value) || doc.name;
		const label = l10n_ve.dispatch_note.list_label(doc);
		if (!label) {
			return base;
		}
		return title.position === "before" ? `${label} · ${base}` : `${base} · ${label}`;
	};

	// Sin ninguna empresa que emita el 04, sus dos filtros de la barra no traen nada: se
	// ocultan. Frappe arma los filtros antes del onload de la lista. Uno con valor queda a la
	// vista: oculto, filtraría la lista sin que se vea por qué.
	const previous_onload = settings.onload;
	settings.onload = function (listview) {
		if (previous_onload) {
			previous_onload(listview);
		}
		if ((frappe.boot.dispatch_note_companies || []).length) {
			return;
		}
		for (const fieldname of ["ve_dispatch_document_kind", "hka_status"]) {
			const field = listview.page.fields_dict[fieldname];
			if (field && !field.get_value()) {
				field.$wrapper.hide();
			}
		}
	};
};

Object.keys(l10n_ve.dispatch_note.LIST_TITLES).forEach(l10n_ve.dispatch_note.extend_list);
