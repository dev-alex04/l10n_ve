import re
import frappe
from frappe import _
import os

# Caché Redis de tasas de cambio, indexado por (fecha, moneda_origen, moneda_destino).
# Se invalida por completo cuando cambia cualquier 'Currency Exchange'
# (ver clear_exchange_rate_cache + doc_events/tasks.py).
EXCHANGE_RATE_CACHE_KEY: str = "l10n_ve_exchange_rate"

from frappe.utils import (
    getdate,
    get_first_day,
    get_url_to_list as url_to_list,
    get_link_to_form as link_to_form,
    nowdate,
    add_months,
    add_days,
    flt,
)

import erpnext


_JURIDICAL_NATURES: tuple[str, ...] = ("Juridical", "Government", "Communal", "Educational")
_NATURAL_NATURES: tuple[str, ...] = ("Venezuelan", "Extranjero", "Passport")
_JURIDICAL_PERSON_TYPES: tuple[str, ...] = ("Domiciled legal entity", "Non-domiciled legal entity")


@frappe.whitelist()
def is_juridical_customer(customer_name: str) -> bool:
    """Retorna True si el cliente es una persona jurídica.

    Las naturalezas jurídicas son: Juridical, Government, Communal y Educational.
    Además, una empresa extranjera (Naturaleza 'Extranjero' con Tipo de Persona
    'Persona jurídica no domiciliada') también es persona jurídica a efectos
    fiscales, pese a que 'Extranjero' es una naturaleza natural.

    Args:
        customer_name: Nombre (ID) del Customer en Frappe.

    Returns:
        True si es persona jurídica, False si es persona natural.
    """
    if not customer_name:
        return False

    nature = frappe.get_cached_value(
        "Customer", customer_name, "nature_of_the_taxpayer"
    ) or ""
    person_type = frappe.get_cached_value(
        "Customer", customer_name, "type_of_person"
    ) or ""

    return nature in _JURIDICAL_NATURES or (
        nature == "Extranjero" and person_type in _JURIDICAL_PERSON_TYPES
    )


@frappe.whitelist()
def get_company_address(company_name):
    if not company_name:
        return

    try:
        company_doc = frappe.get_doc("Company", company_name)
        address_link = company_doc.get("custom_company_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting company address")


@frappe.whitelist()
def get_supplier_address(supplier_name):
    if not supplier_name:
        return

    try:
        supplier_doc = frappe.get_doc("Supplier", supplier_name)
        address_link = supplier_doc.get("supplier_primary_address")

        if address_link:
            address_doc = frappe.get_doc("Address", address_link)
            return address_doc.as_dict()

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error getting supplier address")

# Qué implica cada letra de un documento venezolano. Vive al lado de
# `validate_taxpayer_and_person_type_consistency` a propósito: es la regla que tiene que
# satisfacer, y separarlas es como se desincronizan.
#
# El `label` es para mostrar; el resto son los valores internos de los Select.
IDENTITY_BY_LETTER: dict[str, dict[str, str]] = {
    "V": {
        "label": "Venezolano (persona natural)",
        "nature_of_the_taxpayer": "Venezuelan",
        "type_of_person": "Natural person domiciled",
        "customer_type": "Individual",
        "short_document": "Cedula",
        "long_document": "RIF",
    },
    "E": {
        "label": "Extranjero con cédula (persona natural)",
        "nature_of_the_taxpayer": "Extranjero",
        "type_of_person": "Natural person domiciled",
        "customer_type": "Individual",
        "short_document": "Cedula",
        "long_document": "RIF",
    },
    "P": {
        "label": "Extranjero con pasaporte",
        "nature_of_the_taxpayer": "Passport",
        "type_of_person": "Non-domiciled natural person",
        "customer_type": "Individual",
        "short_document": "Passport",
        "long_document": "Passport",
    },
    "J": {
        "label": "Empresa",
        "nature_of_the_taxpayer": "Juridical",
        "type_of_person": "Domiciled legal entity",
        "customer_type": "Company",
        "short_document": "RIF",
        "long_document": "RIF",
    },
    "G": {
        "label": "Ente gubernamental",
        "nature_of_the_taxpayer": "Government",
        "type_of_person": "Domiciled legal entity",
        "customer_type": "Company",
        "short_document": "RIF",
        "long_document": "RIF",
    },
    "C": {
        "label": "Consejo comunal",
        "nature_of_the_taxpayer": "Communal",
        "type_of_person": "Domiciled legal entity",
        "customer_type": "Company",
        "short_document": "RIF",
        "long_document": "RIF",
    },
}

# Un RIF de persona natural lleva 9 dígitos; una cédula, entre 6 y 8. Es lo único que
# distingue "V12345678" de "V123456789".
SHORT_DOCUMENT_MAX_DIGITS = 8


