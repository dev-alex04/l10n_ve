const RIF_LEGAL_NATURES = ["Juridical", "Government", "Communal"];
const RIF_NATURAL_NATURES = ["Venezuelan", "Extranjero", "Passport"];

/**
 * @param {string} document_type
 * @param {string} nature
 * @returns {number|Array<number>}
 */
function get_tax_id_config(document_type, nature) {
	const config = {
		'RIF': { default: 9 },
		'Cedula': {
			default: 8
		},
		'Passport': {
			default: [8, 9]
		}
	};

	const doc_config = config[document_type] || config['RIF'];
	return doc_config[nature] || doc_config.default;
}

/**
 * @param {object} frm
 * @param {string} fieldname
 */
function handle_field_change(frm, fieldname) {
	// Si cambia el tipo de documento, es el cambio de mayor jerarquía.
	if (fieldname === 'type_of_document') {
		frm.set_value('nature_of_the_taxpayer', '');
		frm.set_value('type_of_person', '');
	}

	// Ejecutamos los filtros en cascada.
	set_nature_filter(frm);

	if (fieldname === 'nature_of_the_taxpayer') {
		build_tax_id(frm);
	}

	set_person_type_filter(frm);

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

	const length_config = get_tax_id_config(document_type, nature);
	const max_length = Array.isArray(length_config) ? length_config[1] : length_config;
	let full_tax_id = '';

	if (document_type === 'Passport') {
		let passport_number = tax_id_value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();

		let letter_count = 0;
		let cleaned_passport = "";
		for (const char of passport_number) {
			if (/[A-Z]/.test(char)) {
				if (letter_count < 3) {
					cleaned_passport += char;
					letter_count++;
				}
			} else {
				cleaned_passport += char;
			}
		}
		passport_number = cleaned_passport;

		if (passport_number.length > max_length) {
			passport_number = passport_number.substring(0, max_length);
		}
		full_tax_id = passport_number;
	} else {
		// Lógica para Cédula y RIF
		const letter = nature.charAt(0).toUpperCase();
		let number_part = tax_id_value.replace(/^[a-zA-Z]*/, '').replace(/\D/g, '');

		if (max_length && number_part.length > max_length) {
			number_part = number_part.substring(0, max_length);
		}
		full_tax_id = letter + number_part;
	}

	frm.set_value('tax_id', full_tax_id);
}

/**
 * Construye el RIF para la Compañía.
 * @param {object} frm -
 */
function build_rif(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const tax_id_value = frm.doc.tax_id || '';

	if (!nature) {
		return;
	}

	const letter = nature.charAt(0).toUpperCase();
	let number_part = tax_id_value.replace(/^[a-zA-Z]*/, '').replace(/\D/g, '');

	if (number_part.length > 9) {
		number_part = number_part.substring(0, 9);
	}

	frm.set_value('tax_id', letter + number_part);
}

/**
 *
 * @param {object} frm
 */
function set_person_type_filter(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const doc_type = frm.doc.type_of_document;

	let allowed_person_types = [];

	if (doc_type === 'Cedula' || doc_type === 'Passport') {
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

	if (doc_type === 'Cedula') {
		allowed_natures = ['Venezuelan', 'Extranjero'];
	} else if (doc_type === 'Passport') {
		allowed_natures = ['Extranjero'];
		frm.set_value('nature_of_the_taxpayer', 'Extranjero');
	} else {
		// Para RIF u otros, permitir todas las opciones
		allowed_natures = RIF_LEGAL_NATURES.concat(RIF_NATURAL_NATURES);
	}

	if (frm.doc.nature_of_the_taxpayer && !allowed_natures.includes(frm.doc.nature_of_the_taxpayer)) {
		frm.set_value('nature_of_the_taxpayer', '');
	}

	frm.set_df_property('nature_of_the_taxpayer', 'options', allowed_natures.join('\n'));
}