import os
import csv

import frappe

def set_l10n_co_data() -> None:
    print("Iniciando la configuración de datos para l10n_ve...")

    try:

        set_chart_of_accounts()
        create_vat_withholding()
        create_sales_taxes_and_charges_template()


        print("Success: Configuración de datos para l10n_ve completada exitosamente.")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la configuración de l10n_co_data: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en set_l10n_co_data')



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
        {'fieldname': 'sales_ica_account', 'account_name': '261510 - De industria y comercio'},
        {'fieldname': 'sales_ica_withholding_account', 'account_name': '2368 - Impuesto de industria y comercio retenido'},
        {'fieldname': 'purchase_ica_withholding_account', 'account_name': '135518 - Impuesto de industria y comercio retenido'},
        {'fieldname': 'purchase_income_tax_account', 'account_name': '2365 - Retención en la fuente'},
        {'fieldname': 'sales_income_tax_account', 'account_name': '135515 - Retención en la fuente'},
        {'fieldname': 'purchase_vat_withholding_account', 'account_name': '2367 - Impuesto a las ventas retenido'},
        {'fieldname': 'sales_vat_withholding_account', 'account_name': '135517 - Impuesto a las ventas retenido'},
        {'fieldname': 'purchase_vat_account', 'account_name': 'VAT'},
        {'fieldname': 'sales_vat_account', 'account_name': 'VAT'},
        {
            'for_create': True,
            'account_number': '220595',
            'parent_account': '22 - Proveedores',
            'fieldname': 'stock_received_but_not_billed',
            'account_type': 'Stock Received But Not Billed',
            'account_name': 'Valores adquiridos por recibir',
        },
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

    for aliquot in (15, 75):

        withholding = frappe.new_doc('Tax Withholding Category')
        withholding.name = f'IVA Retencion {aliquot}%'

        withholding.append('rates' , {
            'to_date': to_date,
            'from_date': from_date,
            'charge_type': 'ReteIVA',
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

            for i, aliquot in enumerate([19, 5]):

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