def split_document_number(raw: str | None) -> tuple[str, str]:
    """Parte un documento en (letra, dígitos). ("", "") si no se entiende.

    Tolera lo que la gente escribe: "V-12.345.678", "v12345678", con espacios. Un número
    sin letra devuelve letra vacía: no se adivina, porque de la letra dependen la
    retención y el documento fiscal.
    """
    limpio = re.sub(r"[^A-Za-z0-9]", "", raw or "").upper()

    if not limpio:
        return "", ""

    if limpio[0] in IDENTITY_BY_LETTER:
        return limpio[0], limpio[1:]

    return "", limpio


def classify_party_by_document(raw: str | None, document_type: str | None = None) -> dict:
    """Los campos fiscales que corresponden a ese documento, o `{}` si no se puede saber.

    Existe porque **omitir estos campos no deja la parte sin clasificar**: son Select
    obligatorios, y Frappe rellena un Select obligatorio vacío con su PRIMERA opción. Sin
    esto, un Customer creado desde código nace `RIF` + `Juridical` --persona jurídica--
    aunque tenga cédula y aunque se haya pedido `customer_type` Individual. No hay error
    en pantalla; se descubre cuando la retención de ISLR sale mal.

    `document_type` es lo que un humano eligió y manda sobre lo que se deduzca de la
    longitud, pero sólo si es posible para esa letra: una "J" no tiene cédula.
    """
    letter, digits = split_document_number(raw)
    entrada = IDENTITY_BY_LETTER.get(letter)

    if not entrada:
        return {}

    posibles = list(dict.fromkeys([entrada["short_document"], entrada["long_document"]]))
    elegido = document_type if document_type in posibles else None
    corto = len(digits) <= SHORT_DOCUMENT_MAX_DIGITS

    return {
        "type_of_document": elegido or (entrada["short_document"] if corto else entrada["long_document"]),
        "nature_of_the_taxpayer": entrada["nature_of_the_taxpayer"],
        "type_of_person": entrada["type_of_person"],
        "customer_type": entrada["customer_type"],
    }


def validate_taxpayer_and_person_type_consistency(doc):
    """
    Valida que 'Nature of the Taxpayer' y 'Type of person' sean consistentes.
    """
    nature = doc.get("nature_of_the_taxpayer")
    person_type = doc.get("type_of_person")

    if not nature or not person_type:
        return

    is_legal_nature = nature in _JURIDICAL_NATURES
    is_natural_nature = nature in _NATURAL_NATURES

    is_legal_person_type = \
    person_type.startswith("Domiciled legal entity") \
    or person_type.startswith("Non-domiciled legal entity")

    is_natural_person_type = person_type.startswith("Natural person") \
    or person_type.startswith("Non-domiciled natural person")

    # Excepción: una empresa extranjera (Naturaleza 'Extranjero') puede ser una
    # persona jurídica NO domiciliada, aunque 'Extranjero' sea naturaleza natural.
    is_foreign_legal_entity = \
    nature == "Extranjero" and person_type.startswith("Non-domiciled legal entity")


    if is_legal_nature and not is_legal_person_type:
        frappe.throw(_("Con la Naturaleza de Contribuyente '{0}'," \
        " el Tipo de Persona debe ser una entidad legal.").format(nature))

    if is_natural_nature and not is_natural_person_type and not is_foreign_legal_entity:
        frappe.throw(_("Con la Naturaleza de Contribuyente '{0}'," \
        " el Tipo de Persona debe ser una persona natural.").format(nature))

    if is_legal_person_type and not is_legal_nature and not is_foreign_legal_entity:
        frappe.throw(_("Con el Tipo de Persona '{0}'," \
        " la Naturaleza del Contribuyente debe ser Jurídico," \
        " Gubernamental, Comunal o Educativo.").format(person_type))

    if is_natural_person_type and not is_natural_nature:
        frappe.throw(_("Con el Tipo de Persona '{0}', " \
        "la Naturaleza del Contribuyente debe ser Venezolano, Extranjero o Pasaporte.").format(person_type))

def get_tax_id_config(document_type: str, nature: str) -> int:
    """
    Devuelve la longitud máxima de dígitos para un tipo de documento y naturaleza.
    """
    config = {
        'RIF': {'default': 9},
        'Cedula': {
            'default': [6,8]
        },
        'Passport': {
            'Extranjero': [5,12],
        },
        'DEA': {'default': 8}
    }
    doc_config = config.get(document_type, config['RIF'])
    return doc_config.get(nature, doc_config.get('default'))

