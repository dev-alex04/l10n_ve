# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt
"""Inyección declarativa de links y accesos directos de l10n_ve en workspaces ajenos.

Los workspaces *Accounting*, *Financial Reports*, *Selling* y *Buying* son de ERPNext.
l10n_ve necesita colgar cosas suyas adentro, pero el dueño sigue siendo ERPNext: cada
`bench migrate` que trae un JSON nuevo borra las filas hijas del workspace y las repone
desde el archivo (`import_file.delete_old_doc` + `insert`), así que la inyección tiene que
volver a aplicarse — y tiene que ser inocua cuando no hay nada que aplicar.

Qué declara cada manifiesto (un JSON por workspace destino, en esta misma carpeta):

    {
      "targets": ["Accounting", "Accounts"],      # candidatos; se usa el 1º que exista
      "cards": [{
          "label": "Configuración Venezuela",     # identidad de la tarjeta Y card_name en `content`
          "aliases": ["Comprobantes"],            # labels históricos a adoptar (renombrar, no duplicar)
          "owned": true,                          # true = la tarjeta es nuestra
          "col": 4,                               # sólo si owned; ancho del bloque en `content`
          "place": {"after_card": "Payments"},    # sólo se aplica AL CREAR la tarjeta
          "insert": {"after_link": "Blanket Order"},   # sólo si NO owned: ancla del splice
          "links": [{"label": "...", "link_to": "...", "link_type": "DocType",
                     "is_query_report": 0, "onboard": 0}]
      }],
      "shortcuts": [{"label": "...", "link_to": "...", "type": "DocType",
                     "aliases": ["label viejo "], "color": "Blue", "col": 3}]
    }

Invariantes que este módulo sostiene (cada uno nació de un daño medido en producción):

1. **Sólo se borra lo declarado.** La clave de propiedad de un link es
   `(link_type, casefold(link_to))` y sale del manifiesto; la de un acceso directo es
   `(type, casefold(link_to))`. Todo lo demás —de ERPNext o del usuario— es intocable.
   El predecesor (`setup._dedupe_workspace_links`) colapsaba por `(type, link_to, label)`
   sin mirar bajo qué Card Break estaba la fila, y le borró a ERPNext el segundo
   `Accounting Dimension`, que el JSON pristino trae DOS veces a propósito (bajo
   *Cost Center and Budgeting* y bajo *Accounting Masters*).

2. **Idempotencia real.** Se compara una huella del documento antes y después; si no
   cambió nada, no hay `save()` — y sin `save()` no hay fila en `tabVersion`, no cambia
   `modified` y no se re-exporta ningún JSON. El bug anterior en *Selling* era comparar un
   string crudo contra un set ya normalizado (`"VE Sales Credit Note" in {"ve sales credit
   note"}`): nunca coincidía, así que agregaba el par en cada migrate. Acá se normaliza
   **siempre en los dos lados**.

3. **`idx` renumerado 1..N al final, siempre.** `workspace.set("links", ...)` conserva los
   `idx` viejos y los `append` posteriores reciclan números; Frappe carga las hijas con
   `order_by="idx asc"` **sin desempate**, así que los empates hacen la agrupación no
   determinista. En *Accounting* había cuatro pares empatados en 64-67.

4. **El Card Break viaja pegado a sus links.** En *Financial Reports* el Card Break
   `Reportes Venezuela` había quedado en `idx=37` y sus 7 reportes en 25–31 (o sea, antes):
   los 7 se renderizaban dentro de *Other Reports* y la tarjeta propia quedaba vacía, que
   `desktop.get_links()` descarta (`if new_items:`).

5. **`link_count` no miente.** Es lo que usa `clean_up()`
   (`frappe/desk/desktop.py`) con `del original_page.links[i : i + link_count + 1]` cuando
   el usuario guarda el workspace desde la UI: un valor inflado borra el tramo equivocado.
   Se recalcula en las tarjetas propias, y en las ajenas **sólo si el valor guardado no es
   cero y no coincide** con los links reales (un 0 no es peligroso: `build_links_table_from_card`
   lo recuenta solo).

6. **Las dos representaciones se sincronizan**: la tabla hija `links`/`shortcuts` y el campo
   JSON `content` (bloques `card`/`shortcut`). El `data.links` inline que el código viejo
   escribía en los bloques `card` **no se renderiza** (el front resuelve por label contra
   `get_link_groups()`), así que se borra.
"""

import copy
import hashlib
import json
import os
from collections import Counter
from contextlib import contextmanager

import frappe
from frappe.utils import cint

MANIFEST_DIR = os.path.dirname(os.path.abspath(__file__))

