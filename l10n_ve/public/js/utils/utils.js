const RIF_LEGAL_NATURES = ["Juridical", "Government", "Communal"];
const RIF_NATURAL_NATURES = ["Venezuelan", "Extranjero", "Passport"];

/**
 * @param {string} document_type
 * @param {string} nature
 * @returns {number|Array<number>}
 */
function get_tax_id_config(document_type, nature) {
  const config = {
    RIF: { default: 9 },
    Cedula: {
      default: [7, 8],
    },
    Passport: {
      default: [8, 9],
    },
  };

  const doc_config = config[document_type] || config["RIF"];
  return doc_config[nature] || doc_config.default;
}

/**
 * @param {object} frm
 * @param {string} fieldname
 */
function handle_field_change(frm, fieldname) {
  if (fieldname === "type_of_document") {
    frm.set_value("nature_of_the_taxpayer", "");
    frm.set_value("type_of_person", "");
  }

  set_nature_filter(frm);

  if (fieldname === "nature_of_the_taxpayer") {
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
  const tax_id_value = frm.doc.tax_id || "";

  if (!nature || !document_type) {
    return;
  }

  const length_config = get_tax_id_config(document_type, nature);
  const max_length = Array.isArray(length_config)
    ? length_config[1]
    : length_config;
  let full_tax_id = "";

  if (document_type === "Passport") {
    let passport_number = tax_id_value
      .replace(/[^a-zA-Z0-9]/g, "")
      .toUpperCase();

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
    let number_part = tax_id_value.replace(/^[a-zA-Z]*/, "").replace(/\D/g, "");

    if (max_length && number_part.length > max_length) {
      number_part = number_part.substring(0, max_length);
    }
    full_tax_id = letter + number_part;
  }

  frm.set_value("tax_id", full_tax_id);
}

/**
 * Construye el RIF para la Compañía.
 * @param {object} frm -
 */
function build_rif(frm) {
  const nature = frm.doc.nature_of_the_taxpayer;
  const tax_id_value = frm.doc.tax_id || "";

  if (!nature) {
    return;
  }

  const letter = nature.charAt(0).toUpperCase();
  let number_part = tax_id_value.replace(/^[a-zA-Z]*/, "").replace(/\D/g, "");

  if (number_part.length > 9) {
    number_part = number_part.substring(0, 9);
  }

  frm.set_value("tax_id", letter + number_part);
}

/**
 *
 * @param {object} frm
 */
function set_person_type_filter(frm) {
  const nature = frm.doc.nature_of_the_taxpayer;
  const doc_type = frm.doc.type_of_document;

  let allowed_person_types = [];

  if (doc_type === "Cedula" || doc_type === "Passport") {
    allowed_person_types = [
      "Natural person domiciled",
      "Non-domiciled natural person",
    ];
  } else if (RIF_LEGAL_NATURES.includes(nature)) {
    allowed_person_types = [
      "Domiciled legal entity",
      "Non-domiciled legal entity",
    ];
  } else if (RIF_NATURAL_NATURES.includes(nature)) {
    allowed_person_types = [
      "Natural person domiciled",
      "Non-domiciled natural person",
    ];
  }

  if (
    frm.doc.type_of_person &&
    !allowed_person_types.includes(frm.doc.type_of_person)
  ) {
    frm.set_value("type_of_person", "");
  }

  frm.set_df_property(
    "type_of_person",
    "options",
    allowed_person_types.join("\n")
  );
}

/**
 * Filtra las opciones de Naturaleza del Contribuyente según el Tipo de Documento.
 * @param {object} frm
 */
function set_nature_filter(frm) {
  const doc_type = frm.doc.type_of_document;
  let allowed_natures = [];

  if (doc_type === "Cedula") {
    allowed_natures = ["Venezuelan", "Extranjero"];
  } else if (doc_type === "Passport") {
    allowed_natures = ["Extranjero"];
    frm.set_value("nature_of_the_taxpayer", "Extranjero");
  } else {
    // Para RIF u otros, permitir todas las opciones
    allowed_natures = RIF_LEGAL_NATURES.concat(RIF_NATURAL_NATURES);
  }

  if (
    frm.doc.nature_of_the_taxpayer &&
    !allowed_natures.includes(frm.doc.nature_of_the_taxpayer)
  ) {
    frm.set_value("nature_of_the_taxpayer", "");
  }

  frm.set_df_property(
    "nature_of_the_taxpayer",
    "options",
    allowed_natures.join("\n")
  );
}


function validate_cedula(frm, fieldname) {
	const value = frm.doc[fieldname];
	if (!value) return;

	let cleanedValue = value.toUpperCase().replace(/[^VE\d]/g, '');
	let firstChar = cleanedValue.charAt(0);
	let restOfChars = cleanedValue.substring(1).replace(/\D/g, '');

	if (firstChar !== 'V' && firstChar !== 'E') {
		frm.set_value(fieldname, '');
		frappe.throw({
			title: __("Formato de Cédula Inválido"),
			message: __("El primer carácter de la cédula debe ser 'V' o 'E'."),
			indicator: "red"
		});
		return;
	}

	const length_config = get_tax_id_config('Cedula');
	const min_length = length_config[0];
	const max_length = length_config[1];

	if (restOfChars.length > max_length) {
		restOfChars = restOfChars.substring(0, max_length);
	}

	const final_value = firstChar + restOfChars;

	if (frm.doc[fieldname] !== final_value) {
		frm.set_value(fieldname, final_value);
	}
}


function get_address_link(frm) {
  const field_primary_address = {
    Company: "custom_company_primary_address",
    Supplier: "supplier_primary_address",
    Customer: "customer_primary_address",
  };

  const fieldname_address_link = field_primary_address[frm.doctype];

  if (!fieldname_address_link) {
    return;
  }

  if (frm.is_new()) {
    frm.toggle_display(fieldname_address_link, false);
    return;
  }

  frappe
    .call({
      method: "l10n_ve.overrides.address.get_address_link_count",
      args: {
        link_doctype: frm.doctype,
        link_name: frm.doc.name,
      },
    })
    .then((r) => {
      frm.toggle_display(fieldname_address_link, r.message > 0);
    });
}

function hidden_address_contact(frm) {
  const field_primary_address = {
    Company: "custom_company_primary_address",
    Supplier: "supplier_primary_address",
    Customer: "customer_primary_address",
  };

  const field_primary_contact = {
    Supplier: "supplier_primary_contact",
    Customer: "customer_primary_contact",
  };

  const fieldname_address_link = field_primary_address[frm.doctype];
  const fieldname_contact_link = field_primary_contact[frm.doctype];

  if (fieldname_address_link) {
    frm.toggle_display(fieldname_address_link, false);
  }

  if (fieldname_contact_link) {
    frm.toggle_display(fieldname_contact_link, false);
  }
}

function realtime_numeric_validation(frm, fieldname) {
  const input = frm.get_field(fieldname).$input;
  if (!input) return;

  input.on("input", function () {
    const value = $(this).val();
    const numeric_value = value.replace(/\D/g, "");

    if (value !== numeric_value) {
      frm.set_value(fieldname, numeric_value, false);
      frm.get_field(fieldname).refresh();
    }
  });
}

function realtime_numeric_validation(frm, fieldname) {
  const input = frm.get_field(fieldname).$input;
  if (!input) return;

  input.on("input", function () {
    const value = $(this).val();
    const numeric_value = value.replace(/\D/g, "");

    if (value !== numeric_value) {
      frm.set_value(fieldname, numeric_value, false);
      frm.get_field(fieldname).refresh();
    }
  });
}

function add_address_button(frm) {
  if (frm.is_new() && !frm.doc.customer_primary_address || !frm.custom_buttons["Agregar Dirección"]) {
    frm.add_custom_button(__("Agregar Dirección"), () => {
      _get_address_dialog(frm).show();
    });
  }
}

function _get_address_dialog(frm) {
  const dialog = new frappe.ui.Dialog({
    title: __("Nueva Dirección"),
    fields: [
      {
        label: __("Dirección Línea 1"),
        fieldname: "address_line1",
        fieldtype: "Data",
        reqd: 1,
      },
      {
        label: __("Tipo de Dirección"),
        fieldname: "address_type",
        fieldtype: "Select",
        options: "Billing\nShipping\nOffice\nPersonal\nPlant\nWarehouse",
        default: "Billing",
        reqd: 1,
      },
      {
        label: __("País"),
        fieldname: "country",
        fieldtype: "Link",
        options: "Country",
        default: frappe.defaults.get_user_default("country"),
        reqd: 1,
      },
      {
        label: __("Estado/Provincia"),
        fieldname: "state",
        fieldtype: "Link",
        options: "VE State",
        default: null,
        reqd: 1,
      },
      {
        label: __("Ciudad/Pueblo"),
        fieldname: "city",
        fieldtype: "Link",
        options: "VE City",
        default: null,
        reqd: 1,
      },
      {
        label: __("Municipio"),
        fieldname: "county",
        fieldtype: "Link",
        options: "VE Municipality",
        default: null,
        reqd: 1,
      },
      {
        label: __("Parish"),
        fieldname: "parish",
        fieldtype: "Link",
        options: "VE Parish",
        default: null,
      },
      {
        label: __("Código Postal"),
        fieldname: "pincode",
        fieldtype: "Data",
        default: null,
      },
      {
        label: __("Es Dirección Principal"),
        fieldname: "is_primary_address",
        fieldtype: "Check",
        default: 0,
      },
      {
        label: __("Es Dirección de Envío"),
        fieldname: "is_shipping_address",
        fieldtype: "Check",
        default: 0,
      },
    ],
    primary_action_label: __("Guardar"),
    primary_action: (values) => {
      values.doctype = "Address";

      frappe.call({
        method: "l10n_ve.utils.utils.create_independent_address",
        args: {
          address_values: values,
        },
        callback: (r) => {
          if (!r.exc && r.message) {
            frappe.msgprint(__("Dirección creada exitosamente."));
            dialog.hide();

            const address_field =
              frm.doctype === "Supplier"
                ? "supplier_primary_address"
                : "customer_primary_address";
            frm.set_value(address_field, r.message);
            frm.toggle_display(address_field, true);
            frappe.show_alert({
              message: __(
                "La nueva dirección ha sido asignada. Se vinculará al guardar el documento."
              ),
              indicator: "green",
            });
          }
        },
        error: (err) => {
          frappe.msgprint(__("Ocurrió un error al crear la dirección."));
          console.error(err);
        },
      });
    },
  });

  dialog.get_field("state").get_query = function () {
    return {
      filters: { country: dialog.get_value("country") },
    };
  };
  dialog.get_field("city").get_query = function () {
    return { filters: { state: dialog.get_value("state") } };
  };
  dialog.get_field("county").get_query = function () {
    return { filters: { state: dialog.get_value("state") } };
  };
  dialog.get_field("parish").get_query = function () {
    return { filters: { municipality: dialog.get_value("county") } };
  };

  dialog.fields_dict.state.df.onchange = () => {
    dialog.set_value("city", "");
    dialog.set_value("county", "");
    dialog.set_value("parish", "");
  };
  dialog.fields_dict.county.df.onchange = () => {
    dialog.set_value("parish", "");
  };

  return dialog;
}