def validate_unique_tax_id(doc) -> None:
    """
    Valida que no exista otro registro del mismo doctype con el mismo tax_id.
    """
    if not doc.tax_id:
        return

    title_field: str = "customer_name" if doc.doctype == "Customer" else "supplier_name"

    filters: dict = {
        "tax_id": doc.tax_id,
        "name": ["!=", doc.name]
    }

    existing: dict | None = frappe.db.get_value(
        doc.doctype, filters, ["name", title_field], as_dict=True
    )

    if existing:
        doc_type_label: str = _(doc.get("type_of_document")) or _("ID de Impuesto")
        existing_link: str = frappe.bold(
            link_to_form(doc.doctype, existing.name, existing.get(title_field))
        )
        frappe.throw(
            _("Ya existe un {0} con la {1} <b>{2}</b>: {3}").format(
                _(doc.doctype), doc_type_label, doc.tax_id, existing_link
            ),
            title=_("{0} Duplicado/a").format(doc_type_label)
        )

def validate_tax_id_format(doc):
    """
    Valida el formato del tax_id (RIF, Cédula, Pasaporte) en un documento.
    """
    if not doc.tax_id:
        return

    if not doc.meta.has_field("type_of_document"):
        cleaned_rif = re.sub(r'[^a-zA-Z0-9]', '', doc.tax_id).upper()
        doc.tax_id = cleaned_rif

        if not cleaned_rif:
            return

        letter = cleaned_rif[0]
        number = cleaned_rif[1:]
        valid_letters = "VEJGPC"

        if letter not in valid_letters:
            frappe.throw(_("El RIF '{0}' debe comenzar con una de las siguientes letras: {1}.").format(doc.tax_id, valid_letters))

        if not number.isdigit() or len(number) != 9:
            frappe.throw(_("El RIF '{0}' no es válido. El formato debe ser una letra "
                            "(V, E, J, G, P, C) seguida de 9 dígitos.").format(doc.tax_id))

        return

    is_passport = doc.meta.has_field("type_of_document") and doc.type_of_document == 'Passport'
    is_dea = doc.meta.has_field("type_of_document") and doc.type_of_document == 'DEA'

    if is_passport:

        cleaned_id = re.sub(r'[^a-zA-Z0-9]', '', doc.tax_id).upper()
        doc.tax_id = cleaned_id
        number = cleaned_id
    elif is_dea:
        original_tax_id = doc.tax_id
        cleaned_id = re.sub(r'[^a-zA-Z0-9]', '', original_tax_id or '').upper()
        doc.tax_id = cleaned_id

        if not cleaned_id:
            return

        # Match formats like OD12345678, DEAOD12345678, O12345678, etc.
        match = re.match(r'^(DEA)?(OD|OC|PD|PC|O|P|D)?(\d+)$', cleaned_id)
        if not match:
             frappe.throw(_("El Código DEA '{0}' no es válido. Debe contener números y puede incluir prefijos como OD, OC, PD, PC, O o DEA.").format(original_tax_id))

        number = match.group(3)

    else:

        cleaned_id = re.sub(r'[^a-zA-Z0-9]', '', doc.tax_id or '').upper()
        doc.tax_id = cleaned_id

        if not cleaned_id:
            return

        letter = cleaned_id[0]
        number = cleaned_id[1:]
        valid_letters = "VEJGPC"

        if letter not in valid_letters:
            frappe.throw(_("El ID de Impuesto '{0}' debe comenzar con una de las " \
            "               siguientes letras: {1}.").format(doc.tax_id, valid_letters))

        if not number.isdigit():
            frappe.throw(_("La parte numérica del ID de Impuesto '{0}' contiene " \
                            "caracteres no válidos.").format(doc.tax_id))

    # Validación de longitud
    length_config = get_tax_id_config(doc.type_of_document, doc.nature_of_the_taxpayer)
    num_len = len(number)

    if isinstance(length_config, list):
        min_len, max_len = length_config
        if not (min_len <= num_len <= max_len):
            frappe.throw(_("Para el tipo de documento '{0}', el ID de Impuesto '{1}' " \
            "               debe tener entre {2} y {3} dígitos.").format(
                doc.type_of_document, doc.tax_id, min_len, max_len
            ))
    else:
        if num_len != length_config:
            frappe.throw(_("Para el tipo de documento '{0}', " \
            "               el ID de Impuesto '{1}' debe tener {2} dígitos.").format(
                                doc.type_of_document, doc.tax_id, length_config
            ))

def validate_return_in_same_month(self):
    """
    Valida que una Nota de Crédito o Débito se cree en el mismo mes
    que la factura original a la que hace referencia.

    Además de la regla fiscal, el diseño de tasas depende de este guard:
    los naturales usan la tasa del 1° del mes, así que intra-mes la tasa
    propia de la nota coincide con la de la factura afectada.
    """
    if not (self.is_return or self.is_debit_note) or not self.return_against:
        return

    # return_against apunta a la factura ORIGINAL, no al doctype de la
    # nota: para VE Sales Credit/Debit Note consultar self.doctype
    # devolvía None y la validación pasaba en silencio.
    reference_doctype = (
        "Purchase Invoice" if "Purchase" in self.doctype else "Sales Invoice"
    )

    current_posting_date = getdate(self.posting_date)
    origin_invoice_date = frappe.db.get_value(
        reference_doctype, self.return_against, "posting_date"
    )

    if not origin_invoice_date:
        return

    origin_posting_date = getdate(origin_invoice_date)

    if (current_posting_date.month == origin_posting_date.month and
        current_posting_date.year == origin_posting_date.year):
        return

    document_type = _("Nota de Crédito") if self.is_return else _("Nota de Débito")
    frappe.throw(_("La {0} debe ser creada en el mismo mes que la factura original.").format(document_type))

