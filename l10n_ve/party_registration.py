# Copyright (c) 2026, Domina Software and Contributors
# For license information, please see license.txt

"""Registro de una parte a partir de su documento de identidad y su dirección.

Lo que comparten los dos lados de la integración ISP ↔ Contratista cuando registran a una
persona: la contratista al aceptar una orden (crea el Customer) y el ISP al encargar la
instalación (completa el Lead). Son dos apps que no se ven entre sí --corren en sitios
distintos-- y las dos dependen de esta, que además es la dueña de las reglas: la tabla de
letras, los rangos por documento y los catálogos de dirección son de `l10n_ve`.

Nació en `domina_isp_contractor` (`customer_identity.py` y `customer_address.py`) y se mudó
acá para que el ISP no tuviera que copiarlo; los módulos de allá quedaron como
reexportaciones. El diálogo que lo consume también es compartido:
`public/js/utils/party_registration.js`.

Existe porque el silencio salía caro. Los tres campos fiscales que esta app agrega a
Customer son obligatorios, y un Select obligatorio que se deja vacío Frappe lo llena con
**su primera opción**: `RIF` y `Juridical`. Sin esto, cada cliente creado por integración
nacía como persona jurídica --aunque tuviera cédula-- sin un solo error en pantalla, y eso
mueve la retención de ISLR y el documento fiscal que va a HKA.

Dos cosas se deciden acá y no en quien llama:

- **Filtrar contra la meta del sitio.** Campo que no exista o valor que ese Select no
  admita, no se propone: un sitio puede ir por detrás en fixtures, y mandarle una
  naturaleza que su Select todavía no tiene hace fallar el alta con un mensaje sobre
  valores válidos.
- **La dirección se crea o se actualiza, según haya.** Una parte que ya tiene dirección no
  gana otra cada vez que alguien completa el formulario.
"""

import json
import re

import frappe
from l10n_ve.utils import utils as ve_utils
from l10n_ve.utils.utils import (
	IDENTITY_BY_LETTER,
	classify_party_by_document,
	get_tax_id_config,
	split_document_number,
)

# Los campos que esta app agrega a Customer y que hay que decidir. El orden importa: es el
# que ve el operador en el diálogo.
FISCAL_FIELDS = ("type_of_document", "nature_of_the_taxpayer", "type_of_person")

# Los datos de contacto que una parte puede exigir, y cómo se llaman para quien opera:
# «ID Fiscal» no es como nadie nombra al RIF acá.
CONTACT_FIELD_NAMES = {
	"tax_id": "el RIF",
	"mobile_no": "el teléfono",
	"email_id": "el correo",
	"customer_name": "el nombre",
}

# Los campos del Address que se le piden al operador, en orden. El resto --título,
# enlaces-- se resuelve solo: no hay decisión que tomar ahí.
ADDRESS_FIELDS = (
	"address_line1",
	"address_type",
	"country",
	"state",
	"city",
	"county",
	"parish",
	"pincode",
	"phone",
	"email_id",
	"is_primary_address",
	"is_shipping_address",
)

# `address_line1` es un Data, y un Data en Frappe son 140 caracteres. La dirección que
# llega de un formulario es texto libre y puede pasarse: lo que sobra va a la segunda
# línea, que para eso está, en vez de reventar el alta con un error sobre longitudes.
ADDRESS_LINE_MAX_LENGTH = 140

# Debajo de esto, el nombre de una ciudad aparece dentro de demasiadas palabras comunes
# como para fiarse. "Ocumare" sí, "Cua" no.
MIN_CITY_NAME_LENGTH = 4


# =============================================================================
# Identidad
# =============================================================================

def split_document(raw: str | None) -> tuple[str, str]:
	"""(letra, dígitos) del documento. Tolera puntos, guiones y minúsculas."""
	return split_document_number(raw)