# type de la fila hija -> DocType donde vive el destino, para la guarda de existencia.
LINK_TARGET_DOCTYPE = {"DocType": "DocType", "Page": "Page", "Report": "Report"}
SHORTCUT_TARGET_DOCTYPE = {
	"DocType": "DocType",
	"Page": "Page",
	"Report": "Report",
	"Dashboard": "Dashboard",
}

# Campos del manifiesto que se copian a la fila hija.
#
# En los LINKS el manifiesto es autoritativo: lo que no declara se restablece al default, así
# que una fila adoptada no arrastra un `onboard=1` viejo (spotlight azul) ni un `only_for`
# heredado. Los ints van con su default explícito para que no oscilen entre NULL y 0.
LINK_OPTIONAL_DEFAULTS = {
	"onboard": 0,
	"is_query_report": 0,
	"only_for": None,
	"dependencies": None,
	"icon": None,
	"description": None,
}
LINK_OPTIONAL_FIELDS = tuple(LINK_OPTIONAL_DEFAULTS)

# En los SHORTCUTS es al revés: sólo se escribe lo declarado. `color`, `doc_view` y
# `stats_filter` son cosas que el usuario retoca desde la UI y pisárselas en cada migrate
# sería hostil; los manifiestos declaran color sólo donde el color ES la decisión (Selling).
SHORTCUT_OPTIONAL_FIELDS = ("color", "doc_view", "stats_filter", "url", "format", "icon", "restrict_to_domain")

# La huella se deriva de las constantes de arriba: si mañana alguien agrega un campo al
# manifiesto y no lo suma acá, el reconciliador lo escribiría y nunca lo vería cambiar
# (no-op permanente y silencioso). Derivándola, no puede volver a divergir.
_LINK_FINGERPRINT_FIELDS = ("type", "label", "link_type", "link_to", "hidden", "link_count", "idx", "name")
_SHORTCUT_FINGERPRINT_FIELDS = ("type", "label", "link_to", "idx", "name")
_INT_FIELDS = frozenset({"hidden", "link_count", "idx", "onboard", "is_query_report"})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def norm(value: str | None) -> str:
	"""Clave de comparación de un link: sin espacios y sin distinguir mayúsculas.

	Los nombres de DocType/Report se comparaban con `==` de Python, que SÍ distingue
	mayúsculas, contra strings escritos a mano. Dos tipeos —"Ve Branch" por "VE Branch" y
	"Sales Book" por "Sales book"— hacían que el filtro de quitado no encontrara el link
	viejo: sobrevivía, se agregaba otro, y en cada migración se sumaba uno más. Medido en
	producción: 18 copias de "Sucursales" en Accounting y 10 de "Libro de Ventas" en
	Financial Reports.
	"""
	return (value or "").strip().casefold()


def _get(row, field):
	"""Lee un campo de una fila hija, que puede ser un Document o todavía un dict."""
	if isinstance(row, dict):
		return row.get(field)
	return getattr(row, field, None)


def _set(row, field, value):
	if isinstance(row, dict):
		row[field] = value
	else:
		setattr(row, field, value)


def _link_key(row) -> tuple:
	return (norm(_get(row, "link_type")), norm(_get(row, "link_to")))


def _shortcut_key(row) -> tuple:
	"""Identidad de un acceso directo.

	Ojo con `type="URL"`: ahí `link_to` es NULL, así que usar `link_to` a secas colapsa TODOS
	los shortcuts URL en la misma clave `("url", "")`. Medido: declarar un shortcut URL en
	Accounting adoptaba y reescribía el `Learn Accounting` de ERPNext en vez de agregar uno
	nuevo. En URL la identidad es la propia `url`.
	"""
	kind = norm(_get(row, "type"))
	if kind == "url":
		return (kind, norm(_get(row, "url")))
	return (kind, norm(_get(row, "link_to")))


def _stable_id(workspace_name: str, kind: str, label: str) -> str:
	"""`id` determinista para un bloque de `content`.

	El código viejo usaba `random.choices`, así que dos sites producían JSON distintos y una
	re-creación generaba un id nuevo (diff garantizado). Los bloques que YA tienen id no se
	tocan.
	"""
	raw = f"{workspace_name}:{kind}:{label}".encode()
	return hashlib.md5(raw, usedforsecurity=False).hexdigest()[:10]


@contextmanager
def no_file_export():
	"""Impide que `Workspace.on_update` re-exporte el JSON al árbol de la app dueña.

	`disable_saving_as_public()` (frappe/desk/doctype/workspace/workspace.py) devuelve True
	con `in_patch`, que es el mismo switch que usa `sync_all()`. Sin esto, correr el
	reconciliador a mano en una laptop con `developer_mode=1` ensucia
	`apps/erpnext/.../accounting.json` — que es exactamente como se ensuciaron tres de los
	cuatro. En un `bench migrate` real `in_migrate` ya cubre lo mismo.
	"""
	previous = frappe.flags.in_patch
	frappe.flags.in_patch = True
	try:
		yield
	finally:
		frappe.flags.in_patch = previous


