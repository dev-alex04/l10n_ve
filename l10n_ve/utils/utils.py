import frappe
from frappe import _
import re
from frappe.utils import getdate


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

def validate_taxpayer_and_person_type_consistency(doc):
    """
    Valida que 'Nature of the Taxpayer' y 'Type of person' sean consistentes.
    """
    nature = doc.get("nature_of_the_taxpayer")
    person_type = doc.get("type_of_person")

    if not nature or not person_type:
        return

    legal_entities_nature = ["Juridical", "Government", "Communal"]
    natural_persons_nature = ["Venezuelan", "Extranjero", "Passport"]

    is_legal_nature = nature in legal_entities_nature
    is_natural_nature = nature in natural_persons_nature

    is_legal_person_type = \
    person_type.startswith("Domiciled legal entity") \
    or person_type.startswith("Non-domiciled legal entity")

    is_natural_person_type = person_type.startswith("Natural person") \
    or person_type.startswith("Non-domiciled natural person")


    if is_legal_nature and not is_legal_person_type:
        frappe.throw(_("Con la Naturaleza de Contribuyente '{0}'," \
        " el Tipo de Persona debe ser una entidad legal.").format(nature))

    if is_natural_nature and not is_natural_person_type:
        frappe.throw(_("Con la Naturaleza de Contribuyente '{0}'," \
        " el Tipo de Persona debe ser una persona natural.").format(nature))

    if is_legal_person_type and not is_legal_nature:
        frappe.throw(_("Con el Tipo de Persona '{0}'," \
        " la Naturaleza del Contribuyente debe ser Jurídico," \
        " Gubernamental o Comunal.").format(person_type))

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
            'default': 8
        },
        'Passport': {
            'Extranjero': [8,9],
        }
    }
    doc_config = config.get(document_type, config['RIF'])
    return doc_config.get(nature, doc_config.get('default'))

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

    if is_passport:

        cleaned_id = re.sub(r'[^a-zA-Z0-9]', '', doc.tax_id).upper()
        doc.tax_id = cleaned_id
        number = cleaned_id
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
    """
    if not (self.is_return or self.is_debit_note) or not self.return_against:
        return

    current_posting_date = getdate(self.posting_date)
    origin_invoice_date = frappe.db.get_value(
        self.doctype, self.return_against, "posting_date"
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
        exit()

def format_amounts(doc, main_fields=[], child_fields=[], child_table_field=None):
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
                    formatted_value = frappe.format(item.get(field), "Currency").replace(currency_symbol, "").strip()
                    item.set(field, formatted_value)