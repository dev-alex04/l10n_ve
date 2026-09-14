// Copyright (c) 2026, Domina Software and Contributors
// For license information, please see license.txt

// El diálogo de registrar a una parte --nombre, documento y dirección--, compartido por
// los dos lados de la integración ISP ↔ Contratista: la contratista lo abre al aceptar una
// orden («Registrar Cliente») y el ISP lo embebe al encargar una instalación. Son dos apps
// que corren en sitios distintos y no se ven entre sí; las dos dependen de esta, que es la
// dueña de las reglas que el diálogo muestra: la tabla de letras, los rangos por documento y
// los catálogos de dirección. Lo que el servidor sabe viene en `data`
// (`l10n_ve.party_registration.form_options` más lo precargado por quien llama).
//
// Tres formas de usarlo, de la más cerrada a la más abierta:
//   open({ title, data, primary_action_label, on_submit })  → un diálogo entero.
//   fields(data, ctx) + bind(dialog, data, ctx)              → la sección, dentro de otro diálogo.
//   show_notice(dialog, message)                             → el aviso de arriba.
frappe.provide("l10n_ve.party_registration");

(function (ns) {
	// Cómo se llama cada cosa para quien opera. Los valores internos van en inglés porque
	// son los de los Select; acá se traducen una sola vez, al mostrarlos.
	ns.DOCUMENT_LABELS = {
		RIF: "RIF",
		Cedula: "Cédula",
		Passport: "Pasaporte",
		DEA: "Código DEA",
	};

	// Los mismos nombres que usa el diálogo «Editar Dirección» de la ficha del cliente.
	// Quien aprendió a cargar una dirección allá ya sabe cargarla acá.
	ns.ADDRESS_FIELD_LABELS = {
		address_line1: "Dirección",
		address_type: "Tipo de Dirección",
		country: "País",
		state: "Estado/Provincia",
		city: "Ciudad/Pueblo",
		county: "Municipio",
		parish: "Parroquia",
		pincode: "Código Postal",
		phone: "Teléfono",
		email_id: "Correo Electrónico",
		is_primary_address: "Es Dirección Principal",
		is_shipping_address: "Es Dirección de Envío",
	};

	// El Address la guarda en un Data de una línea, pero escribirla ahí es incómodo: una
	// dirección venezolana lleva urbanización, edificio y apartamento y no se ve entera. Se
	// pide en un cuadro de varias líneas y el servidor la aplana --y parte en
	// `address_line2` lo que no entre-- antes de guardarla.
	const FORCED_FIELDTYPE = { address_line1: "Small Text" };

	// La dirección que se registra acá es la principal y la de envío, siempre (Daniel,
	// 12-sep-2026): marcadas y de solo lectura. El servidor lo vuelve a imponer, porque el
	// endpoint se puede llamar sin el diálogo.
	const ALWAYS_CHECKED = ["is_primary_address", "is_shipping_address"];

	// Cómo se reparten en filas. Apilados no entran en pantalla junto a lo demás.
	const ADDRESS_ROWS = [
		["address_line1"],
		["address_type", "country"],
		["state", "city", "county"],
		["parish", "pincode"],
		["phone", "email_id"],
		["is_primary_address", "is_shipping_address"],
	];

	// De qué cuelga cada catálogo. Filtrar por el padre convierte 336 municipios en los 22
	// que pueden ser, y 1.140 parroquias en las de ese municipio.
	const CATALOG_PARENT = {
		"VE Municipality": "state",
		"VE City": "state",
		"VE Parish": "county",
	};

	// Cómo se llama el campo del padre DENTRO del catálogo hijo: la parroquia guarda el
	// municipio en `municipality`, no en `county`.
	const PARENT_FIELD_IN_CATALOG = {
		"VE Municipality": "state",
		"VE City": "state",
		"VE Parish": "municipality",
	};

	// El teléfono y el correo son de la persona, no sólo de su dirección: se piden una vez
	// y se escriben en los dos lados. Por eso son obligatorios aunque no se cargue dirección
	// --la parte los exige-- y por eso no se preguntan dos veces.
	const CONTACT_OF_THE_PARTY = { phone: "mobile_no", email_id: "email_id" };

	// Qué documento admite esa cantidad de dígitos, con los rangos que manda el servidor
	// (`get_tax_id_config`). El primero que encaje; si no encaja ninguno, el número está
	// mal y se elige por cercanía, igual que hace el servidor.
	ns.document_type_for_length = function (entry, number) {
		const ranges = entry.document_ranges || {};
		const length = (number || "").length;
		const fits = (range) =>
			Array.isArray(range) ? length >= range[0] && length <= range[1] : length === range;

		const candidates = [entry.short_document, entry.long_document].filter(
			(t, i, all) => t && all.indexOf(t) === i
		);

		return (
			candidates.find((t) => fits(ranges[t])) ||
			(length < 6 ? entry.short_document : entry.long_document)
		);
	};

	ns.notice_field = function () {
		return { fieldname: "party_notice", fieldtype: "HTML" };
	};

	ns.show_notice = function (dialog, message) {
		const field = dialog.get_field("party_notice");

		if (!field) {
			frappe.msgprint({ message: frappe.utils.escape_html(message), indicator: "orange" });
			return;
		}

		field.$wrapper.html(`<div class="alert alert-warning">${frappe.utils.escape_html(message)}</div>`);
	};

	// Los campos del registro: nombre, documento y dirección. `ctx.dialog` lo completa
	// `bind`, porque los filtros de los catálogos necesitan leer un diálogo que todavía no
	// existe cuando se arman los campos.
	//
	// `data.address_required` decide qué es la dirección para quien llama. Para la
	// contratista es opcional --el cliente se registra igual y la dirección se completa
	// después desde su ficha--; para el ISP es la esencia del encargo: la cuadrilla tiene
	// que ir a algún lado, así que la línea y los catálogos obligatorios del Address
	// (país, estado, ciudad, municipio) se exigen siempre.
	ns.fields = function (data, ctx) {
		const letters = data.letters || [];
		const required = data.required || {};
		const address_required = !!data.address_required;
		const defaults = data.address_defaults || {};
		const by_name = {};
		(data.address_fields || []).forEach((field) => {
			by_name[field.fieldname] = field;
		});

		// Una opción vacía adelante y a propósito: sin ella el Select se posa en la primera
		// letra --"V"-- y el operador confirma una clasificación que nunca eligió. Es el
		// mismo silencio que se arregló del lado del servidor.
		const letter_options = [{ label: __("Selecciona…"), value: "" }].concat(
			letters.map((entry) => ({ label: `${entry.letter} — ${entry.label}`, value: entry.letter }))
		);

		const address_fields = [];
		let first_row = true;

		ADDRESS_ROWS.forEach((row) => {
			const present = row.filter((fieldname) => by_name[fieldname]);

			if (!present.length) {
				return;
			}

			// Una fila es un Section Break, no un Column Break. Los Column Break sólo parten
			// la sección en columnas, así que sin esto las doce quedan en una sola fila de
			// columnas estrechas donde no entra ni la etiqueta.
			address_fields.push({
				fieldname: `sb_addr_${present[0]}`,
				fieldtype: "Section Break",
				label: first_row ? __("Dirección y contacto") : undefined,
			});
			first_row = false;

			present.forEach((fieldname, column) => {
				const field = by_name[fieldname];
				const of_the_party = CONTACT_OF_THE_PARTY[fieldname];

				if (column > 0) {
					address_fields.push({ fieldname: `cb_addr_${fieldname}`, fieldtype: "Column Break" });
				}

				const control = {
					fieldname: fieldname,
					fieldtype: FORCED_FIELDTYPE[fieldname] || field.fieldtype,
					options: FORCED_FIELDTYPE[fieldname] ? undefined : field.options,
					label: __(ns.ADDRESS_FIELD_LABELS[fieldname] || fieldname),
					default: defaults[fieldname],
				};

				if (ALWAYS_CHECKED.includes(fieldname)) {
					control.default = 1;
					control.read_only = 1;
				}

				if (of_the_party) {
					// Lo exige la parte, no el Address: se pide siempre, haya dirección o no.
					control.reqd = required[of_the_party] ? 1 : 0;
				} else if (address_required && (field.reqd || fieldname === "address_line1")) {
					control.reqd = 1;
				} else if (field.reqd && fieldname !== "address_line1") {
					// Obligatorio sólo si hay dirección que registrar --sin ella no se crea
					// ningún Address, y exigir el municipio de una dirección que no existe
					// bloquearía el alta por un dato que nadie va a usar-- pero **visible
					// siempre**, como en el diálogo de la ficha.
					//
					// Esconderlos con `depends_on` no funciona: `refresh_dependency` corre al
					// construir el diálogo, cuando los `default` todavía no están en los
					// inputs, y evalúa la dirección como vacía aunque venga cargada.
					control.mandatory_depends_on = "eval:!!doc.address_line1";
				}

				const parent = CATALOG_PARENT[field.options];

				if (parent) {
					control.get_query = () => ({
						filters: {
							[PARENT_FIELD_IN_CATALOG[field.options]]: (ctx.dialog && ctx.dialog.get_value(parent)) || "",
						},
					});
				}

				address_fields.push(control);
			});
		});

		return [
			{
				fieldname: "customer_name",
				fieldtype: "Data",
				label: __("Nombre o razón social"),
				default: data.customer_name,
				reqd: 1,
			},
			{ fieldname: "sb_document", fieldtype: "Section Break", label: __("Documento") },
			{
				fieldname: "letter",
				fieldtype: "Select",
				label: __("Tipo"),
				options: letter_options,
				default: data.letter || "",
				reqd: data.classifies ? 1 : 0,
				description: __("Decide si se registra como persona o como empresa."),
			},
			{ fieldname: "cb_document_1", fieldtype: "Column Break" },
			{
				fieldname: "document_type",
				fieldtype: "Select",
				label: __("Documento"),
				options: [],
				// Las opciones dependen de la letra: una empresa no tiene cédula. Se llenan
				// en `bind`, no acá.
				reqd: data.classifies ? 1 : 0,
			},
			{ fieldname: "cb_document_2", fieldtype: "Column Break" },
			{
				fieldname: "digits",
				fieldtype: "Data",
				label: __("Número"),
				default: data.digits,
				reqd: required.tax_id ? 1 : 0,
				description: __("Sin puntos ni guiones."),
			},
		].concat(address_fields);
	};

	// Engancha los comportamientos sobre un diálogo que ya tiene los campos de `fields`.
	ns.bind = function (dialog, data, ctx) {
		ctx = ctx || {};
		ctx.dialog = dialog;

		const by_letter = {};
		(data.letters || []).forEach((entry) => {
			by_letter[entry.letter] = entry;
		});

		// Qué documentos admite la letra elegida. Se conserva el que ya estuviera puesto si
		// sigue siendo válido: cambiar de "V" a "E" no tiene por qué borrar "Cédula".
		const repaint_document_types = () => {
			const entry = by_letter[dialog.get_value("letter")];
			const types = (entry && entry.document_types) || [];
			const previous = dialog.get_value("document_type");

			dialog.set_df_property(
				"document_type",
				"options",
				types.map((t) => ({ label: __(ns.DOCUMENT_LABELS[t] || t), value: t }))
			);

			if (types.includes(previous)) {
				dialog.set_value("document_type", previous);
				return;
			}

			// El que corresponda por longitud, que es el que acierta casi siempre: 8 dígitos
			// es cédula, 9 es RIF.
			const number = (dialog.get_value("digits") || "").replace(/[^0-9A-Za-z]/g, "");
			const suggested = entry ? ns.document_type_for_length(entry, number) : "";

			dialog.set_value("document_type", types.includes(suggested) ? suggested : types[0] || "");
		};

		// Qué se va a registrar, dicho en la descripción del propio Select. Esta
		// clasificación **falla en silencio** --un Select obligatorio vacío se llena con
		// `Juridical`, y una persona con cédula queda como empresa-- así que sin ninguna
		// señal el operador confirma sin haber podido ver nada. Va pegado al campo que lo
		// decide y ocupa cero espacio.
		const tell_the_classification = () => {
			const entry = by_letter[dialog.get_value("letter")];
			const number = (dialog.get_value("digits") || "").replace(/[^0-9A-Za-z]/g, "").toUpperCase();
			const type = dialog.get_value("document_type");

			dialog.set_df_property(
				"letter",
				"description",
				entry && number && type
					? __("Se registrará como <b>{0}</b> · {1} <b>{2}</b>", [
							entry.label,
							ns.DOCUMENT_LABELS[type] || type,
							entry.letter + number,
					  ])
					: __("Decide si se registra como persona o como empresa.")
			);
		};

		const digits = dialog.fields_dict.digits;

		// Nada se mueve mientras se escribe el número: el tipo de documento y el resumen
		// se recalculan al salir del campo. Antes se seguía tecla a tecla, y eso chocaba
		// con una trampa de Frappe: un Data confirma su valor interno al salir del campo
		// (o medio segundo después), y `set_value` sobre otro campo del diálogo termina en
		// `get_values`, que **repinta todo obligatorio cuyo valor interno esté vacío** --el
		// número, a medio escribir, quedaba en blanco a cada tecla--. Seguirlo en vivo no
		// hacía falta para nada.
		//
		// El interno se confirma acá igual: el `change` de Frappe corre antes que este
		// pero termina en una promesa, y el repintado no puede quedar a merced de ese orden.
		const on_document_change = () => {
			digits.value = digits.get_input_value();
			repaint_document_types();
			tell_the_classification();
		};

		dialog.fields_dict.letter.$input.on("change", on_document_change);
		digits.$input.on("change", on_document_change);
		dialog.fields_dict.document_type.$input.on("change", tell_the_classification);

		// Cambiar de estado invalida el municipio y la ciudad que ya estuvieran puestos: son
		// de otro estado y el alta los rechazaría con un mensaje que no dice eso.
		Object.entries(CATALOG_PARENT).forEach(([catalog, parent]) => {
			const child = (data.address_fields || []).find((field) => field.options === catalog);

			if (!child || !dialog.fields_dict[parent] || !dialog.fields_dict[child.fieldname]) {
				return;
			}

			dialog.fields_dict[parent].$input.on("change", () => dialog.set_value(child.fieldname, ""));
		});

		// El diálogo de Frappe reevalúa `mandatory_depends_on` al cambiar `input` y
		// `select`, pero la dirección es un `textarea` y se le escapa: sin esto, los
		// catálogos que dependen de ella nunca se marcaban obligatorios al escribirla.
		if (dialog.fields_dict.address_line1) {
			dialog.fields_dict.address_line1.$input.on("change", () => dialog.refresh_dependency());
		}

		repaint_document_types();
		tell_the_classification();

		// El aviso llega armado del servidor (`missing_contact_text`), con el verbo que
		// concuerda con lo que falta.
		if (data.missing) {
			ns.show_notice(dialog, data.missing);
		}
	};

	// Un diálogo entero, para quien no necesita mezclarlo con otros campos.
	ns.open = function ({ title, data, primary_action_label, on_submit, size = "large" }) {
		const ctx = {};
		const dialog = new frappe.ui.Dialog({
			title: title,
			size: size,
			fields: [ns.notice_field()].concat(ns.fields(data, ctx)),
			primary_action_label: primary_action_label,
			primary_action(values) {
				on_submit(values, dialog);
			},
		});

		dialog.show();
		ns.bind(dialog, data, ctx);

		return dialog;
	};
})(l10n_ve.party_registration);