def _target_exists(target_doctype: str | None, name: str | None) -> bool:
	"""Guarda de existencia: si el DocType/Report/Page destino no está, el link se omite."""
	if not target_doctype:
		return True
	if not name:
		return False
	return bool(frappe.db.exists(target_doctype, name))


def _requirement_met(declaration: dict) -> bool:
	requires = declaration.get("requires")
	if not requires:
		return True
	doctype, _, name = requires.partition(":")
	return bool(frappe.db.exists(doctype.strip(), name.strip()))


# ---------------------------------------------------------------------------
# lectura de manifiestos
# ---------------------------------------------------------------------------


def load_manifests() -> list[dict]:
	"""Devuelve los manifiestos de la carpeta, en orden alfabético de archivo.

	`encoding="utf-8-sig"` a propósito: este repo convive con archivos guardados por editores
	de Windows y un BOM al frente haría estallar el `json.load` — y con él, todo el
	`bench migrate` si el llamador no lo contuviera (ver `apply_all`).
	"""
	manifests = []
	for filename in sorted(os.listdir(MANIFEST_DIR)):
		if not filename.endswith(".json"):
			continue
		path = os.path.join(MANIFEST_DIR, filename)
		try:
			with open(path, encoding="utf-8-sig") as handle:
				manifest = json.load(handle)
		except Exception:
			# Un archivo ilegible se salta solo: no tiene por qué llevarse puestos a los otros
			# tres, y muchísimo menos al `bench migrate`.
			frappe.log_error(frappe.get_traceback(), f"workspace_injection: {filename}")
			print(f"l10n_ve workspaces: no se pudo leer {filename}; ver Error Log.")
			continue
		manifest["_source"] = filename
		manifests.append(manifest)
	return manifests


def assert_unique_declarations(manifest: dict) -> None:
	"""Lint del manifiesto: una clave declarada dos veces nunca converge.

	La identidad de un link es `(link_type, casefold(link_to))` y la de un acceso directo
	`(type, casefold(link_to|url))`. Si la misma clave aparece dos veces:

	* en links, la 2ª tarjeta recrea la fila en **cada** corrida (un `name` nuevo y un
	  `modified` por migrate, para siempre);
	* en shortcuts, `doc.shortcuts` queda con N+1 filas contra N en la BD, la huella nunca
	  converge y el label declarado primero desaparece de la tabla pero deja su bloque
	  huérfano en `content`.

	Ninguna de las dos cosas se puede reparar en caliente, así que se rechaza el manifiesto
	entero. Se llama desde `apply_manifest`, o sea **dentro** del savepoint de `apply_all`:
	el manifiesto roto se saltea y los otros tres se aplican igual.
	"""
	seen: set[tuple] = set()
	for card in manifest.get("cards", []):
		for declaration in card.get("links", []):
			key = _link_key(declaration)
			if key in seen:
				raise ValueError(f"{manifest.get('_source')}: link {key} declarado dos veces")
			seen.add(key)

	seen = set()
	for declaration in manifest.get("shortcuts", []):
		key = _shortcut_key(declaration)
		if key in seen:
			raise ValueError(f"{manifest.get('_source')}: shortcut {key} declarado dos veces")
		seen.add(key)


def _first_existing_workspace(targets: list[str]) -> str | None:
	for candidate in targets or []:
		if frappe.db.exists("Workspace", candidate):
			return candidate
	return None


# ---------------------------------------------------------------------------
# agrupación (misma semántica que Workspace.get_link_groups)
# ---------------------------------------------------------------------------


def parse_groups(doc) -> list[list]:
	"""Recorre `links` en orden de `idx` y abre una tarjeta en cada Card Break.

	Devuelve `[[card_break_row | None, [link_rows]], ...]`. El primer grupo (con Card Break
	`None`) recoge los links sueltos que pudieran existir antes del primer Card Break.
	"""
	groups: list[list] = [[None, []]]
	for row in doc.links:
		if _get(row, "type") == "Card Break":
			groups.append([row, []])
		else:
			groups[-1][1].append(row)
	return groups


def flatten_groups(groups: list[list]) -> list:
	flat = []
	for card_break, links in groups:
		if card_break is not None:
			flat.append(card_break)
		flat.extend(links)
	return flat