def normalized_tax_id(letter: str | None, digits: str | None) -> str:
	"""El documento como lo quiere `validate_tax_id_format`: letra pegada al número."""
	clean = re.sub(r"[^0-9A-Za-z]", "", digits or "").upper()

	return f"{(letter or '').upper()}{clean}"


def _allowed(fieldname: str, party_doctype: str = "Customer") -> set[str]:
	"""Opciones que ese Select admite EN ESTE SITIO, según la meta."""
	field = frappe.get_meta(party_doctype).get_field(fieldname)

	if not field or not field.options:
		return set()

	return {o.strip() for o in field.options.split("\n") if o.strip()}


def document_types_for(letter: str, party_doctype: str = "Customer") -> list[str]:
	"""Qué documentos puede tener esa letra, en el orden en que conviene ofrecerlos.

	No es cosmético: una `J` no puede tener cédula y una `V` sí puede tener las dos --la
	cédula de toda la vida y el RIF de persona natural, que es la cédula con un dígito
	más--. Ofrecer los cuatro tipos siempre invita a elegir uno imposible que después se
	rechaza con un mensaje sobre longitudes.
	"""
	entry = IDENTITY_BY_LETTER.get(letter)

	if not entry:
		return []

	types = [entry["short_document"], entry["long_document"]]
	allowed = _allowed("type_of_document", party_doctype)

	# `dict.fromkeys` y no `set`: quita repetidos sin perder el orden, que acá es el que
	# ve el operador. Para "J" los dos son "RIF" y tiene que quedar una sola opción.
	return [t for t in dict.fromkeys(types) if not allowed or t in allowed]


def classify(raw: str | None, document_type: str | None = None, party_doctype: str = "Customer") -> dict[str, str]:
	"""Los campos fiscales que corresponden a ese documento, filtrados por lo que el sitio admite."""
	proposal = classify_party_by_document(raw, document_type)
	meta = frappe.get_meta(party_doctype)

	classified: dict[str, str] = {}
	discarded: dict[str, str] = {}

	for field, value in proposal.items():
		if not value or not meta.has_field(field):
			continue

		if value in _allowed(field, party_doctype):
			classified[field] = value
		else:
			discarded[field] = value

	if discarded:
		# Omitir un Select obligatorio no lo deja vacío: Frappe le pone su PRIMERA
		# opción --`RIF`, `Juridical`--, que es justo el silencio que este módulo
		# existe para evitar. No se manda el valor (rompería el alta), pero que el
		# sitio esté por detrás en fixtures tiene que verse.
		frappe.log_error(
			"Clasificación fiscal incompleta",
			f"{party_doctype} no admite {discarded} en este sitio: el alta va a tomar "
			"el valor por defecto de cada Select. Sincronizar fixtures.",
		)

	return classified


def letter_choices(party_doctype: str = "Customer") -> list[dict]:
	"""La tabla para el diálogo: letra, qué significa y qué implica.

	Se manda entera al navegador para que el resumen («se registrará como…») salga de
	esta misma tabla y no de una copia en JavaScript que se desincronice.
	"""
	allowed = {field: _allowed(field, party_doctype) for field in FISCAL_FIELDS}
	allowed["customer_type"] = _allowed("customer_type", party_doctype)

	choices = []

	for letter, entry in IDENTITY_BY_LETTER.items():
		types = document_types_for(letter, party_doctype)

		choices.append(
			{
				"letter": letter,
				"label": entry["label"],
				"short_document": entry["short_document"],
				"long_document": entry["long_document"],
				"document_types": types,
				# Los rangos de dígitos de cada documento, para que el resumen del diálogo
				# elija igual que el servidor. Salen de `get_tax_id_config`, que es donde
				# viven: una copia en el navegador se desincroniza.
				"document_ranges": {
					t: get_tax_id_config(t, entry["nature_of_the_taxpayer"]) for t in types
				},
				**{
					field: entry[field]
					for field in ("nature_of_the_taxpayer", "type_of_person", "customer_type")
					if entry[field] in allowed.get(field, set())
				},
			}
		)

	return choices