def check_gl_entries(gl_entries: list=[], do_exit: bool = True) -> None:
    # NO QUITAR PRINT SE USA PARA DEBUGEAR
    print('INICIO ASIENTO')

    debit = credit = 0

    data = {
        'gls': [],
        'info': {
            'DEBE': 0,
            'HABER': 0,
            'DIFERENCIA': 0,
        }
    }

    for gl in gl_entries:
        debit += gl['debit']
        credit += gl['credit']

        data['gls'].append(
            f'account: {gl.get("account")}, DEBE: {gl.get("debit")} HABER: {gl.get("credit")}'
        )

        print(
            'account: ', gl.get('account'),
            ' DEBE: ', gl.get('debit'),
            # ' debito USD ', gl.get('usd_debit'),
            ' HABER: ', gl.get('credit'),
            # 'credito USD ', gl.get('usd_credit'),
            # ' documento: ', gl.get('voucher_no'),
              # ' tipo documento: ', gl.get('voucher_type'),
              # ' contra doctype', gl.get('against_voucher_type'),
              # ' contra documento',  gl.get('against_voucher'),
              # ' contra cuenta',  gl.get('against'),
            #   gl.get('posting_date'), 'fecha ',
              )

    print('DEBE: ', debit,  'HABER: ', credit, ' DIFERENCIA: ', debit - credit)
    print('FIN ASIENTO')

    data['info']['DEBE'] = debit
    data['info']['HABER'] = credit
    data['info']['DIFERENCIA'] = debit - credit

    frappe.publish_realtime(
            "database_debug",
            {
                'data': data,
            },
        )

    if do_exit:
        # exit()  # Comentado: solo para debug local, no usar en producción
        pass

def format_amounts(doc, main_fields=[], child_fields=[], child_table_field=None, special_formats={}):
    company_name = doc.get("empresa")
    company_currency = frappe.db.get_value("Company", company_name, "default_currency")
    currency_symbol = frappe.db.get_value("Currency", company_currency, "symbol") or ""

    if main_fields:
        for field in main_fields:
            if doc.get(field) is not None:
                formatted_value = frappe.format(doc.get(field), "Currency").replace(currency_symbol, "").strip()
                doc.set(field, formatted_value)

    if doc.get(child_table_field) and child_fields:
        for item in doc.get(child_table_field):
            for field in child_fields:
                if item.get(field) is not None:
                    if field in special_formats:
                        formatted_value = special_formats[field].format(item.get(field))
                    else:
                        formatted_value = frappe.format(item.get(field), "Currency").replace(currency_symbol, "").strip()
                    item.set(field, formatted_value)


def get_reference_currency():
    """Returns the currency of the default company"""
    company = erpnext.get_default_company()

    if company:

        return frappe.get_cached_value("Company", company, "reference_currency")

def get_link_to_form(doctype: str, document_name: str) -> str:

    title_field = frappe.db.get_value('DocType', doctype, "title_field")

    if not title_field:
        label = None

    else:
        label = frappe.db.get_value(doctype, document_name, title_field)

    url = frappe.bold(link_to_form(doctype, document_name, label))

    return url

@frappe.whitelist()
def create_independent_address(address_values: str) -> str:
    """
    Crea un nuevo documento de Address de forma independiente.
    No lo vincula a ninguna entidad en este paso.
    """
    address_values = frappe.parse_json(address_values)

    address_doc = frappe.new_doc("Address")
    address_doc.update(address_values)
    address_doc.flags.skip_link_address = True

    if not address_doc.address_title:
        raw_title = address_doc.address_line1 or _("Nueva Dirección")
        address_doc.address_title = raw_title[:110].strip()

    try:
        address_doc.insert(ignore_permissions=True)
    except Exception as e:
        frappe.throw(_("Error al insertar el documento de dirección: {0}").format(str(e)))

    return address_doc.name