def _find_groups(groups: list[list], labels: list[str]) -> list[list]:
	"""Todas las tarjetas que matchean el label o alguno de sus aliases, en orden de tabla.

	Devuelve una lista, no la primera coincidencia: si por cualquier vía coexisten la tarjeta
	y su alias (p. ej. `Comprobantes` y `Tributos`), quedarse con la primera dejaba a la otra
	vacía **para siempre** — el reconciliador no volvía a mirarla nunca. Se fusionan.
	"""
	wanted = {norm(label) for label in labels}
	return [g for g in groups if g[0] is not None and norm(_get(g[0], "label")) in wanted]


def _insert_group(groups: list[list], group: list, place: dict | None) -> None:
	"""Coloca una tarjeta recién creada. Sólo se aplica AL CREAR.

	Si el usuario reordena tarjetas desde la UI, Frappe reconstruye la tabla `links` desde el
	orden del `content`; reimponer la posición en cada migrate sería una guerra con el
	usuario. La posición es una decisión de una sola vez.
	"""
	place = place or {}
	anchor = place.get("after_card")
	if anchor:
		wanted = norm(anchor)
		for index, existing in enumerate(groups):
			card_break = existing[0]
			if card_break is not None and norm(_get(card_break, "label")) == wanted:
				groups.insert(index + 1, group)
				return
	groups.append(group)


def _splice(existing: list, rows: list, after_link: str | None) -> list:
	"""Inserta `rows` dentro de una tarjeta ajena, respetando el orden de ERPNext."""
	if not rows:
		return existing
	if after_link:
		wanted = norm(after_link)
		for index, row in enumerate(existing):
			if norm(_get(row, "link_to")) == wanted:
				return existing[: index + 1] + rows + existing[index + 1 :]
	return existing + rows


# ---------------------------------------------------------------------------
# reconciliación de links
# ---------------------------------------------------------------------------


def _new_link_row(declaration: dict) -> dict:
	row = {
		"type": "Link",
		"label": declaration["label"],
		"link_type": declaration["link_type"],
		"link_to": declaration["link_to"],
		"hidden": 0,
	}
	_apply_link_fields(row, declaration)
	return row


def _apply_link_fields(row, declaration: dict) -> None:
	"""Lleva la fila a lo que dice el manifiesto: label, caja exacta del `link_to` y opcionales.

	Sobre nuestras propias filas el manifiesto es autoritativo, así que los opcionales que NO
	declara vuelven a su default en vez de quedarse como estaban: una fila adoptada con
	`onboard=1` conservaba el spotlight azul del onboarding (`desk/desktop.py`) sin que nada
	lo declarara, y no había forma de sacárselo desde el manifiesto.
	"""
	_set(row, "type", "Link")
	_set(row, "label", declaration["label"])
	_set(row, "link_type", declaration["link_type"])
	_set(row, "link_to", declaration["link_to"])
	_set(row, "hidden", cint(_get(row, "hidden")))
	for field, default in LINK_OPTIONAL_DEFAULTS.items():
		value = declaration.get(field, default)
		_set(row, field, cint(value) if field in _INT_FIELDS else value)


def _declared_link_rows(card: dict) -> list[dict]:
	"""Los links de la tarjeta que pasan las guardas de existencia."""
	usable = []
	for declaration in card.get("links", []):
		if not _requirement_met(declaration):
			continue
		target_doctype = LINK_TARGET_DOCTYPE.get(declaration.get("link_type"))
		if not _target_exists(target_doctype, declaration.get("link_to")):
			continue
		usable.append(declaration)
	return usable


