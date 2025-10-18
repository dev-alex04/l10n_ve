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
        create_sales_taxes_and_charges_template()
        set_title_field_on_purchase_invoice()
        set_reference_currency_on_company()

        print("Success: Configuración de datos para l10n_ve completada exitosamente.")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la configuración de l10n_ve_data: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en set_l10n_ve_data')


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
        tax_unit_value = 43
        effective_date = "2025-01-01"
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
    Valida los valores de 'Tipo de persona' contra las opciones del DocType.
    """
    print("Iniciando la creación de datos del Tabulador de ISLR...")

    csv_file_path = frappe.get_app_path('l10n_ve', 'resources', 'islr_tabulator.csv')

    try:
        meta = frappe.get_meta("Tabulator ISLR Aliquots")
        valid_person_types = meta.get_field("types_of_person").options.split("\n")
        valid_person_types = [opt.strip() for opt in valid_person_types if opt.strip()]

        grouped_data = {}
        with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row_num, row in enumerate(reader, 1):
                codigo = row.get("Codigo", "").strip()
                if not codigo:
                    continue

                if int(codigo) >= 10:
                    codigo = f'0{codigo}'
                else:
                    codigo = f'00{codigo}'

                if codigo not in grouped_data:
                    grouped_data[codigo] = {
                        "descripcion": row.get('Descripcion', '').strip(),
                        "aliquots": []
                    }

                row['original_row_num'] = row_num
                grouped_data[codigo]["aliquots"].append(row)

        for codigo, data in grouped_data.items():
            if frappe.db.exists("Tabulator ISLR", {"codigo": codigo}):
                print(f"  -- Omitiendo (ya existe concepto padre): {codigo}")
                continue

            doc = frappe.new_doc("Tabulator ISLR")
            doc.codigo = codigo
            doc.descripcion = data["descripcion"]

            for aliquot_data in data["aliquots"]:
                types_of_person_from_csv = aliquot_data.get('Tipo de persona', '').strip()

                if types_of_person_from_csv not in valid_person_types:
                    print(f"!! ADVERTENCIA: Valor '{types_of_person_from_csv}' en la fila {aliquot_data['original_row_num']} del CSV no es una opción válida para 'Tipo de persona'. Omitiendo alícuota.")
                    continue

                doc.append("aliquot", {
                    "aliquot": aliquot_data.get('Alicuota', '').strip(),
                    "subtracting": aliquot_data.get('Sustraendo', '').strip(),
                    "percentage_base": aliquot_data.get('Porcentaje Base', '').strip(),
                    "types_of_person": types_of_person_from_csv, # Usamos el valor directo del CSV
                    "payments_greater_than_bs": aliquot_data.get('Pagos mayores a', '').strip()
                })

            try:
                doc.save(ignore_permissions=True)
                print(f"  -> Creado concepto: {codigo} - {doc.descripcion} con {len(doc.aliquot)} alícuotas.")
            except frappe.ValidationError as e:
                print(f"!! FAILURE al guardar el código '{codigo}': {e}")

        frappe.db.commit()
        print("\nSuccess: Proceso de creación del Tabulador de ISLR completado.")

    except Exception as e:
        print(f"!! FATAL: Ocurrió un error inesperado: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_islr_tabulator')

def set_chart_of_accounts() -> None:
    """
    Configura las cuentas contables de impuestos en los campos
    personalizados del Doctype Company para cada compañía existente.
    """
    print("Iniciando la configuración de cuentas contables en las Compañías...")

    try:

        account_map = [
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

                account_name = f"{account_info['account_number']} - {account_info['account_name']} - {company.abbr}"
                parent_account = f"{account_info['parent_account']} - {company.abbr}"

                if not frappe.db.exists("Account", account_name):

                    new_account = frappe.new_doc('Account')

                    new_account.company = company.name
                    new_account.parent_account = parent_account
                    new_account.account_type = account_info['account_type']
                    new_account.account_name = account_info["account_name"]
                    new_account.account_number = account_info['account_number']

                    new_account.insert(ignore_permissions=True)

                frappe.db.set_value("Company",
                                    company.name,
                                    fieldname,
                                    account_name)

                print(f"  Cuenta  '{account_name}' para la compañía '{company.name}' establecida satisfactoriamente y establecida en el campo{fieldname} de la empresa.")

        frappe.db.commit()

    except Exception as e:
        print(f" !! ERROR configucreando las cuentas contables: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en set_chart_of_accounts')

    print("Success: Configuración de cuentas contables en las compañías completada.")


def create_vat_withholding() -> None:

    print(f"Configurando retenciones de IVA")

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

        for aliquot in (100, 75):

            withholding = frappe.new_doc('Tax Withholding Category')
            withholding.name = f'IVA Retencion {aliquot}%'

            withholding.append('rates' , {
                'to_date': to_date,
                'from_date': from_date,
                'charge_type': 'VAT Withholding',
                'tax_withholding_rate': aliquot,
            })

            for company in companies:

                if not (company.get('sales_vat_withholding_account') and company.get('purchase_vat_withholding_account')):
                    print(f"  !! ADVERTENCIA: Cuentas de retención de IVA no configuradas para la compañía '{company.name}'. Se omitirá.")
                    continue

                withholding.append('accounts', {
                    'company': company['name'],
                    'account': company['purchase_vat_withholding_account'],
                    'sales_account': company['sales_vat_withholding_account'],
                })

            withholding.insert(ignore_permissions=True)

        print(f"Retenciones de IVA configuradas exitosamente")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación del retencioes de IVA: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_vat_withholding')


def create_sales_taxes_and_charges_template() -> None:

    print("Creando impuesto deIVA")

    try:

        template_types = {
            'Sales': 'sales_vat_account',
            'Purchase': 'purchase_vat_account'
        }

        companies = frappe.db.get_all('Company', fields=['name', 'abbr'])

        for doctype, fieldname in template_types.items():

            doctype_name = f'{doctype} Taxes and Charges Template'

            for company in companies:

                vat_account_str = frappe.db.get_value('Company',
                                                      company['name'],
                                                      fieldname)
                if not vat_account_str:
                    continue

                for i, aliquot in enumerate([16, 8, 15, 31]):

                    if frappe.db.exists(doctype_name,
                                        f'IVA {aliquot}% - {company["abbr"]}'):
                        continue

                    tax_template = frappe.new_doc(doctype_name)

                    tax_template.company = company['name']
                    tax_template.title = f'IVA {aliquot}% - {company["abbr"]}'
                    tax_template.is_default = bool(i == 0)

                    tax_template.append('taxes', {
                        'rate': aliquot,
                        'charge_type': 'VAT',
                        'add_deduct_tax': 'Add',
                        'account_head': vat_account_str,
                        'description': f'IVA {aliquot}%',
                    })

                    tax_template.insert(ignore_permissions=True)

                    print(f"Success: Impuesto de IVA {aliquot}% para {doctype} creado exitosamente.")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación del impuesto de IVA: {e}")
        frappe.log_error(frappe.get_traceback(),
                         'Error en create_sales_taxes_and_charges_template')


def set_title_field_on_purchase_invoice() -> None:

    print("Estableciendo campo title_field en Purchase Invoice")

    try:

        frappe.db.set_value('DocType',
                            'Purchase Invoice',
                            'title_field',
                            'bill_no' )

        frappe.db.set_value('DocType',
                            'Purchase Invoice',
                            'show_title_field_in_link',
                            True)

        print("Campo bill_no establecido como campo Titulo en Purchase Invoice")

    except Exception as e:
        print(f"Failure: Ocurrió un error Estableciendo campo title_field en Purchase Invoice: {e}")
        frappe.log_error(frappe.get_traceback(),
                         'Error Estableciendo campo title_field en Purchase Invoice:')


def set_reference_currency_on_company() -> None:

    print("Estableciendo campo reference_currency en Purchase Invoice")

    try:

        for company in frappe.get_all('Company', pluck='name'):

            frappe.db.set_value('Company',
                                company,
                                'reference_currency',
                                'USD')

        print("Campo reference_currency establecido en las empresas")

    except Exception as e:
        print(f"Failure: Ocurrió un error Estableciendo campo reference_currency: {e}")
        frappe.log_error(frappe.get_traceback(),
                         'Error Estableciendo campo reference_currency')