@frappe.whitelist()
def get_address_data(address_name: str) -> dict:
    """Obtiene los datos de una dirección existente para edición."""
    if not frappe.db.exists("Address", address_name):
        frappe.throw(_("Dirección {0} no encontrada.").format(address_name))

    address_doc = frappe.get_cached_doc("Address", address_name)

    return {
        "address_line1": address_doc.address_line1,
        "address_type": address_doc.address_type,
        "country": address_doc.country,
        "state": address_doc.state,
        "city": address_doc.city,
        "county": address_doc.county,
        "parish": address_doc.parish,
        "pincode": address_doc.pincode,
        "phone": address_doc.phone,
        "email_id": address_doc.email_id,
        "is_primary_address": address_doc.is_primary_address,
        "is_shipping_address": address_doc.is_shipping_address,
    }


@frappe.whitelist()
def update_independent_address(address_name: str, address_values: str) -> str:
    """Actualiza un documento de Address existente."""
    if not frappe.db.exists("Address", address_name):
        frappe.throw(_("Dirección {0} no encontrada.").format(address_name))

    address_values = frappe.parse_json(address_values)
    address_doc = frappe.get_doc("Address", address_name)
    address_doc.flags.skip_link_address = True

    updatable_fields: list[str] = [
        "address_line1", "address_type", "country", "state",
        "city", "county", "parish", "pincode", "phone",
        "email_id", "is_primary_address", "is_shipping_address",
    ]

    for field in updatable_fields:
        if field in address_values:
            address_doc.set(field, address_values[field])

    if not address_doc.address_title:
        address_doc.address_title = address_doc.address_line1 or _("Nueva Dirección")

    try:
        address_doc.save(ignore_permissions=True)
    except Exception as e:
        frappe.throw(_("Error al actualizar la dirección: {0}").format(str(e)))

    return address_doc.name

def link_address_to_party(address_name: str, party_doctype: str, party_name: str) -> None:
    """
    Asegura que un documento de Address esté vinculado a un documento de Parte (Supplier/Customer).
    """
    if not frappe.db.exists("Address", address_name):
        frappe.throw(_("Dirección {0} no encontrada.").format(address_name))

    if not frappe.db.exists(party_doctype, party_name):
        frappe.throw(_("Documento principal {0} {1} no encontrado.").format(party_doctype, party_name))

    address_doc = frappe.get_doc("Address", address_name)

    link_exists = any(
        link.link_doctype == party_doctype and link.link_name == party_name
        for link in address_doc.links
    )

    if not link_exists:
        address_doc.append("links", {
            "link_doctype": party_doctype,
            "link_name": party_name,
        })
        address_doc.save(ignore_permissions=True)

def get_url_to_list(doctype: str) -> str:

    url = url_to_list(doctype)

    link = f'<a href="{url}" target="_blank"><b>{_(frappe.bold(_(doctype)))}</b></a>'

    return link


@frappe.whitelist()
def get_exchange_rate(date: str, from_currency: str) -> float:
    """Obtiene la tasa de cambio para una fecha y moneda específica.

    El resultado se cachea en Redis indexado por (fecha, origen, destino):
    la misma fecha + moneda se sirve desde caché sin pegar a la BDD. El caché
    se invalida por completo al crear/editar/borrar un 'Currency Exchange'
    (ver clear_exchange_rate_cache), de modo que tras actualizar la tasa la
    siguiente consulta hace UN solo query a la BDD y vuelve a guardar.
    """
    to_currency = frappe.defaults.get_defaults().get("currency")
    if from_currency == to_currency:
        return 1.0

    if not date or not from_currency or not to_currency:
        return 0

    # Normalizar la fecha a 'YYYY-MM-DD' para que un str y un date/datetime
    # de la misma fecha compartan la misma clave de caché.
    date_str: str = str(getdate(date))
    cache_field: str = f"{date_str}|{from_currency}|{to_currency}"
    cached = frappe.cache().hget(EXCHANGE_RATE_CACHE_KEY, cache_field)
    if cached is not None:
        return flt(cached)

    rate: float = _query_exchange_rate(date_str, from_currency, to_currency)
    # Solo se cachean tasas válidas (>0). Una fecha sin tasa aún no se cachea
    # para que vuelva a consultarse en cuanto el BCV la cargue (el insert
    # invalida el caché igualmente, pero esto evita servir ceros transitorios).
    if rate:
        frappe.cache().hset(EXCHANGE_RATE_CACHE_KEY, cache_field, rate)
    return rate

def _query_exchange_rate(date: str, from_currency: str, to_currency: str) -> float:
    """Consulta la tasa en la BDD (sin caché).
    Busca primero la tasa más reciente en o antes de la fecha solicitada.
    Si no existe, busca la más próxima posterior como fallback.
    Usa SQL directo para evitar problemas con 'date' como keyword reservada
    en MariaDB al usarla en ORDER BY vía frappe.db.get_value.
    """
    result = frappe.db.sql(
        """
        SELECT `exchange_rate`
        FROM `tabCurrency Exchange`
        WHERE `date` <= %s
            AND `from_currency` = %s
            AND `to_currency` = %s
        ORDER BY `date` DESC
        LIMIT 1
        """,
        (date, from_currency, to_currency),
    )

    if result:
        return flt(result[0][0])

    result = frappe.db.sql(
        """
        SELECT `exchange_rate`
        FROM `tabCurrency Exchange`
        WHERE `date` >= %s
            AND `from_currency` = %s
            AND `to_currency` = %s
        ORDER BY `date` ASC
        LIMIT 1
        """,
        (date, from_currency, to_currency),
    )

    return flt(result[0][0]) if result else 0