def site_classifies(party_doctype: str = "Customer") -> bool:
	"""Si este sitio le exige clasificación fiscal a esa parte."""
	return frappe.get_meta(party_doctype).has_field("type_of_document")


def required_contact_fields(party_doctype: str = "Customer") -> dict[str, bool]:
	"""Qué exige ESTE sitio de los datos de contacto: lo que su alta va a rechazar."""
	meta = frappe.get_meta(party_doctype)

	return {
		field: bool((meta.get_field(field) or frappe._dict()).get("reqd"))
		for field in CONTACT_FIELD_NAMES
	}


def missing_contact_text(values: dict | None, party_doctype: str = "Customer") -> str:
	"""«el RIF ni el teléfono», o cadena vacía: lo que ese doctype exige y `values` no trae.

	Se pregunta por la **meta**, no por una lista fija: cada sitio decide qué exige. Y no
	se parsea el mensaje de Frappe, que cambia entre versiones y viene traducido a medias.
	"""
	required = required_contact_fields(party_doctype)
	missing = [
		name
		for field, name in CONTACT_FIELD_NAMES.items()
		if required.get(field) and not (values or {}).get(field)
	]

	return " ni ".join(missing)


# =============================================================================
# Dirección
# =============================================================================

def normalize_address_line(text: str | None) -> str:
	"""Deja la dirección en una línea.

	El salto no es cosmético: el título del Address sale de la primera línea y el nombre
	del documento sale del título, así que un salto termina metido dentro del nombre --y
	en la URL--.
	"""
	return re.sub(r"\s+", " ", text or "").strip()


def split_address_line(text: str | None) -> tuple[str, str]:
	"""Parte la dirección en las dos líneas del Address, cortando por palabras."""
	line = normalize_address_line(text)

	if len(line) <= ADDRESS_LINE_MAX_LENGTH:
		return line, ""

	cut = line.rfind(" ", 0, ADDRESS_LINE_MAX_LENGTH)

	# Sin espacios donde cortar --una sola palabra larguísima-- se corta a lo bruto: es
	# preferible a perder la dirección entera.
	if cut <= 0:
		cut = ADDRESS_LINE_MAX_LENGTH

	return line[:cut].strip(), line[cut:].strip()[:ADDRESS_LINE_MAX_LENGTH]


def guess_location(text: str | None) -> dict[str, str]:
	"""Busca en el texto libre una ciudad conocida, y de ahí saca el estado.

	Existe porque `city` es un Link a `VE City` obligatorio, y son cientos de opciones. La
	dirección escrita a mano suele traer la ciudad --"Guarenas, Terrazas de Vicente Emilio
	Sojo"--: hacerla buscar en esa lista es trabajo que ya está hecho. Y de la ciudad sale
	el estado, que a su vez acota los municipios.

	Devuelve `{}` si no hay ninguna o si hay **varias**: adivinar mal es peor que no
	adivinar, porque una ciudad ya rellenada es una que nadie vuelve a mirar.
	"""
	if not text or not frappe.db.exists("DocType", "VE City"):
		return {}

	# Se comparan palabras enteras y no subcadenas: "Cua" está dentro de "Cuadra" y de
	# media docena de direcciones más.
	words = {w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text)}

	if not words:
		return {}

	found = [
		city
		for city in frappe.get_all("VE City", fields=["name", "city", "state"])
		if city.city and len(city.city) >= MIN_CITY_NAME_LENGTH and city.city.lower() in words
	]

	if len(found) != 1:
		return {}

	return {"city": found[0].name, "state": found[0].state or ""}