def reconcile_links(doc, manifest: dict, reclaimed: list | None = None) -> set[str]:
	"""Devuelve los labels (normalizados) de las tarjetas propias que quedaron vivas.

	`reclaimed` (opcional) se rellena con los links que se sacaron de una tarjeta ajena que no
	es la declarada como destino. Es el único caso en que el reconciliador le mueve una fila a
	ERPNext, y por eso se reporta en vez de hacerse en silencio.
	"""
	groups = parse_groups(doc)

	# --- resolución de tarjetas destino ----------------------------------
	# Una tarjeta ajena que no existe no es actionable: sus links no entran en OWNED, así
	# que ni se extraen ni se pierden.
	resolved: list[list] = []
	for card in manifest.get("cards", []):
		labels = [card["label"], *card.get("aliases", [])]
		matches = _find_groups(groups, labels)
		group = matches[0] if matches else None
		if card.get("owned"):
			# Homónimas o alias coexistente: se fusionan en la primera y las sobrantes
			# desaparecen. Quedarse sólo con la primera dejaba a las otras vacías para
			# siempre, porque el reconciliador no las volvía a mirar nunca.
			for extra in matches[1:]:
				group[1].extend(extra[1])
				groups[:] = [g for g in groups if g is not extra]
		resolved.append([card, group])

	owned_keys: set[tuple] = set()
	our_group_ids: set[int] = set()
	target_group_ids: dict[tuple, int] = {}
	for card, group in resolved:
		if group is None and not card.get("owned"):
			continue
		for declaration in card.get("links", []):
			owned_keys.add(_link_key(declaration))
			if group is not None:
				target_group_ids[_link_key(declaration)] = id(group)
		if card.get("owned") and group is not None:
			our_group_ids.add(id(group))

	# --- PASO 1: extraer TODAS las filas de nuestra propiedad, estén donde estén ---
	extracted: dict[tuple, object] = {}
	foreign_in_our_cards: dict[int, list] = {}
	for group in groups:
		kept = []
		for row in group[1]:
			key = _link_key(row)
			if key in owned_keys:
				# La 1ª copia se conserva (mantiene el `name`, menos ruido en tabVersion);
				# de la 2ª en adelante desaparecen por construcción. El dedupe está acotado
				# a OWNED: si ERPNext repite un link a propósito, se queda.
				if key not in extracted and reclaimed is not None:
					mine = id(group) in our_group_ids
					declared_target = target_group_ids.get(key) == id(group)
					if not mine and not declared_target and group[0] is not None:
						reclaimed.append(f"{_get(group[0], 'label')} / {key[0]}:{key[1]}")
				extracted.setdefault(key, row)
				continue
			if id(group) in our_group_ids:
				# Lo ajeno que vive dentro de una tarjeta nuestra: se conserva y se reubica
				# al final de esa misma tarjeta.
				foreign_in_our_cards.setdefault(id(group), []).append(row)
			else:
				kept.append(row)
		group[1] = kept

	# --- PASO 2: reinsertar donde manda el manifiesto ---------------------
	placed: list[list] = []
	for card, group in resolved:
		if group is None:
			if not card.get("owned"):
				continue
			card_break = {"type": "Card Break", "label": card["label"], "hidden": 0, "link_count": 0}
			group = [card_break, []]
			_insert_group(groups, group, card.get("place"))
		elif card.get("owned"):
			# Adopción de alias: se renombra la tarjeta en vez de crear una segunda.
			# `link_type` de un Card Break no se toca: Frappe lo rellena con la 1ª opción del
			# Select ("DocType") al insertar la fila, así que normalizarlo a NULL haría que la
			# corrida siguiente lo volviera a ver distinto y guardara de nuevo — un `Version`
			# de más por cada re-import de ERPNext. `get_link_groups()` lo ignora en los
			# Card Break, y los JSON de ERPNext lo traen así.
			_set(group[0], "label", card["label"])

		rows = []
		for declaration in _declared_link_rows(card):
			key = _link_key(declaration)
			# `pop`, no `get`: si el mismo link estuviera declarado en dos tarjetas, reusar el
			# mismo objeto lo dejaria dos veces en `doc.links` apuntando a la misma fila.
			row = extracted.pop(key, None)
			if row is None:
				row = _new_link_row(declaration)
			else:
				_apply_link_fields(row, declaration)
			rows.append(row)

		if card.get("owned"):
			group[1] = rows + foreign_in_our_cards.get(id(group), [])
		else:
			group[1] = _splice(group[1], rows, (card.get("insert") or {}).get("after_link"))
		placed.append([card, group])

	# --- PASO 3: tarjeta propia que quedó sin ningún link -> se borra el Card Break ---
	# Evita la tarjeta fantasma (un bloque `card` en `content` sin nada que mostrar).
	live_card_labels: set[str] = set()
	dead_group_ids: set[int] = set()
	for card, group in placed:
		if not card.get("owned"):
			continue
		if group[1]:
			live_card_labels.add(norm(card["label"]))
		else:
			dead_group_ids.add(id(group))
	if dead_group_ids:
		# Por identidad, no por igualdad: `list.remove` compara por valor y dos grupos
		# distintos podrían compararse iguales.
		groups[:] = [g for g in groups if id(g) not in dead_group_ids]

	doc.set("links", flatten_groups(groups))
	return live_card_labels


