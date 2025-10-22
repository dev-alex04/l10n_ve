const RIF_LEGAL_NATURES = ["Juridical", "Government", "Communal"];
const RIF_NATURAL_NATURES = ["Venezuelan", "Extranjero", "Passport"];

/**
 *
 * @param {string} document_type - RIF, Cédula, Pasaporte
 * @param {string} nature - Naturaleza del contribuyente
 * @returns {number|Array<number>} - Longitud de dígitos
 */
function get_tax_id_config(document_type, nature) {
	const config = {
		'RIF': { default: 9 },
		'ID': {
			'Venezolano': 8,
			default: 8
		},
		'ID_Foreign': { default: [8, 10] },
		'Passport': {
			'Extranjero': [8, 12],
			'Venezolano': 8,
			default: [8, 12]
		}
	};

	const doc_config = config[document_type] || config['RIF'];
	return doc_config[nature] || doc_config.default;
}

/**
 *
 * @param {object} frm
 * @param {string} source_field
 */
function sync_taxpayer_fields(frm, source_field, is_company = false) {

	if (!frm.doc[source_field]) {
		return;
	}

	const nature = frm.doc.nature_of_the_taxpayer;
	const person_type = frm.doc.type_of_person;

	if (source_field === 'nature_of_the_taxpayer' || source_field === 'type_of_document') {
		if (RIF_LEGAL_NATURES.includes(nature)) {
			frm.set_value('type_of_person', 'Domiciled legal entity');

		} else if (RIF_NATURAL_NATURES.includes(nature)) {
			frm.set_value('type_of_person', 'Natural person domiciled');
		}
	} else if (source_field === 'type_of_person') {
		if (person_type.includes('natural person')) { // Persona Natural
			if (!RIF_NATURAL_NATURES.includes(nature)) {
				frm.set_value('nature_of_the_taxpayer', 'Venezuelan');
			}
		} else if (person_type.includes('legal entity')) { // Persona Jurídica
			if (!RIF_LEGAL_NATURES.includes(nature)) {
				frm.set_value('nature_of_the_taxpayer', 'Juridical');
			}
		}
	}

	if (!is_company) {
		// Al cambiar la naturaleza, reconstruir el tax_id
		build_tax_id(frm);
	}
}

/**
 *
 * @param {object} frm -
 */
function build_tax_id(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const document_type = frm.doc.type_of_document;
	const tax_id_value = frm.doc.tax_id || '';

	if (!nature || !document_type) {
		return;
	}

	const letter = nature.charAt(0).toUpperCase();
	let number = tax_id_value.replace(/[^0-9]/g, '');

	const length_config = get_tax_id_config(document_type, nature);
	const max_length = Array.isArray(length_config) ? length_config[1] : length_config;

	if (number.length > max_length) {
		number = number.substring(0, max_length);
	}

	const full_tax_id = letter + number;

	frm.set_value('tax_id', full_tax_id);
}

/**
 * Construye el RIF para la Compañía (versión simple).
 * @param {object} frm -
 */
function build_rif(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const tax_id_value = frm.doc.tax_id || '';

	if (!nature) {
		return;
	}

	const letter = nature.charAt(0).toUpperCase();
	let number = tax_id_value.replace(/[^0-9]/g, '');

	if (number.length > 9) {
		number = number.substring(0, 9);
	}

	frm.set_value('tax_id', letter + number);
}

/**
 *
 * @param {object} frm
 */
function set_person_type_filter(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const doc_type = frm.doc.type_of_document;

	let allowed_person_types = [];

	if (doc_type === 'ID' || doc_type === 'Passport') {
		allowed_person_types = ["Natural person domiciled", "Non-domiciled natural person"];
	} else if (RIF_LEGAL_NATURES.includes(nature)) {
		allowed_person_types = ["Domiciled legal entity",
			 "Non-domiciled legal entity"];
	} else if (RIF_NATURAL_NATURES.includes(nature)) {
		allowed_person_types = ["Natural person domiciled",
			"Non-domiciled natural person"];
	}

	if (frm.doc.type_of_person && !allowed_person_types.includes(frm.doc.type_of_person)) {
		frm.set_value('type_of_person', '');
	}

	frm.set_df_property('type_of_person', 'options', allowed_person_types.join('\n'));
}

/**
 * Filtra las opciones de Naturaleza del Contribuyente según el Tipo de Documento.
 * @param {object} frm
 */
function set_nature_filter(frm) {
	const doc_type = frm.doc.type_of_document;
	let allowed_natures = [];

	if (doc_type === 'ID_Foreign') {
		allowed_natures = ['Extranjero'];
		frm.set_value('nature_of_the_taxpayer', 'Extranjero');
	} else if (doc_type === 'ID' || doc_type === 'Passport') {
		allowed_natures = ['Venezuelan', 'Extranjero'];
	} else {
		// Para RIF u otros, permitir todas las opciones
		allowed_natures = RIF_LEGAL_NATURES.concat(RIF_NATURAL_NATURES);
	}

	// Si la naturaleza actual no está en las permitidas, limpiarla
	if (frm.doc.nature_of_the_taxpayer && !allowed_natures.includes(frm.doc.nature_of_the_taxpayer)) {
		frm.set_value('nature_of_the_taxpayer', '');
	}

	frm.set_df_property('nature_of_the_taxpayer', 'options', allowed_natures.join('\n'));
}