def address_field_meta() -> list[dict]:
	"""Cómo es cada campo de dirección EN ESTE SITIO.

	Se lee de la meta y no se codifica porque el diálogo se arma con esto: si un campo
	deja de existir o cambia de tipo, el diálogo lo sigue sin que nadie se acuerde.
	"""
	meta = frappe.get_meta("Address")
	fields = []

	for fieldname in ADDRESS_FIELDS:
		field = meta.get_field(fieldname)

		if not field:
			continue

		fields.append(
			{
				"fieldname": fieldname,
				"fieldtype": field.fieldtype,
				"options": field.options,
				"reqd": bool(field.reqd),
			}
		)

	return fields


def form_options(party_doctype: str = "Customer") -> dict:
	"""Lo que el diálogo compartido necesita saber del sitio, sin nada de la parte.

	Quien llama le suma lo precargado --nombre, documento, contacto, dirección-- que sale
	del documento que tenga enfrente: la orden en la contratista, el Lead en el ISP.
	"""
	return {
		"letters": letter_choices(party_doctype),
		"classifies": site_classifies(party_doctype),
		"address_fields": address_field_meta(),
		"required": required_contact_fields(party_doctype),
		"country": frappe.db.get_default("country"),
	}


def party_address(party_doctype: str, party_name: str) -> dict | None:
	"""La dirección principal de una parte --o la primera enlazada--, con sus campos."""
	linked = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": party_doctype, "link_name": party_name},
		pluck="parent",
	)

	if not linked:
		return None

	rows = frappe.get_all(
		"Address",
		filters={"name": ["in", linked]},
		fields=["name", "address_line2", *ADDRESS_FIELDS],
		order_by="is_primary_address desc, creation asc",
		limit=1,
	)

	return rows[0] if rows else None


def address_text(address: dict | None) -> str | None:
	"""La dirección en una línea, para viajar como texto o mostrarse en un formulario."""
	if not address:
		return None

	return ", ".join(x for x in (address.get("address_line1"), address.get("address_line2")) if x) or None


def build_party_address(party_doctype: str, party_name: str, party_title: str | None, values: dict) -> str | None:
	"""Deja a la parte con esa dirección: actualiza la que tenga o crea una y la enlaza.

	Devuelve el nombre del `Address`, o `None` si no había nada que guardar. Si algo falla
	lanza: quien llama decide qué hacer --en el alta de la contratista es avisar sin perder
	el cliente; en el encargo del ISP es no encargar hasta que la dirección esté bien--.

	Para crear se hacen los dos pasos que hace el diálogo «Agregar Dirección» de la ficha,
	en este orden: crear la dirección suelta y enlazarla después. No es un detalle de
	estilo --el `validate` del Address rechaza cosas distintas según haya enlaces o no--.
	Un detalle que se hereda gratis: la dirección se retitula con el ID de la parte apenas
	tiene enlaces (`overrides/address.py`), así que el título no se decide acá.
	"""
	line, rest = split_address_line(values.get("address_line1"))

	if not line:
		return None

	fields = {
		"address_line1": line,
		"address_line2": rest or None,
		**{
			field["fieldname"]: values.get(field["fieldname"])
			for field in address_field_meta()
			if field["fieldname"] != "address_line1" and values.get(field["fieldname"]) is not None
		},
	}

	existing = party_address(party_doctype, party_name)

	if existing:
		doc = frappe.get_doc("Address", existing["name"])
		doc.update(fields)
		doc.flags.skip_link_address = True
		doc.save(ignore_permissions=True)
		name = doc.name
	else:
		name = ve_utils.create_independent_address(json.dumps(fields))
		ve_utils.link_address_to_party(name, party_doctype, party_name)

	if party_doctype == "Customer":
		# `set_value` y no `save`: el Customer ya pasó por su validación y volver a
		# guardarlo entero sólo para apuntar la dirección puede fallar por algo que no
		# tiene nada que ver --y ahí ya habría un Address huérfano--.
		frappe.db.set_value("Customer", party_name, "customer_primary_address", name, update_modified=False)

	return name