def renumber_and_recount(doc, owned_card_labels: set[str]) -> None:
	"""`idx` contiguos 1..N y `link_count` que no miente.

	Renumerar en cada corrida es lo que mata de raíz la colisión de `idx` (cuatro pares
	empatados en *Accounting*) y el Card Break náufrago de *Financial Reports*.

	Con `link_count` se es asimétrico a propósito:

	* Tarjetas **propias**: se fija siempre al número real.
	* Tarjetas **ajenas**: sólo se corrige un valor guardado que **no es cero y miente**
	  (p. ej. *Other Reports* decía 7 con 14 links). Un 0 no es peligroso —
	  `build_links_table_from_card` lo recuenta solo— y dejarlo quieto evita tocar filas de
	  ERPNext sin necesidad: *Buying* y *Selling* los tienen todos en 0 y quedan intactos.
	"""
	for index, row in enumerate(doc.links, start=1):
		row.idx = index

	for card_break, links in parse_groups(doc):
		if card_break is None:
			continue
		actual = len(links)
		stored = cint(card_break.link_count)
		ours = norm(card_break.label) in owned_card_labels
		if ours or (stored and stored != actual):
			card_break.link_count = actual


# ---------------------------------------------------------------------------
# reconciliación de accesos directos
# ---------------------------------------------------------------------------


def _new_shortcut_row(declaration: dict) -> dict:
	row = {
		"type": declaration["type"],
		"label": declaration["label"],
		"link_to": declaration.get("link_to"),
	}
	for field in SHORTCUT_OPTIONAL_FIELDS:
		if field in declaration:
			row[field] = declaration[field]
	return row


def _declared_shortcuts(manifest: dict) -> list[dict]:
	usable = []
	for declaration in manifest.get("shortcuts", []):
		if not _requirement_met(declaration):
			continue
		target_doctype = SHORTCUT_TARGET_DOCTYPE.get(declaration.get("type"))
		if not _target_exists(target_doctype, declaration.get("link_to")):
			continue
		usable.append(declaration)
	return usable


def reconcile_shortcuts(doc, manifest: dict) -> set[str]:
	declarations = manifest.get("shortcuts", [])
	if not declarations:
		return set()

	owned_keys = {_shortcut_key(d) for d in declarations}

	extracted: dict[tuple, object] = {}
	kept = []
	for row in doc.shortcuts:
		key = _shortcut_key(row)
		if key in owned_keys:
			extracted.setdefault(key, row)
			continue
		kept.append(row)

	rows = []
	live_labels: set[str] = set()
	for declaration in _declared_shortcuts(manifest):
		key = _shortcut_key(declaration)
		# `pop`, no `get`, por simetría con los links: con `get`, dos declaraciones de la
		# misma clave recibían el MISMO objeto y `doc.shortcuts` quedaba con N+1 filas contra
		# N en la BD — la huella no convergía nunca. Hoy además lo ataja
		# `assert_unique_declarations`, pero el `pop` es el que lo hace imposible.
		row = extracted.pop(key, None)
		if row is None:
			row = _new_shortcut_row(declaration)
		else:
			# Adopción: se corrige el label (los históricos traían espacios finales y faltas
			# de tilde) sin duplicar la fila, porque la identidad es (type, link_to|url).
			_set(row, "label", declaration["label"])
			_set(row, "type", declaration["type"])
			for field in SHORTCUT_OPTIONAL_FIELDS:
				if field in declaration:
					_set(row, field, declaration[field])
		rows.append(row)
		live_labels.add(norm(declaration["label"]))

	doc.set("shortcuts", kept + rows)
	for index, row in enumerate(doc.shortcuts, start=1):
		row.idx = index
	return live_labels


# ---------------------------------------------------------------------------
# reconciliación del `content`
# ---------------------------------------------------------------------------


def _find_block(blocks: list[dict], kind: str, labels: list[str]) -> dict | None:
	field = f"{kind}_name"
	for label in labels:
		wanted = norm(label)
		for block in blocks:
			if block.get("type") != kind:
				continue
			if norm((block.get("data") or {}).get(field)) == wanted:
				return block
	return None


def _insert_after_last(blocks: list[dict], kind: str, block: dict) -> None:
	position = len(blocks)
	for index, existing in enumerate(blocks):
		if existing.get("type") == kind:
			position = index + 1
	blocks.insert(position, block)


def _insert_block(blocks: list[dict], kind: str, block: dict, after_label: str | None) -> None:
	"""Coloca un bloque nuevo detrás de su ancla del `place`; si no está, tras el último del tipo.

	Sin esto, `place.after_card` ordenaba la tabla `links` pero **no** el layout: el
	renderizador arma la pantalla desde `content` (`blocks/card.js` resuelve por label), así
	que la tarjeta salía siempre al final aunque el manifiesto dijera otra cosa. De las tres
	`place` declaradas, dos acertaban por casualidad —su ancla ya era la última tarjeta— y
	`Configuración Venezuela` after `Payments` fallaba.
	"""
	if after_label:
		wanted = norm(after_label)
		field = f"{kind}_name"
		for index, existing in enumerate(blocks):
			if existing.get("type") == kind and norm((existing.get("data") or {}).get(field)) == wanted:
				blocks.insert(index + 1, block)
				return
	_insert_after_last(blocks, kind, block)