def resolve_exchange_rate_date(rate: float, from_currency: str = "USD", max_date: str = None) -> str | None:
    """Fecha real de publicación de una tasa: lookup INVERSO en Currency Exchange.

    Inverso de get_exchange_rate: dada la tasa que porta un documento, devuelve
    la fecha (más reciente <= max_date) en que el BCV publicó exactamente esa
    tasa, o None si ninguna fila coincide. Permite etiquetar el documento con
    la fecha verdadera de su tasa sin inferirla del posting_date — inferencia
    que falla cuando la tasa se actualizó después (ej. re-tasado de jurídicos
    al primer pago) o cuando get_exchange_rate cayó a la fila de un día
    anterior porque el BCV aún no cargaba la del día solicitado.
    """
    to_currency = frappe.defaults.get_defaults().get("currency")
    if not flt(rate) or not from_currency or not to_currency or from_currency == to_currency:
        return None

    # BETWEEN (sargable) en vez de ABS(col - x): permite usar índice sobre
    # exchange_rate y expresa la misma tolerancia de ±0.0001.
    rate_val: float = flt(rate)
    result = frappe.db.sql(
        """
        SELECT `date`
        FROM `tabCurrency Exchange`
        WHERE `exchange_rate` BETWEEN %s AND %s
            AND `from_currency` = %s
            AND `to_currency` = %s
            AND `date` <= %s
        ORDER BY `date` DESC
        LIMIT 1
        """,
        (rate_val - 0.0001, rate_val + 0.0001, from_currency, to_currency, max_date or nowdate()),
    )

    return str(result[0][0]) if result else None


def clear_exchange_rate_cache(doc=None, method=None) -> None:
    """Invalida el caché de tasas de cambio.
    Se invoca desde los doc_events de 'Currency Exchange' (alta/edición/baja
    manual) y desde la tarea de sincronización BCV (que actualiza vía
    frappe.db.set_value, el cual NO dispara doc_events). Borra todo el hash:
    al cambiar una tasa, las consultas con fallback de otras fechas también
    podrían variar, así que se recalculan todas bajo demanda.
    """
    frappe.cache().delete_key(EXCHANGE_RATE_CACHE_KEY)


@frappe.whitelist()
def get_ve_exchange_rate_for_customer(
    customer: str,
    date: str = None,
    from_currency: str = "USD",
) -> float:
    """Retorna la tasa de cambio correcta según el tipo de cliente venezolano.

    Regla fiscal, anclada SIEMPRE en hoy:

    - Jurídico (Juridical / Government / Communal / Educational):
      tasa del día de hoy.
    - Natural (Venezuelan / Extranjero / Passport):
      tasa del primer día del mes en curso.

    Por qué la referencia es hoy y no la fecha del documento
    --------------------------------------------------------
    Lo que se declara ante el SENIAT es la tasa del día en que el documento se EMITE,
    no la del período que factura. Una factura de julio cobrada en agosto se emite en
    agosto y debe salir a la tasa de agosto: si el cliente paga hoy un servicio de
    marzo, la factura sale a la tasa de hoy.

    Anclarla a la fecha recibida era la causa del incidente del 2026-08-03
    (ACC-SINV-2026-13754, cliente natural): se le pasaba el `posting_date` de la
    factura, que era de julio, y salió ante el SENIAT con la tasa del 1° de julio
    teniendo fecha de emisión 1° de agosto. Base imponible Bs 109.200,76 cuando
    correspondían Bs 128.726,43: Bs 19.526 de base y Bs 3.124 de IVA por debajo.

    El parámetro `date` se conserva por compatibilidad --la función está whitelisted y
    la llaman dos formularios-- pero NO participa de la regla. Se ignora a propósito:
    era justamente el camino por el que entraba la fecha equivocada. Los llamadores
    nuevos no lo pasan.

    Args:
        customer:      ID del Customer en Frappe.
        date:          Ignorado. Se mantiene por compatibilidad de firma.
        from_currency: Moneda de origen. Por defecto 'USD'.

    Returns:
        Tasa de cambio como float. 0.0 si no se encuentra ninguna.
        Si customer está vacío o no existe, se asume Natural (1° del mes en curso).
    """
    hoy = getdate(nowdate())

    if customer and is_juridical_customer(customer):
        rate_date = hoy
    else:
        rate_date = get_first_day(hoy)

    return get_exchange_rate(str(rate_date), from_currency) or 0.0

