/**
 * 
 * @param {object} frm 
 * @param {string} source_field 
 */
function sync_taxpayer_fields(frm, source_field) {

	if (!frm.doc[source_field]) {
		return;
	}
 
	const nature = frm.doc.nature_of_the_taxpayer;
	const person_type = frm.doc.type_of_person;
 
	if (source_field === 'nature_of_the_taxpayer') {
		
		const legal_entities = ["Juridical", "Government", "Communal"];
		const natural_persons = ["Venezuelan", "Extranjero", "Passport"];
 
		if (legal_entities.includes(nature)) {
			
			frm.set_value('type_of_person', 'Domiciled legal entity');

		} else if (natural_persons.includes(nature)) {
			
			frm.set_value('type_of_person', 'Natural person domiciled');
		}
	} else if (source_field === 'type_of_person') {
		
		if (person_type.includes('natural person')) {
			
			if (!['Venezuelan', 'Extranjero', 'Passport'].includes(nature)) {
				frm.set_value('nature_of_the_taxpayer', 'Venezuelan');
			}
		} else if (person_type.includes('legal entity')) {
			
			if (!['Juridical', 'Government', 'Communal'].includes(nature)) {
				frm.set_value('nature_of_the_taxpayer', 'Juridical');
			}
		}
	}
}
 
/**
 *
 * @param {object} frm -
 */
function build_rif(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const tax_id_value = frm.doc.tax_id || '';
 
	if (!nature) {
		
		return;
	}
 
	const letter = nature.charAt(0).toUpperCase();
	const number = tax_id_value.replace(/[^0-9]/g, '');
 
	const full_rif = letter + number;
 
	frm.set_value('tax_id', full_rif);
}

/**
 * 
 * @param {object} frm 
 */
function set_person_type_filter(frm) {
	const nature = frm.doc.nature_of_the_taxpayer;
	const legal_natures = ["Juridical", "Government", "Communal"];
	const natural_natures = ["Venezuelan", "Extranjero", "Passport"];

	let allowed_person_types = [];

	if (legal_natures.includes(nature)) {
		allowed_person_types = ["Domiciled legal entity",
			 "Non-domiciled legal entity"];
			 
	} else if (natural_natures.includes(nature)) {
		allowed_person_types = ["Natural person domiciled", 
			"Non-domiciled natural person"];
	}

	
	if (frm.doc.type_of_person && !allowed_person_types.includes(frm.doc.type_of_person)) {
		frm.set_value('type_of_person', '');
	}


	frm.set_df_property('type_of_person', 'options', allowed_person_types.join('\n'));
}