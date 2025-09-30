import os
import csv

import frappe
from frappe.utils import getdate

def set_l10n_ve_data() -> None:
    print("Iniciando la configuración de datos para l10n_ve...")

    try:

        create_currency_exchange()
        create_tax_unit()
        create_islr_tabulator()
        set_chart_of_accounts()
        create_vat_withholding()
        # create_sales_taxes_and_charges_template()


        print("Success: Configuración de datos para l10n_ve completada exitosamente.")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la configuración de l10n_co_data: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en set_l10n_co_data')


def create_currency_exchange() -> None:
    print("Creando tasa de cambio...")
    try:

        from l10n_ve.tasks import create_currency_exchange
        create_currency_exchange()
        print("Success: Tasa de cambio creada exitosamente.")

    except Exception as e:
        print(f"Failure: Ocurrió un error al crear la tasa de cambio: {e}")
        frappe.log_error(frappe.get_traceback(),
                         'Error en create_currency_exchange')


def create_tax_unit() -> None:
    """
    Crea el registro inicial para la Unidad Tributaria.
    """
    print("Iniciando la creación de la Unidad Tributaria...")

    try:
        # Define los datos de la unidad tributaria a crear
        tax_unit_value = 43
        effective_date = "2025-01-01" # Fecha de vigencia de la UT

        # Verifica si ya existe una unidad tributaria para esa fecha para no duplicar
        if not frappe.db.exists("Tax Unit", {"effective_date": effective_date}):

            tax_unit = frappe.new_doc("Tax Unit")
            tax_unit.value = tax_unit_value
            tax_unit.effective_date = effective_date
            tax_unit.is_active = True  # La establece como activa

            tax_unit.insert(ignore_permissions=True)

            print(f"  -> Unidad Tributaria con valor {tax_unit_value} creada exitosamente.")
        else:
            print(f"  -- Omitiendo (ya existe): Unidad Tributaria para la fecha {effective_date}.")

        frappe.db.commit()
        print("Success: Creación de Unidad Tributaria completada.")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación de la Unidad Tributaria: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_tax_unit')


def create_islr_tabulator() -> None:
    """
    Crea los registros del Tabulador de ISLR a partir de un archivo CSV.
    """
    print("Iniciando la creación de datos del Tabulador de ISLR...")

    csv_file_path = frappe.get_app_path('l10n_ve',
                                        'resources',
                                        'islr_tabulator.csv')

    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            current_islr_doc = None

            for row in reader:

                aliquot = row.get('Alicuota', '').strip()
                codigo = row.get("Codigo", "").strip()
                subtracting = row.get('Sustraendo', '').strip()
                descripcion = row.get('Descripcion', '').strip()
                percentage_base = row.get('Porcentaje Base', '').strip()
                types_of_person = row.get('Tipo de persona', '').strip()
                payments_greater_than_bs = row.get('Pagos mayores a', '').strip()


                # Si la fila tiene código y descripción, es un nuevo documento padre
                if codigo and descripcion:

                    if int(codigo) >= 10:
                        codigo = f'0{codigo}'
                    else:
                        codigo = f'00{codigo}'

                    if not frappe.db.exists("Tabulator ISLR", {"codigo": codigo}):
                        current_islr_doc = frappe.new_doc("Tabulator ISLR")
                        current_islr_doc.codigo = codigo
                        current_islr_doc.descripcion = descripcion

                        # Añadir la primera alícuota que viene en la misma fila
                        current_islr_doc.append("aliquot", {
                            "aliquot": aliquot,
                            "subtracting": subtracting,
                            "percentage_base": percentage_base,
                            "types_of_person": types_of_person,
                            "payments_greater_than_bs": payments_greater_than_bs
                        })
                        current_islr_doc.insert(ignore_permissions=True)
                        print(f"  -> Creado concepto: {codigo} - {descripcion}")
                    else:
                        # Si ya existe, lo cargamos para añadirle las alícuotas hijas
                        current_islr_doc = frappe.get_doc("Tabulator ISLR", {"codigo": codigo})
                        print(f"  -- Omitiendo (ya existe): {codigo} - {descripcion}")

                # Si no tiene código, es una alícuota hija del documento anterior
                elif current_islr_doc:
                    current_islr_doc.append("aliquot", {
                        "aliquot": aliquot,
                        "subtracting": subtracting,
                        "percentage_base": percentage_base,
                        "types_of_person": types_of_person,
                        "payments_greater_than_bs": payments_greater_than_bs
                    })
                    # Guardar el documento padre después de añadir cada hijo
                    current_islr_doc.save(ignore_permissions=True)

        frappe.db.commit()
        print("Success: Datos del Tabulador de ISLR creados exitosamente.")

    except FileNotFoundError:
        print(f"!! FAILURE: No se encontró el archivo en la ruta: {csv_file_path}")
        print("!! Por favor, asegúrate de que el archivo 'Tabulator ISLR.csv' exista en la carpeta 'resources' de tu aplicación.")
    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación del Tabulador de ISLR: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_islr_tabulator')