def reconcile_content(doc, manifest: dict, live_card_labels: set[str], live_shortcut_labels: set[str]) -> None:
	try:
		original = json.loads(doc.content or "[]")
	except ValueError:
		original = []
	if not isinstance(original, list):
		original = []
	blocks = copy.deepcopy(original)

	for card in manifest.get("cards", []):
		if not card.get("owned"):
			continue
		labels = [card["label"], *card.get("aliases", [])]
		block = _find_block(blocks, "card", labels)
		if norm(card["label"]) in live_card_labels:
			if block is None:
				block = {
					"id": _stable_id(doc.name, "card", card["label"]),
					"type": "card",
					"data": {"card_name": card["label"], "col": card.get("col", 4)},
				}
				_insert_block(blocks, "card", block, (card.get("place") or {}).get("after_card"))
			else:
				data = block.setdefault("data", {})
				data["card_name"] = card["label"]
				# `data.links` inline no se renderiza (blocks/card.js resuelve por label
				# contra get_link_groups()); sólo servía para ensuciar el JSON.
				data.pop("links", None)
				# `col` NO se reimpone: es ancho de layout, lo mismo que `place`, y el usuario
				# puede cambiarlo desde la UI. Pisárselo en cada migrate sería la misma guerra
				# que el diseño evita con la posición de la tarjeta. Sólo se rellena si falta.
				data.setdefault("col", card.get("col", 4))
				if not block.get("id"):
					block["id"] = _stable_id(doc.name, "card", card["label"])
		elif block is not None:
			blocks.remove(block)

	for declaration in manifest.get("shortcuts", []):
		labels = [declaration["label"], *declaration.get("aliases", [])]
		block = _find_block(blocks, "shortcut", labels)
		if norm(declaration["label"]) in live_shortcut_labels:
			if block is None:
				block = {
					"id": _stable_id(doc.name, "shortcut", declaration["label"]),
					"type": "shortcut",
					"data": {"shortcut_name": declaration["label"], "col": declaration.get("col", 3)},
				}
				_insert_after_last(blocks, "shortcut", block)
			else:
				data = block.setdefault("data", {})
				data["shortcut_name"] = declaration["label"]
				data.setdefault("col", declaration.get("col", 3))
				if not block.get("id"):
					block["id"] = _stable_id(doc.name, "shortcut", declaration["label"])
		elif block is not None:
			blocks.remove(block)

	# Sólo se reescribe si el árbol de bloques cambió de verdad: re-serializar un JSON
	# idéntico mueve la huella y dispara un save inútil.
	if blocks != original:
		doc.content = json.dumps(blocks)


# ---------------------------------------------------------------------------
# huella / no-op
# ---------------------------------------------------------------------------


def _fingerprint_row(row, fields) -> list:
	return [cint(_get(row, f)) if f in _INT_FIELDS else _get(row, f) for f in fields]


def fingerprint(doc) -> str:
	"""Huella del documento. Si no cambia, no hay `save()` — y sin `save()` no hay nada.

	Los campos salen de las constantes del módulo, no de una lista escrita a mano: un campo
	que el manifiesto puede escribir pero la huella no mira es un cambio que se aplica y
	nunca se guarda, en silencio y para siempre.

	Nota metodológica: `tabVersion` **no** sirve para verificar esto. `version.get_diff()`
	itera `meta.fields` para las hijas e `idx` no es campo de meta, así que un cambio de
	sólo-`idx` guarda el documento sin dejar fila. Los indicadores válidos son `modified` y
	este `changed`.
	"""
	return json.dumps(
		{
			"links": [
				_fingerprint_row(row, _LINK_FINGERPRINT_FIELDS + LINK_OPTIONAL_FIELDS) for row in doc.links
			],
			"shortcuts": [
				_fingerprint_row(row, _SHORTCUT_FINGERPRINT_FIELDS + SHORTCUT_OPTIONAL_FIELDS)
				for row in doc.shortcuts
			],
			"content": doc.content or "",
		},
		sort_keys=True,
		default=str,
	)


def _link_labels(doc) -> Counter:
	"""Multiconjunto `tarjeta / tipo:destino`.

	`Counter` y no `set`: con un set, quitar una de dos filas idénticas no aparecía en el plan
	(el dedupe de los duplicados de *Selling* salía como `links_removed=[]`).
	"""
	out: Counter = Counter()
	for card_break, links in parse_groups(doc):
		card = _get(card_break, "label") if card_break is not None else "(sin tarjeta)"
		for row in links:
			out[f"{card} / {_get(row, 'link_type')}:{_get(row, 'link_to')}"] += 1
	return out