def validate_portal_upload(file_url, max_size_mb=5):
    """
    Valida que el archivo cargado sea una imagen o PDF y no exceda el peso permitido.
    """
    if not file_url:
        return

    allowed_extensions = ['.pdf', '.png', '.jpg', '.jpeg', '.webp']
    file_ext = os.path.splitext(file_url.lower())[1]
    
    if file_ext not in allowed_extensions:
        frappe.throw(_("Formato de archivo no permitido. Solo se aceptan PDF e imágenes (JPG, PNG, WebP)."))

    file_info = frappe.db.get_value("File", {"file_url": file_url}, ["name", "file_size"], as_dict=True)

    if file_info and file_info.file_size:
        max_size_bytes = max_size_mb * 1024 * 1024
        if file_info.file_size > max_size_bytes:
            frappe.delete_doc("File", file_info.name, ignore_permissions=True)
            frappe.throw(_("El archivo excede el límite de {0}MB.").format(max_size_mb))

def delete_old_attachment(doc, fieldname, new_file_url=None):
    """
    Elimina el archivo adjunto anterior si existe y es distinto al nuevo.
    """
    old_file_url = doc.get(fieldname)
    
    # Solo actuar si hay un archivo viejo y es diferente al que se está subiendo
    if old_file_url and old_file_url != new_file_url:
        file_name = frappe.db.get_value("File", {"file_url": old_file_url}, "name")
        if file_name:
            try:
                frappe.delete_doc("File", file_name, ignore_permissions=True, force=True)
            except frappe.DoesNotExistError:
                pass

def get_last_day_of_month(date):
    first_day_next_month = getdate(date).replace(day=1)
    next_month = add_months(first_day_next_month, 1)
    return add_days(next_month, -1)

def is_period_open(voucher_date, period_type="IVA"):
    if not voucher_date:
        return True
    
    today = getdate(nowdate())
    v_date = getdate(voucher_date)
    
    if period_type == "IVA":
        if v_date.day <= 15:
            limit_date = v_date.replace(day=15)
        else:
            limit_date = get_last_day_of_month(v_date)
        
        return today <= limit_date

    elif period_type in ("ISLR", "Municipal"):
        limit_date = get_last_day_of_month(v_date)
        return today <= limit_date

    return True


def _get_cached_rate(date_str, cache):
    """Helper local para almacenar en caché las tasas de cambio y evitar la consulta N+1 en bucles."""
    if date_str not in cache:
        cache[date_str] = get_exchange_rate(date_str, "USD") or 1.0
    return cache[date_str]


@frappe.whitelist()
def get_disponible_usd():
    """Calcula los fondos disponibles sumando cuentas de Caja y Banco con moneda USD."""
    accounts = frappe.get_all("Account", filters={
        "account_currency": "USD",
        "account_type": ["in", ["Bank", "Cash"]],
        "is_group": 0
    }, pluck="name")
    if not accounts:
        return 0.0
    # Refactorizado de frappe.db.get_value con SUM a consulta SQL directa para compatibilidad y robustez
    result = frappe.db.sql("""
        SELECT SUM(debit_in_account_currency - credit_in_account_currency)
        FROM `tabGL Entry`
        WHERE account IN %s AND docstatus = 1
    """, (tuple(accounts),))
    balance = result[0][0] if result and result[0][0] is not None else 0.0
    return float(balance)