def set_chart_of_accounts() -> None:
    """
    Configura las cuentas contables de impuestos en los campos
    personalizados del Doctype Company para cada compañía existente.
    """
    print("Iniciando la configuración de cuentas contables en las Compañías...")

    # Lista de diccionarios con el mapeo de campos y cuentas.
    # El 'account_name' debe coincidir exactamente con el nombre de la cuenta
    # en el Plan de Cuentas, incluyendo el sufijo de la compañía si existe.
    account_map = [
        # {'fieldname': 'sales_ica_account', 'account_name': '261510 - De industria y comercio'},
        {
            'account_name': 'IVA retenido en compras',
            'account_number': '2.7.2.15.99.01.01',
            'account_type': 'Tax',
            'fieldname': 'purchase_vat_withholding_account',
            'for_create': True,
            'parent_account': '2 - PASIVO',
        },
        {
            'account_name': 'Debito Fiscal IVA',
            'account_number': '2.7.2.15.99.01.02',
            'account_type': 'Tax',
            'fieldname': 'purchase_vat_account',
            'for_create': True,
            'parent_account': '2 - PASIVO',
        },
        {
            'account_name': 'ISLR retenido a terceros',
            'account_number': '2.7.2.15.01.01.01',
            'account_type': 'Tax',
            'fieldname': 'purchase_islr_account',
            'for_create': True,
            'parent_account': '2 - PASIVO',
        },
        {
            'account_name': 'Inventario Recibido pero no Facturado',
            'account_number': '2.7.2.15.99.01.03',
            'account_type': 'Stock Received But Not Billed',
            'fieldname': 'stock_received_but_not_billed',
            'for_create': True,
            'parent_account': '2 - PASIVO',
        },
        {
            'account_name': 'Credito Fiscal IVA',
            'account_number': '1.8.8.02.01.01.01',
            'account_type': 'Tax',
            'fieldname': 'sales_vat_account',
            'for_create': True,
            'parent_account': '1 - ACTIVO',
        },
        {
            'account_name': 'IVA retenido por terceros',
            'account_number': '1.8.8.02.01.02.01',
            'account_type': 'Tax',
            'fieldname': 'sales_vat_withholding_account',
            'for_create': True,
            'parent_account': '1 - ACTIVO',
        },
        {
            'account_name': 'ISLR retenido por terceros',
            'account_number': '1.8.8.02.02.01.01',
            'account_type': 'Tax',
            'fieldname': 'sales_islr_account',
            'for_create': True,
            'parent_account': '1 - ACTIVO',
        }
    ]

    companies = frappe.get_all("Company", fields=["name", "abbr"])
    for company in companies:
        print(f"Configurando cuentas para la compañía: {company.name}")

        for account_info in account_map:
            fieldname = account_info['fieldname']
            base_account_name = account_info['account_name']

            account_name = f"{base_account_name} - {company.abbr}"

            if not frappe.db.exists("Account", account_name):

                account_number = account_info["account_number"]
                parent_account = f'{account_info["parent_account"]} - {company.abbr}'


                if account_info.get('for_create') \
                        and not frappe.db.exists(
                            "Account", f'{account_number} - {account_name}'):

                    new_account = frappe.new_doc('Account')

                    new_account.parent_account = parent_account
                    new_account.account_number = account_number
                    new_account.account_type = account_info['account_type']
                    new_account.account_name = account_info["account_name"]

                    new_account.insert(ignore_permissions=True)

                    account_name = new_account.name

                else:
                    print(f"  !! ADVERTENCIA: No se encontró la cuenta  '{account_name}' para la compañía '{company.name}'. Se omitirá la configuración del campo '{fieldname}'.")

                    continue

            try:
                frappe.db.set_value("Company",
                                    company.name,
                                    fieldname,
                                    account_name)

                print(f" -> Campo '{fieldname}' configurado con la cuenta '{account_name}'.")

            except Exception as e:
                print(f" !! ERROR configurando el campo '{fieldname}' en la compañía '{company.name}': {e}")

    frappe.db.commit()
    print("Success: Configuración de cuentas contables en las compañías completada.")