def _shortcut_labels(doc) -> Counter:
	return Counter(
		f"{_get(r, 'type')}:{_get(r, 'link_to') or _get(r, 'url')} ({_get(r, 'label')})" for r in doc.shortcuts
	)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def apply_manifest(manifest: dict, dry_run: bool = False) -> dict | None:
	assert_unique_declarations(manifest)

	workspace_name = _first_existing_workspace(manifest.get("targets", []))
	if not workspace_name:
		print(
			f"l10n_ve workspaces: {manifest.get('_source')} sin destino "
			f"(ninguno de {manifest.get('targets')} existe); no se inyecto nada."
		)
		return None

	doc = frappe.get_doc("Workspace", workspace_name)
	before_fingerprint = fingerprint(doc)
	before_rows = len(doc.links)
	before_links = _link_labels(doc)
	before_shortcuts = _shortcut_labels(doc)

	reclaimed: list[str] = []
	live_card_labels = reconcile_links(doc, manifest, reclaimed)
	live_shortcut_labels = reconcile_shortcuts(doc, manifest)
	renumber_and_recount(doc, live_card_labels)
	reconcile_content(doc, manifest, live_card_labels, live_shortcut_labels)

	after_links = _link_labels(doc)
	after_shortcuts = _shortcut_labels(doc)

	plan = {
		"workspace": workspace_name,
		"changed": fingerprint(doc) != before_fingerprint,
		"rows_before": before_rows,
		"rows_after": len(doc.links),
		"links_added": sorted((after_links - before_links).elements()),
		"links_removed": sorted((before_links - after_links).elements()),
		"shortcuts_added": sorted((after_shortcuts - before_shortcuts).elements()),
		"shortcuts_removed": sorted((before_shortcuts - after_shortcuts).elements()),
		# Links sacados de una tarjeta ajena que NO es la declarada como destino: el único
		# caso en que el reconciliador le mueve una fila a ERPNext. Se reporta siempre.
		"reclaimed": sorted(reclaimed),
	}

	if not plan["changed"] or dry_run:
		return plan

	with no_file_export():
		# `ignore_links` como hace `import_file.import_doc`: `link_to` es un Dynamic Link, y
		# UNA fila colgante (p. ej. resto de una app desinstalada) hace estallar el save del
		# workspace entero — justo el caso que este reconciliador existe para reparar.
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
	frappe.db.commit()
	return plan


def apply_all(dry_run: bool = False) -> list[dict]:
	"""Aplica los cuatro manifiestos. Es el hook `after_migrate` de l10n_ve.

	Silencioso por diseño: imprime UNA línea y sólo si algo cambió de verdad. Pero **nunca
	falla en silencio**: `migrate.py` llama los hooks `after_migrate` pelados y su `@atomic`
	hace rollback + raise, así que una excepción que escape de acá mata el `bench migrate`
	entero y se lleva puestos los `after_migrate` de las apps que van detrás. Nada sale de
	esta función: ni leer los manifiestos, ni aplicarlos.
	"""
	plans: list[dict] = []

	try:
		manifests = load_manifests()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "workspace_injection: load_manifests")
		print("l10n_ve workspaces: FALLO leyendo los manifiestos; no se inyecto nada (ver Error Log).")
		return plans

	for manifest in manifests:
		# Savepoint por manifiesto: `update_child_table` hace el DELETE ... NOT IN ANTES del
		# bucle de db_update(), así que un fallo a mitad no deja duplicados sino filas
		# faltantes con `link_count` inflado — munición directa para `clean_up()`. Sin
		# rollback, el commit del manifiesto siguiente confirmaba ese destrozo.
		# Ojo: `frappe.db.savepoint()` NO es context manager y devuelve None.
		savepoint = "l10n_ve_wsinj"
		frappe.db.savepoint(savepoint)
		try:
			plan = apply_manifest(manifest, dry_run=dry_run)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(frappe.get_traceback(), f"workspace_injection: {manifest.get('_source')}")
			print(f"l10n_ve workspaces: FALLO en {manifest.get('_source')}; ver Error Log.")
			continue
		if plan:
			plans.append(plan)
			if plan["reclaimed"]:
				print(
					f"l10n_ve workspaces: {plan['workspace']} - links reclamados de tarjetas ajenas "
					f"no declaradas: {', '.join(plan['reclaimed'])}"
				)

	touched = [p for p in plans if p["changed"]]
	if touched:
		resumen = ", ".join(f"{p['workspace']} ({p['rows_before']}->{p['rows_after']} links)" for p in touched)
		prefix = "l10n_ve workspaces (dry-run):" if dry_run else "l10n_ve workspaces:"
		print(f"{prefix} {resumen}")
	return plans