@frappe.whitelist()
def get_gastos_usd_mes():
    """Calcula la sumatoria de gastos del mes corriente expresada en USD, optimizado con caché."""
    from frappe.utils import get_first_day, get_last_day, nowdate
    today = nowdate()
    first_day = get_first_day(today)
    last_day = get_last_day(today)
    
    accounts = frappe.get_all("Account", filters={"root_type": "Expense", "is_group": 0}, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1,
        "posting_date": ["between", [first_day, last_day]]
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        if entry.account_currency == "USD":
            total_usd += (entry.debit_in_account_currency - entry.credit_in_account_currency)
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            total_usd += (entry.debit - entry.credit) / rate
    return float(total_usd)


@frappe.whitelist()
def get_gastos_usd_ano():
    """Calcula la sumatoria de gastos del año corriente expresada en USD, optimizado con caché."""
    from frappe.utils import nowdate
    today = nowdate()
    year_start = f"{today[:4]}-01-01"
    year_end = f"{today[:4]}-12-31"
    
    accounts = frappe.get_all("Account", filters={"root_type": "Expense", "is_group": 0}, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1,
        "posting_date": ["between", [year_start, year_end]]
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        if entry.account_currency == "USD":
            total_usd += (entry.debit_in_account_currency - entry.credit_in_account_currency)
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            total_usd += (entry.debit - entry.credit) / rate
    return float(total_usd)


@frappe.whitelist()
def get_retencion_islr_usd():
    """Calcula retenciones de ISLR de clientes en el mes (filtrado de precisión por root_type='Asset')."""
    from frappe.utils import get_first_day, get_last_day, nowdate
    today = nowdate()
    first_day = get_first_day(today)
    last_day = get_last_day(today)
    
    # Filtrado explícito de precisión contable por root_type 'Asset'
    accounts = frappe.get_all("Account", filters={
        "account_name": ["like", "%islr%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1,
        "posting_date": ["between", [first_day, last_day]]
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        amount = entry.debit - entry.credit
        if entry.account_currency == "USD":
            amount_usd = entry.debit_in_account_currency - entry.credit_in_account_currency
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            amount_usd = amount / rate
        total_usd += amount_usd
    return float(total_usd)


@frappe.whitelist()
def get_retencion_iva_usd():
    """Calcula retenciones de IVA de clientes en el mes (filtrado de precisión por root_type='Asset')."""
    from frappe.utils import get_first_day, get_last_day, nowdate
    today = nowdate()
    first_day = get_first_day(today)
    last_day = get_last_day(today)
    
    # Filtrado explícito de precisión contable por root_type 'Asset'
    accounts = frappe.get_all("Account", filters={
        "account_name": ["like", "%iva%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1,
        "posting_date": ["between", [first_day, last_day]]
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        amount = entry.debit - entry.credit
        if entry.account_currency == "USD":
            amount_usd = entry.debit_in_account_currency - entry.credit_in_account_currency
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            amount_usd = amount / rate
        total_usd += amount_usd
    return float(total_usd)


@frappe.whitelist()
def get_pendiente_cobrar_usd():
    """Calcula el saldo pendiente por cobrar consolidado (A/R) en USD, optimizado con caché."""
    accounts = frappe.get_all("Account", filters={"account_type": "Receivable", "is_group": 0}, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        amount = entry.debit - entry.credit
        if entry.account_currency == "USD":
            amount_usd = entry.debit_in_account_currency - entry.credit_in_account_currency
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            amount_usd = amount / rate
        total_usd += amount_usd
    return float(total_usd)


@frappe.whitelist()
def get_igtf_usd():
    """Calcula el pasivo acumulado por pagar del IGTF en USD (filtrado de precisión por root_type='Liability')."""
    accounts = frappe.get_all("Account", filters={
        "account_name": ["like", "%igtf%"],
        "root_type": "Liability",
        "is_group": 0
    }, pluck="name")
    if not accounts:
        return 0.0
        
    gl_entries = frappe.get_all("GL Entry", filters={
        "account": ["in", accounts],
        "docstatus": 1
    }, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for entry in gl_entries:
        amount = entry.credit - entry.debit
        if entry.account_currency == "USD":
            amount_usd = entry.credit_in_account_currency - entry.debit_in_account_currency
        else:
            date_str = str(entry.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            amount_usd = amount / rate
        total_usd += amount_usd
    return float(total_usd)


@frappe.whitelist()
def get_total_facturado_usd():
    """Calcula el total facturado bruto en USD en el mes corriente, optimizado con caché."""
    from frappe.utils import get_first_day, get_last_day, nowdate
    today = nowdate()
    first_day = get_first_day(today)
    last_day = get_last_day(today)
    
    invoices = frappe.get_all("Sales Invoice", filters={
        "docstatus": 1,
        "posting_date": ["between", [first_day, last_day]]
    }, fields=["grand_total", "currency", "posting_date"])
    
    total_usd = 0.0
    rates_cache = {}
    for inv in invoices:
        if inv.currency == "USD":
            total_usd += inv.grand_total
        else:
            date_str = str(inv.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            total_usd += inv.grand_total / rate
    return float(total_usd)


@frappe.whitelist()
def get_usd_factura_de_venta():
    """Retorna la cantidad de facturas de venta registradas en USD durante el mes corriente."""
    from frappe.utils import get_first_day, get_last_day, nowdate
    today = nowdate()
    first_day = get_first_day(today)
    last_day = get_last_day(today)
    
    return frappe.db.count("Sales Invoice", filters={
        "currency": "USD",
        "docstatus": 1,
        "posting_date": ["between", [first_day, last_day]]
    })


@frappe.whitelist()
def get_today_bcv_rate() -> float:
    """Retorna la última tasa de cambio oficial (BCV) del dólar (USD) registrada."""
    from frappe.utils import nowdate
    to_currency = frappe.defaults.get_defaults().get("currency") or "VEF"
    if to_currency == "USD":
        return 1.0
    rate = get_exchange_rate(nowdate(), "USD")
    if not rate:
        rates = frappe.get_all(
            "Currency Exchange",
            filters={"from_currency": "USD", "to_currency": to_currency},
            fields=["exchange_rate"],
            order_by="date desc",
            limit=1
        )
        rate = rates[0].exchange_rate if rates else 0.0
    return flt(rate)