def create_vat_withholding() -> None:

    try:

        companies = \
            frappe.db.get_all('Company',
                              fields=[
                                'name',
                                'abbr',
                                'sales_vat_withholding_account',
                                'purchase_vat_withholding_account'
                              ])

        to_date = getdate('2025-12-31')
        from_date = getdate('2025-01-01')

        print(f"Configurando retenciones de IVA")

        for aliquot in (100, 75):

            withholding = frappe.new_doc('Tax Withholding Category')
            withholding.name = f'IVA Retencion {aliquot}%'

            withholding.append('rates' , {
                'to_date': to_date,
                'from_date': from_date,
                'charge_type': 'VAT Withholding',
                'tax_withholding_rate': aliquot,
            })

            if not all([company['sales_vat_withholding_account'],
                        company['purchase_vat_withholding_account']]
                    for company in companies):
                continue

            for company in companies:

                withholding.append('accounts', {
                    'company': company['name'],
                    'account': company['purchase_vat_withholding_account'],
                    'sales_account': company['sales_vat_withholding_account'],
                })

            withholding.insert(ignore_permissions=True)

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación del retencioes de IVA: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_vat_withholding')


def create_sales_taxes_and_charges_template() -> None:

    template_types = (
        'Sales',
        'Purchase'
    )

    companies = frappe.db.get_all('Company', fields=['name', 'abbr'])

    for doctype in template_types:

        doctype_name = f'{doctype} Taxes and Charges Template'

        taxes_templates = frappe.db.get_all(doctype_name,
                                            pluck='name')

        for template_name in taxes_templates:

            if 'Colombia Tax' in template_name:
                tax_tempate = frappe.get_doc(doctype_name,
                                             template_name)

                tax_tempate.delete()

        for company in companies:

            vat_account_str = f'VAT - {company["abbr"]}'

            for i, aliquot in enumerate([16, 8, 15]):

                if frappe.db.exists(doctype_name,
                                    f'IVA {aliquot}% - {company["abbr"]}'):
                    continue

                tax_template = frappe.new_doc(doctype_name)

                tax_template.company = company['name']
                tax_template.title = f'IVA {aliquot}%'
                tax_template.is_default = bool(i == 0)

                tax_template.append('taxes', {
                    'rate': aliquot,
                    'charge_type': 'VAT',
                    'add_decut_tax': 'Add',
                    'account_head': vat_account_str,
                    'description': f'IVA {aliquot}%',
                })

                tax_template.insert(ignore_permissions=True)
