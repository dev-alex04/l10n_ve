import os
import csv
import json
import frappe
from frappe import _
from frappe.utils import getdate

def set_data() -> None:
    print("Iniciando la configuración de datos para l10n_ve...")

    try:

        create_currency_exchange()
        create_tax_unit()
        create_islr_tabulator()
        set_chart_of_accounts()
        create_vat_withholding()
        create_sales_taxes_and_charges_template()
        set_title_field_on_purchase_invoice()
        set_mode_of_payments()
        set_reference_currency()
        set_allow_multi_currency_invoices()
        load_venezuela_data()
        create_bank_venezuelan()
        create_bank_account_types()
        create_economic_activities()
        uncheck_all_prepared_reports()
        disable_rounded_total()
        set_buying_naming_series()
        set_selling_settings()
        set_stock_naming_series()
        create_municipality_taxes()
        create_conatel_tax_types()
        set_stock_settings()
        create_bank_transaction_mappings()
        disable_other_currencies()
        remove_module_onboarding()
        set_profiles()
        set_roles()
        setup_workspaces()

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
    """
    print("Iniciando la creación de datos del Tabulador de ISLR...")

    csv_file_path = frappe.get_app_path('l10n_ve', 'resources', 'tabulador_islr.csv')

    try:
        grouped_data = {}
        with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                codigo = row.get("Codigo")
                if not codigo or not codigo.strip():
                    continue

                codigo = codigo.strip().zfill(3)

                descripcion = row.get("Descripción", "").strip()

                original_codigo = codigo
                suffix = 1
                while codigo in grouped_data and grouped_data[codigo]["descripcion"] != descripcion:
                    codigo = f"{original_codigo}-{suffix}"
                    suffix += 1

                if codigo not in grouped_data:
                    grouped_data[codigo] = {
                        "descripcion": descripcion,
                        "aliquots": []
                    }

                grouped_data[codigo]["aliquots"].append(row)

        for codigo, data in grouped_data.items():
            if frappe.db.exists("Tabulator ISLR", {"codigo": codigo}):
                print(f"  -- Omitiendo (ya existe concepto padre): {codigo}")
                continue

            doc = frappe.new_doc("Tabulator ISLR")
            doc.codigo = codigo
            doc.descripcion = data["descripcion"]

            if not doc.descripcion:
                print(f"!! ADVERTENCIA: Descripción vacía para el código '{codigo}'. Omitiendo registro.")
                continue

            for aliquot_data in data["aliquots"]:
                def clean_numeric_str(value_str):
                    if not value_str or not value_str.strip():
                        return "0"
                    return value_str.strip().replace(',', '')

                # Mapeo manual para los campos de la tabla hija desde el nuevo formato CSV
                aliquot_doc = {
                    "aliquot": clean_numeric_str(aliquot_data.get("Aliquot (aliquot)")),
                    "payments_greater_than_bs": clean_numeric_str(aliquot_data.get("Payments greater than bs (aliquot)")),
                    "percentage_base": clean_numeric_str(aliquot_data.get("Percentage base (aliquot)")),
                    "subtracting": clean_numeric_str(aliquot_data.get("Subtracting (aliquot)")),
                    "types_of_person": aliquot_data.get("Types of person (aliquot)", "").strip(),
                }
                doc.append("aliquot", aliquot_doc)

            try:
                doc.save(ignore_permissions=True)
                print(f"  -> Creado concepto: {codigo} - {doc.descripcion} con {len(doc.aliquot)} alícuotas.")
            except frappe.ValidationError as e:
                print(f"!! FAILURE al guardar el código '{codigo}': {e}")

        frappe.db.commit()
        print("\nSuccess: Proceso de creación del Tabulador de ISLR completado.")

    except FileNotFoundError:
        print(f"!! FATAL: No se encontró el archivo CSV en la ruta: {csv_file_path}")
    except Exception as e:
        print(f"!! FATAL: Ocurrió un error inesperado: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_islr_tabulator')


def set_chart_of_accounts(company_name: str = None) -> None:
    """
    Configura las cuentas contables de impuestos en los campos
    personalizados del Doctype Company para cada compañía existente.
    Si se proporciona `company_name`, solo se configura esa compañía.
    """

    target = f"la compañía '{company_name}'" if company_name else "todas las Compañías"
    print(f"Iniciando la configuración de cuentas contables en {target}...")

    try:
        account_map = [
            {
                'account_name': 'Cuenta de costos (venta) por defecto',
                'account_number': '5.1.1.1.01',
                'company_field': 'default_expense_account',
            },
            {
                'account_name': 'Cuenta de efectivo por defecto',
                'account_number': '1.1.1.1.01',
                'company_field': 'default_cash_account',
            },
            {
                'account_name': 'Cuenta de ingresos por defecto',
                'account_number': '4.1.1.1.01',
                'company_field': 'default_income_account',
            },
            {
                'account_name': 'Cuenta por cobrar por defecto',
                'account_number': '1.1.3.1.01',
                'company_field': 'default_receivable_account',
            },
            {
                'account_name': 'Cuenta por pagar por defecto',
                'account_number': '2.1.2.1.01',
                'company_field': 'default_payable_account',
            },
            {
                'account_name': 'Cuenta de Desajuste',
                'account_number': '1.6.1.1.01',
                'company_field': 'write_off_account',
            },
            {
                'account_name': 'Cuenta de Pérdidas/Ganancias no realizada',
                'account_number': '4.1.2.1.04',
                'company_field': 'unrealized_profit_loss_account',
            },
            {
                'account_name': 'Cuenta de Ganancias / Pérdidas en Cambio',
                'account_number': '8.1.3.3.01',
                'company_field': 'exchange_gain_loss_account',
            },
            {
                'account_name': 'Cuenta de descuento por pago predeterminado',
                'account_number': '1.1.3.1.01',
                'company_field': 'default_discount_account',
            },
            {
                'account_name': 'Cuenta de Ganancia / Pérdida de Canje no Realizada',
                'account_number': '8.1.3.3.01',
                'company_field': 'unrealized_exchange_gain_loss_account',
            },
            {
                'account_name': 'Cuenta de redondeo por defecto',
                'account_number': '4.1.2.2.01',
                'company_field': 'round_off_account',
            },
            {
                'account_name': 'Cuenta de Redondeo para Apertura',
                'account_number': '4.1.2.2.01',
                'company_field': 'round_off_for_opening',
            },
            {
                'account_name': 'Cuenta de Ingresos Diferidos Predeterminada',
                'account_number': '2.6.1.1.01',
                'company_field': 'default_deferred_revenue_account',
            },
            {
                'account_name': 'Cuenta de Gastos Diferidos Predeterminada',
                'account_number': '1.6.1.1.01',
                'company_field': 'default_deferred_expense_account',
            },
            {
                'account_name': 'Cuenta de depreciación acumulada',
                'account_number': '1.3.1.5.02',
                'company_field': 'accumulated_depreciation_account',
            },
            {
                'account_name': 'Cuenta de ganancias/pérdidas por enajenación de activos fijos',
                'account_number': '6.1.2.2.05',
                'company_field': 'disposal_account',
            },
            {
                'account_name': 'Cuenta de gastos de depreciación',
                'account_number': '6.1.5.1.01',
                'company_field': 'depreciation_expense_account',
            },
            {
                'account_name': 'Gastos incluidos en la valoración de activos',
                'account_number': '6.1.2.2.05',
                'company_field': 'expenses_included_in_asset_valuation',
            },
            {
                'account_name': 'Cuenta de Activo recibido pero no facturado',
                'account_number': '1.3.1.5.01',
                'company_field': 'asset_received_but_not_billed',
            },
            {
                'account_name': 'Cuenta de IVA en ventas',
                'account_number': '2.1.2.4.01',
                'company_field': 'sales_vat_account',
            },
            {
                'account_name': 'Cuenta de IVA en compras',
                'account_number': '1.2.1.1.01',
                'company_field': 'purchase_vat_account',
            },
            {
                'account_name': 'Cuenta de Retención de IVA en ventas',
                'account_number': '1.2.1.1.02',
                'company_field': 'sales_vat_withholding_account',
            },
            {
                'account_name': 'Cuenta de Retención de IVA en Compras',
                'account_number': '2.1.2.4.04',
                'company_field': 'purchase_vat_withholding_account',
            },
            {
                'account_name': 'Cuenta ISLR en ventas',
                'account_number': '1.2.1.1.06',
                'company_field': 'sales_islr_account',
            },
            {
                'account_name': 'Cuenta ISLR en Compras',
                'account_number': '2.1.2.4.06',
                'company_field': 'purchase_islr_account',
            },
            {
                'account_name': 'Cuenta IGTF en Ventas',
                'account_number': '2.1.2.2.06',
                'company_field': 'sales_igtf_account',
            },
            {
                'account_name': 'Cuenta IGTF en Compras',
                'account_number': '6.1.7.1.04',
                'company_field': 'purchase_igtf_account',
            },
            {
                'account_name': 'Cuenta de Inventario Predeterminada',
                'account_number': '1.1.5.1.01',
                'company_field': 'default_inventory_account',
            },
            {
                'account_name': 'Cuenta de Inventario Recibido pero no Facturado',
                'account_number': '1.1.5.1.01',
                'company_field': 'stock_received_but_not_billed',
            },
            {
                'account_name': 'Cuenta provisional predeterminada',
                'account_number': '1.6.1.1.01',
                'company_field': 'default_provisional_account',
            },
            {
                'account_name': 'Cuenta de ajuste de existencias',
                'account_number': '1.6.1.1.01',
                'company_field': 'stock_adjustment_account',
            },
            {
                'account_name': 'Cuenta GASTOS DE VALORACIÓN',
                'account_number': '6.1.2.2.05',
                'company_field': 'expenses_included_in_valuation',
            },
            {
                'account_name': 'Cuenta de costos operativos por defecto',
                'account_number': '6.1.2.1.01',
                'company_field': 'default_operating_cost_account',
            },
            {
                'account_name': 'Cuenta bancaria por defecto',
                'account_number': '1.1.2.1.01',
                'company_field': 'default_bank_account',
            },
            {
                'account_name': 'Capital Work in Progress por defecto',
                'account_number': '1.3.1.9.03',
                'company_field': 'capital_work_in_progress_account',
            },
            {
                'account_name': 'ANTICIPOS DECLIENTES',
                'account_number': '2.1.2.1.09',
                'company_field': 'default_advance_received_account',
            },
            {
                'account_name': 'ANTICIPO A PROVEEDORES NACIONALES',
                'account_number': '1.1.3.4.01',
                'company_field': 'default_advance_paid_account',
            },
        ]

        if company_name:
            companies = \
                frappe.get_all("Company",
                                filters={"name": company_name},
                                fields=["name", "abbr"])
        else:
            companies = frappe.get_all("Company", fields=["name", "abbr"])

        for company in companies:
            print(f"Configurando cuentas para la compañía: {company.name}")

            for account_info in account_map:
                company_field = account_info['company_field']

                account_name = frappe.get_value("Account",
                                                {
                                                    "company": company.name,
                                                    "account_number": account_info['account_number'],
                                                },
                                                "name")

                if not account_name:
                    print(f"  !! ADVERTENCIA: La cuenta {account_info['account_number']} no existe para la compañía {company.name}. Se omitirá.")
                    continue

                frappe.db.set_value("Company",
                                    company.name,
                                    company_field,
                                    account_name)

                print(f" Cuenta '{account_name}' enlazada satisfactoriamente en el campo '{company_field}'.")

            frappe.db.set_value('Company',
                                company,
                                'book_advance_payments_in_separate_party_account',
                                True)
        frappe.db.commit()

    except Exception as e:
        print(f" !! ERROR configurando las cuentas contables: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en set_chart_of_accounts')

    print("Success: Configuración de cuentas contables en las compañías completada.")


def create_vat_withholding(company_name: str = None) -> None:
    """
    Crea o actualiza las categorías de retención de IVA.
    Si se proporciona `company_name`, solo se agregan las cuentas de esa compañía.
    """
    target = f"la compañía '{company_name}'" if company_name else "todas las Compañías"
    print(f"Configurando retenciones de IVA para {target}...")

    try:
        company_filters = {"name": company_name} if company_name else {}
        companies = \
            frappe.db.get_all('Company',
                                      filters=company_filters,
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
            withholding_name = f'IVA Retencion {aliquot}%'

            if not frappe.db.exists('Tax Withholding Category', withholding_name):
                withholding.name = withholding_name
                withholding.append('rates', {
                    'to_date': to_date,
                    'from_date': from_date,
                    'charge_type': 'VAT Withholding',
                    'tax_withholding_rate': aliquot,
                })
            else:
                withholding = frappe.get_doc('Tax Withholding Category', withholding_name)

            for company in companies:

                if not (company.get('sales_vat_withholding_account') and company.get('purchase_vat_withholding_account')):
                    print(f"  !! ADVERTENCIA: Cuentas de retención de IVA no configuradas para la compañía '{company.name}'. Se omitirá.")
                    continue

                withholding.append('accounts', {
                    'company': company['name'],
                    'account': company['purchase_vat_withholding_account'],
                    'sales_account': company['sales_vat_withholding_account'],
                })

            withholding.save(ignore_permissions=True)

        print(f"Retenciones de IVA configuradas exitosamente")

    except Exception as e:
        print(f"Failure: Ocurrió un error durante la creación de las retenciones de IVA: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_vat_withholding')


def create_sales_taxes_and_charges_template(company_name: str = None) -> None:
    """
    Crea las plantillas de impuestos y cargos de IVA para ventas y compras.
    Si se proporciona `company_name`, solo se crean para esa compañía.
    """
    target = f"la compañía '{company_name}'" if company_name else "todas las Compañías"
    print(f"Creando plantillas de impuestos de IVA para {target}...")

    try:
        template_types = {
            'Sales': 'sales_vat_account',
            'Purchase': 'purchase_vat_account'
        }

        if company_name:
            companies = frappe.get_all("Company",
                                        filters={"name": company_name},
                                          fields=["name", "abbr"])
        else:
            companies = frappe.get_all('Company', fields=['name', 'abbr'])

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


def set_mode_of_payments(company_name: str = None) -> None:
    """
    Configura las cuentas por defecto en los modos de pago.
    Si se proporciona `company_name`, solo se configuran las cuentas para esa compañía.
    """
    target = f"la compañía '{company_name}'" if company_name else "todas las Compañías"
    print(f"Configurando modos de pago para {target}...")

    mode_of_payments = [
        {
            'mode_of_payment': 'Biopago',
            'account_number': '2.1.1.2.01',
            'type': 'Gangway',
            'visibility_type': 'Private'
        },
        {
            'mode_of_payment': 'Pagomóvil',
            'account_number': '2.1.1.2.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
        {
            'mode_of_payment': 'Tarjetas de crédito',
            'account_number': '2.1.1.2.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
        {
            'mode_of_payment': 'Tarjetas de débito',
            'account_number': '2.1.1.2.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
        {
            'mode_of_payment': 'Transferencia bancaria',
            'account_number': '1.1.2.1.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
        {
            'mode_of_payment': 'Giro bancario',
            'account_number': '1.1.2.1.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
        {
            'mode_of_payment': 'Efectivo',
            'account_number': '1.1.1.1.01',
            'type': 'Cash',
            'visibility_type': 'Private'
        },
        {
            'mode_of_payment': 'Cheque',
            'account_number': '1.1.2.1.01',
            'type': 'Bank',
            'visibility_type': 'Public'
        },
    ]

    try:

        if company_name:
            companies = frappe.get_all("Company",
                                        filters={"name": company_name},
                                          pluck='name')
        else:
            companies = frappe.db.get_all('Company', pluck='name')

        for mode in mode_of_payments:
            mop_name = mode['mode_of_payment']
            mop_type = mode['type']
            mop_visibility_type = mode['visibility_type']
            
            if not frappe.db.exists('Mode of Payment', mop_name):
                print(f"  + Creando nuevo Modo de Pago: '{mop_name}'")
                doc = frappe.new_doc('Mode of Payment')
                doc.mode_of_payment = mop_name
                doc.type = mop_type
                doc.visibility_type = mop_visibility_type
                doc.insert(ignore_permissions=True)

            mode_of_payment = frappe.get_doc('Mode of Payment', mop_name)

            for company in companies:
                default_account: str = frappe.db.get_value('Account', {
                    'company': company,
                    'account_number': mode['account_number']
                }, 'name')

                if not default_account:
                    print(f'  !! ADVERTENCIA: No se encontró la cuenta con número '
                          f'{mode["account_number"]} para la compañía {company}.')
                    continue

                existing_account_entry = None
                for acc_entry in mode_of_payment.accounts:
                    if acc_entry.company == company:
                        existing_account_entry = acc_entry
                        break

                if existing_account_entry:

                    if existing_account_entry.default_account != default_account:
                        existing_account_entry.default_account = default_account

                        print(f'  -> Actualizando cuenta a {default_account} en el modo de pago '
                              f'{mode["mode_of_payment"]} para la compañía {company}')

                    else:
                         print(f'  -- Omitiendo (ya está configurado correctamente): Modo de pago '
                               f'{mode["mode_of_payment"]} para la compañía {company}.')
                else:
                    mode_of_payment.append('accounts', {
                        'company': company,
                        'default_account': default_account,
                    })

                    print(f'  -> Agregando cuenta {default_account} al modo de pago '
                          f'{mode["mode_of_payment"]} para la compañía {company}')

            mode_of_payment.save(ignore_permissions=True)

    except Exception as e:
        print(f"Failure: Ocurrió un error configurando los modos de pago: {e}")
        frappe.log_error(frappe.get_traceback(),
                         'Error configurando los modos de pago:')


def set_reference_currency(company_name: str = None) -> None:

    target = f"la compañía '{company_name}'" if company_name else "todas las Compañías"
    print(f"Estableciendo moneda de referencia en {target}...")

    try:
        if company_name:
            companies = frappe.get_all("Company",
                                        filters={"name": company_name},
                                          pluck='name')

        else:
            companies: list[str] = frappe.db.get_all('Company', pluck='name')

        if not companies:
            print(f"  -- Omitiendo: No se encontraron compañías para procesar.")
            return

        currency = 'USD'
        for company in companies:
            frappe.db.set_value('Company',
                                company,
                                'reference_currency',
                                currency)

            print(f"  -> Moneda de referencia {currency} establecida para la compañía {company}")

        frappe.db.set_value('Currency',
                             currency,
                            {'symbol': 'REF.'})

        print(f"  -> Símbolo 'REF.' establecido para la moneda {currency}")
        set_pricelist_on_reference_currency(currency)

        print("Success: Configuración de moneda de referencia completada.")

    except Exception as e:
        print(f"Failure: Ocurrió un error configurando la moneda de referencia: {e}")
        frappe.log_error(title='Error configurando la moneda de referencia:',
                         message=frappe.get_traceback())


def set_pricelist_on_reference_currency(currency: str) -> None:

    print(f'Estableciendo moneda {currency} en las listas de precios')

    try:
        price_lists: list[str] = frappe.db.get_all('Price List', pluck='name')

        for pricelist in price_lists:
            frappe.db.set_value('Price List', pricelist, 'currency', currency)


        print(f'Moneda {currency} establecida correctamente')

    except Exception as e:
        print(f"Failure: Ocurrió un error estableciendo moneda {currency} en las listas de precios: {e}")
        frappe.log_error(title=f'Error estableciendo moneda {currency} en las listas de precios:',
                         message=frappe.get_traceback())


def set_allow_multi_currency_invoices() -> None:
    try:
        print(f'Estableciendo multimoneda en la configuración contable')

        frappe.db.set_value(
            "Accounts Settings",
            "Accounts Settings",
            "allow_multi_currency_invoices_against_single_party_account",
            1
        )

        print(f'Multimoneda en facturas establecida correctamente')

    except Exception as e:
        print(f"Failure: Ocurrió un error estableciendo Multimoneda en facturas: {e}")
        frappe.log_error(title=f'Error estableciendo Multimoneda en facturas:',
                         message=frappe.get_traceback())

def load_venezuela_data() -> None:
    STATE_DOCTYPE = "VE State"
    MUNICIPALITY_DOCTYPE = "VE Municipality"
    PARISH_DOCTYPE = "VE Parish"
    CITY_DOCTYPE = "VE City"

    COUNTRY_ID = "Venezuela, Bolivarian Republic of"
    JSON_FILE_PATH = frappe.get_app_path("l10n_ve", "resources", "venezuela.json")

    print("Iniciando la carga de datos regionales de Venezuela...")

    try:
        frappe.get_doc("Country", COUNTRY_ID.strip())
    except frappe.DoesNotExistError:
        try:
            country_doc = frappe.new_doc("Country")
            country_doc.country_name = COUNTRY_ID.strip()
            country_doc.code = "VE"
            country_doc.insert(ignore_permissions=True, ignore_mandatory=True)
            print(f"  -> Creado DocType Country: {COUNTRY_ID.strip()}")
        except Exception as e:
            frappe.throw(_(f"Fallo al crear el DocType Country '{COUNTRY_ID.strip()}'. Error: {e}"))
            return
    except Exception as e:
        frappe.throw(_(f"Error al obtener el DocType Country: {e}"))
        return

    try:
        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        frappe.throw(_(f"Error al leer o decodificar el archivo JSON: {e}"))
        return

    country_name = COUNTRY_ID.strip()

    try:
        for i, state_data in enumerate(data):
            state_name_from_json = state_data.get("estado")
            ve_state_name = None

            state_filters = {
                "state": state_name_from_json,
                "country": country_name
            }

            existing_state_name = frappe.db.get_value(
                STATE_DOCTYPE,
                state_filters,
                "name"
            )

            if existing_state_name:
                ve_state_name = existing_state_name
                print(f"-- Omitiendo Estado (ya existe): {state_name_from_json}")
            else:
                state_doc = frappe.new_doc(STATE_DOCTYPE)
                state_doc.country = country_name
                state_doc.state = state_name_from_json
                state_doc.capital = state_data.get("capital")
                state_doc.insert(ignore_permissions=True, ignore_mandatory=True)
                ve_state_name = state_doc.name
                print(f"-> Creado Estado: {state_doc.state}")

            # frappe.db.commit()

            for municipality_data in state_data.get("municipios", []):
                municipality_name_from_json = municipality_data.get("municipio")
                ve_municipality_name = None

                municipality_filters = {
                    "municipality": municipality_name_from_json,
                    "state": ve_state_name,
                    "country": country_name
                }

                existing_municipality_name = frappe.db.get_value(
                    MUNICIPALITY_DOCTYPE,
                    municipality_filters,
                    "name"
                )

                if existing_municipality_name:
                    ve_municipality_name = existing_municipality_name
                else:
                    municipality_doc = frappe.new_doc(MUNICIPALITY_DOCTYPE)
                    municipality_doc.state = ve_state_name
                    municipality_doc.country = country_name
                    municipality_doc.municipality = municipality_name_from_json
                    municipality_doc.capital = municipality_data.get("capital")
                    municipality_doc.insert(ignore_permissions=True, ignore_mandatory=True)
                    ve_municipality_name = municipality_doc.name

                for parish_name in municipality_data.get("parroquias", []):

                    parish_filters = {
                        "parish": parish_name,
                        "municipality": ve_municipality_name,
                        "country": country_name
                    }

                    if frappe.db.exists(PARISH_DOCTYPE, parish_filters):
                        continue

                    parish_doc = frappe.new_doc(PARISH_DOCTYPE)
                    parish_doc.municipality = ve_municipality_name
                    parish_doc.state = ve_state_name
                    parish_doc.country = country_name
                    parish_doc.parish = parish_name
                    parish_doc.insert(ignore_permissions=True, ignore_mandatory=True)

                # frappe.db.commit()

            for city_name in state_data.get("ciudades", []):

                city_filters = {
                    "city": city_name,
                    "state": ve_state_name,
                    "country": country_name
                }

                if frappe.db.exists(CITY_DOCTYPE, city_filters):
                    continue

                city_doc = frappe.new_doc(CITY_DOCTYPE)
                city_doc.state = ve_state_name
                city_doc.country = country_name
                city_doc.city = city_name
                city_doc.insert(ignore_permissions=True, ignore_mandatory=True)

            # frappe.db.commit()

        frappe.db.commit()
        print("\nSuccess: Proceso de carga de datos regionales completado.")
        frappe.msgprint(_("Datos de Venezuela cargados exitosamente."))

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(message=frappe.get_traceback(), title="Error en load_venezuela_data")
        frappe.throw(_(f"Fallo la carga de datos. Revierte los cambios. Error: {e}"))

def create_bank_venezuelan()->str:
    """
    Importa una lista de bancos venezolanos desde un archivo JSON al DocType Bank.
    """
    print("Iniciando la importación de bancos venezolanos...")

    app_path = frappe.get_app_path('l10n_ve')
    json_path = os.path.join(app_path, 'resources', 'Bank_venezuelan.json')

    if not os.path.exists(json_path):
        frappe.throw(f"Archivo no encontrado en la ruta: {json_path}")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            bancos = json.load(f)
    except Exception as e:
        frappe.throw(_(f"Error al leer o decodificar el archivo JSON de bancos: {e}"))
        return

    bancos_creados = 0
    bancos_existentes = 0
    errores = []

    country_name = "Venezuela, Bolivarian Republic of"

    for banco_data in bancos:
        codigo_banco = banco_data.get('codigo')
        nombre_banco = banco_data.get('nombre')

        if not codigo_banco or not nombre_banco:
            frappe.log_message("Entrada de banco inválida, se omite", f"Datos: {banco_data}")
            errores.append(f"Entrada de banco inválida: {banco_data}")
            continue

        if frappe.db.exists("Bank", {"swift_number": codigo_banco}):
            bancos_existentes += 1
            print(f"  -- Omitiendo (ya existe por código SWIFT): '{nombre_banco}' ({codigo_banco})")
            continue

        if frappe.db.exists("Bank", {"bank_name": nombre_banco}):
            bancos_existentes += 1
            print(f"  -- Omitiendo (ya existe por nombre): '{nombre_banco}' ({codigo_banco})")
            continue

        try:
            nuevo_banco = frappe.get_doc({
                "doctype": "Bank",
                "bank_name": nombre_banco,
                "swift_number": codigo_banco,
                "country": country_name
            })
            nuevo_banco.insert(ignore_permissions=True)
            bancos_creados += 1
            print(f"  -> Creado Banco: '{nombre_banco}' ({codigo_banco})")

        except Exception as e:
            error_msg = f"Error al crear el banco '{nombre_banco}' ({codigo_banco}): {e}"
            frappe.log_error(error_msg, "Error de Importación de Bancos")
            errores.append(error_msg)

    frappe.db.commit()

    mensaje = f"Importación de bancos venezolanos completada. Bancos creados:"\
            F"{bancos_creados}. Bancos que ya existían: {bancos_existentes}."
    if errores:
        mensaje += f" Errores encontrados: {len(errores)}."
        frappe.msgprint(mensaje + "\n" + "\n".join(errores),
                        title="Importación de Bancos con Errores", indicator="red")
    else:
        frappe.msgprint(mensaje, title="Importación de Bancos Exitosa", indicator="green")

    print(f"Success: {mensaje}")
    return mensaje

def create_bank_account_types() -> str:
    """
    Carga los tipos de cuenta bancaria 'Corriente' y 'Ahorro' en el DocType Bank Account Type.
    """
    print("Iniciando la carga de tipos de cuenta bancaria...")

    account_types = ["Cuenta Corriente", "Cuenta de Ahorro"]
    created_count = 0
    existing_count = 0

    for account_type_name in account_types:
        if frappe.db.exists("Bank Account Type", account_type_name):
            existing_count += 1
            print(f"  -- Omitiendo (ya existe): Tipo de cuenta '{account_type_name}'")
        else:
            try:
                doc = frappe.new_doc("Bank Account Type")
                doc.account_type = account_type_name
                doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"  -> Creado Tipo de cuenta: '{account_type_name}'")
            except Exception as e:
                frappe.log_error(f"Error al crear el tipo de cuenta"
                                 f"'{account_type_name}': {e}", "Error de Importación de Tipos de Cuenta Bancaria")

    frappe.db.commit()

    mensaje = (f"Carga de tipos de cuenta bancaria completada. "
               f"Tipos creados: {created_count}. "
               f"Tipos que ya existían: {existing_count}.")
    frappe.msgprint(mensaje, title="Carga de Tipos de Cuenta Bancaria", indicator="green")
    print(f"Success: {mensaje}")
    return mensaje

def create_economic_activities() -> None:
    """
    Crea los registros de Actividades Económicas a partir de un archivo CSV.
    """
    print("Iniciando la creación de Actividades Económicas...")

    csv_file_path = frappe.get_app_path('l10n_ve', 'resources', 've_economic_activity.csv')
    doctype = "VE Economic Activity"

    try:
        with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            activities = list(reader)

        for row in activities:
            if row.get("is_group") == "1":
                if not frappe.db.exists(doctype, {"code": row["code"]}):
                    doc = frappe.new_doc(doctype)
                    doc.code = row["code"]
                    doc.description = row["description"]
                    doc.sector = row.get("sector")
                    doc.group = row["group"]
                    doc.branch = row["branch"]
                    doc.is_group = 1
                    doc.save(ignore_permissions=True)
                    print(f"  -> Creado grupo padre: {doc.code}")

        frappe.db.commit()

        for row in activities:
            if row.get("is_group") != "1":
                if not frappe.db.exists(doctype, {"code": row["code"]}):
                    doc = frappe.new_doc(doctype)
                    doc.code = row["code"]
                    doc.description = row["description"]
                    doc.sector = row.get("sector")
                    doc.group = row.get("group")
                    doc.branch = row.get("branch")

                    parent_code = row["parent_code"]
                    parent_doc_name = frappe.db.get_value(doctype,
                                                         {"code": parent_code},
                                                         "name")

                    if not parent_doc_name:
                        frappe.throw(f"No se pudo encontrar la Actividad "
                                     f"Económica VE Padre con el código: {parent_code}")

                    doc.parent_ve_economic_activity = parent_doc_name
                    doc.save(ignore_permissions=True)
                    print(f"  -> Creada actividad hija: {doc.code}")

        frappe.db.commit()
        print("\nSuccess: Proceso de creación de Actividades Económicas completado.")
    except Exception as e:
        print(f"!! FATAL: Ocurrió un error inesperado durante la creación de actividades económicas: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_economic_activities')

def uncheck_all_prepared_reports() -> None:
    print(f"Estableciendo valor 0 en prepared_report en Report")
    try:
        report_list: list[str] = frappe.db.get_all('Report', pluck='name')

        for report in report_list:
            frappe.db.set_value('Report', report, 'prepared_report', 0)

        frappe.db.commit()
        print("El campo 'prepared_report' ha sido desmarcado en todos los Reportes.")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error al desmarcar reportes", message=str(e))
        frappe.throw("Ocurrió un error al actualizar los reportes.")

def disable_rounded_total() -> None:
    print(f"Estableciendo valor 1 en disable_rounded_total en Global Defaults")
    try:
        frappe.db.set_value('Global Defaults', 'Global Defaults', 'disable_rounded_total', 1)

        frappe.db.commit()
        print("El campo 'disable_rounded_total' ha sido marcado en Global Defaults.")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error al establecer valor 1 en disable_rounded_total", message=str(e))
        frappe.throw("Ocurrió un error al actualizar disable_rounded_total en Global Defaults.")


def set_buying_naming_series() -> None:
    print(f"Estableciendo Naming Series en Buying Series")
    try:
        frappe.db.set_value('Buying Settings',
                            'Buying Settings',
                            'supp_master_name',
                            'Naming Series')

        frappe.db.commit()
        print("El campo 'supp_master_name' en Buying Settings establecido como Naming Series")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error Estableciendo Naming Series en Buying Serie", message=str(e))
        frappe.throw("Ocurrió un error Estableciendo Naming Series en Buying Serie")


def set_selling_settings() -> None:
    print(f"Estableciendo Naming Series en Selling Series")
    try:
        frappe.db.set_value('Selling Settings',
                            'Selling Settings',
                            'cust_master_name',
                            'Naming Series')

        frappe.db.commit()
        print("El campo 'cust_master_name' en Selling Settings establecido como Naming Series")

        frappe.db.set_value('Selling Settings',
                            'Selling Settings',
                            'allow_multiple_items',
                            False)

        frappe.db.commit()
        print("Success: El campo 'allow_multiple_items' en Selling Settings establecido como False")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error Estableciendo configuraciones en Selling Settings", message=str(e))
        frappe.throw("Ocurrió un error Estableciendo configuraciones en Selling Settings")


def set_stock_naming_series() -> None:
    print(f"Estableciendo Naming Series en Stock Series")
    try:
        frappe.db.set_value('Stock Settings',
                            'Stock Settings',
                            'item_naming_by',
                            'Naming Series')

        frappe.db.commit()
        print("El campo 'item_naming_by' en Stock Settings establecido como Naming Series")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error Estableciendo Naming Series en Stock Serie", message=str(e))
        frappe.throw("Ocurrió un error Estableciendo Naming Series en Stock Serie")


def create_municipality_taxes_for_municipality(municipality_doc_name: str) -> None:
    """
    Crea los impuestos municipales para un municipio específico si no existen.
    :param municipality_doc_name: El nombre del DocType 'VE Municipality' para el cual crear los impuestos.
    """
    doctype = "VE Municipality Taxes"

    if frappe.db.exists(doctype, {"municipality": municipality_doc_name}):
        print(f"  -- Omitiendo (ya existen): Impuestos para el municipio {municipality_doc_name}.")
        return

    municipality_info = frappe.get_doc("VE Municipality", municipality_doc_name)
    print(f"-> Creando impuestos bajo demanda para el municipio: {municipality_info.municipality}")

    csv_file_path = frappe.get_app_path('l10n_ve', 'resources', 've_municipality_taxes.csv')
    try:
        tax_rules = []
        with open(csv_file_path, 'r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                tax_rules.append(row)

    except Exception as e:
        frappe.log_error(f"Error al leer el archivo ve_municipality_taxes.csv: {e}",
                         "Creación de Impuestos Municipales")
        return

    activities_map = {a.code: a.name for a in frappe.get_all("VE Economic Activity", fields=["name", "code"])}

    created_count = 0
    for tax_rule in tax_rules:
        economic_activity_code = tax_rule.get("economic_activity")
        ve_economic_activity_doc_name = activities_map.get(economic_activity_code)

        if not ve_economic_activity_doc_name:
            frappe.log_error(f"Actividad económica con código '{economic_activity_code}' no encontrada. Se omite la regla.",
                             "Creación de Impuestos Municipales")
            continue

        try:
            new_tax_doc = frappe.new_doc(doctype)
            new_tax_doc.state = municipality_info.state
            new_tax_doc.municipality = municipality_info.name
            new_tax_doc.economic_activity = ve_economic_activity_doc_name
            new_tax_doc.aliquot = float(tax_rule.get("aliquot") or 0)
            new_tax_doc.mt_tcmmv = float(tax_rule.get("mt_tcmmv") or 0)
            new_tax_doc.insert(ignore_permissions=True, ignore_mandatory=True)
            created_count += 1

        except Exception as e:
            frappe.log_error(
                f"Error creando impuesto para {municipality_info.municipality}"
                f"y actividad {economic_activity_code}: {e}",
                "Creación de Impuestos Municipales"
            )

    if created_count > 0:
        frappe.db.commit()
        message = _("Se han creado {0} nuevos registros de impuestos para el municipio {1}.").format(
            frappe.bold(created_count), frappe.bold(municipality_info.municipality)
        )
        if not frappe.flags.in_install:
            frappe.msgprint(message, title=_("Impuestos Municipales Creados"), indicator="green")
        print(f"Success: {created_count} impuestos creados para {municipality_info.municipality}.")

def create_municipality_taxes() -> None:
    """
    Crea los impuestos municipales solo para el municipio Libertador durante la instalación.
    """
    print("Iniciando la creación de Impuestos Municipales para Libertador...")

    try:
        libertador_state = frappe.db.get_value("VE State", {"state": "Distrito Capital"}, "name")
        if not libertador_state:
            print("  -- Omitiendo: No se encontró el estado 'Distrito Capital'.")
            return

        libertador_municipality_name = frappe.db.get_value("VE Municipality",
                                                          {"municipality": "Libertador",
                                                           "state": libertador_state})
        if not libertador_municipality_name:
            print("  -- Omitiendo: No se encontró el municipio 'Libertador' en 'Distrito Capital'.")
            return

        create_municipality_taxes_for_municipality(libertador_municipality_name)

    except Exception as e:
        frappe.db.rollback()

        print(f"!! FATAL: Ocurrió un error inesperado durante la creación de impuestos municipales: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_municipality_taxes')

def set_stock_settings() -> None:

    print(f"Estableciendo valores en Stock Settings")
    try:
        settings_to_update = {
            "auto_indent": 0,
            "disable_serial_no_and_batch_selector": 0,
            "do_not_update_serial_batch_on_creation_of_auto_bundle": 0,
            "auto_create_serial_and_batch_bundle_for_outward": 0,
            "allow_existing_serial_no": 0,
            "enable_stock_reservation": 0,
        }

        frappe.db.set_value('Stock Settings',
                            'Stock Settings',
                            settings_to_update)

        frappe.db.commit()
        print("Varios campos en Stock Settings han sido desactivados.")

    except Exception as e:
        frappe.db.rollback()
        frappe.log_error(title="Error estableciendo valores en Stock Settings", message=str(e))
        frappe.throw("Ocurrió un error al actualizar Stock Settings.")


def create_bank_transaction_mappings() -> None:
    """
    Actualiza los DocTypes de Banco existentes para añadirles las reglas de mapeo
    de transacciones bancarias.
    """
    print("Iniciando la creación de mapeos de transacciones bancarias...")

    if not frappe.db.has_table("Bank Transaction Mapping"):
        print("  -- Omitiendo: El DocType 'Bank Transaction Mapping' (tabla hija) no se encuentra en esta versión de ERPNext.")
        return

    bank_mappings = {
        "0102": "Banco de Venezuela",
        "0172": "Bancamiga"
    }

    bank_mapping_rules = {
        "0102": [
            {'bank_transaction_field': 'date', 'file_field': 'Fecha'},
            {'bank_transaction_field': 'deposit', 'file_field': 'Credito'},
            {'bank_transaction_field': 'withdrawal', 'file_field': 'Debito'},
            {'bank_transaction_field': 'reference_number', 'file_field': 'Referencia'},
            {'bank_transaction_field': 'description', 'file_field': 'Descripción'},
        ],
        "0172": [
            {'bank_transaction_field': 'date', 'file_field': 'Fecha'},
            {'bank_transaction_field': 'deposit', 'file_field': 'Credito'},
            {'bank_transaction_field': 'withdrawal', 'file_field': 'Debito'},
            {'bank_transaction_field': 'reference_number', 'file_field': 'Referencia'},
            {'bank_transaction_field': 'description', 'file_field': 'Concepto'},
        ]
    }

    for bank_code, bank_name in bank_mappings.items():
        try:
            bank_doc = frappe.get_doc("Bank", {"swift_number": bank_code})

            bank_doc.set("bank_transaction_mapping", [])

            for rule in bank_mapping_rules.get(bank_code, []):
                bank_doc.append("bank_transaction_mapping", rule)

            bank_doc.save(ignore_permissions=True)
            print(f"  -> Creado mapeo para el banco: '{bank_name}'.")


        except Exception as e:
            print(f"!! FAILURE al crear el mapeo para el banco con código '{bank_code}': {e}")
            frappe.log_error(frappe.get_traceback(), f'Error en create_bank_transaction_mappings para el banco {bank_code}')

    frappe.db.commit()
    print("Success: Creación de mapeos de transacciones bancarias completada.")


def disable_other_currencies() -> None:
    """
    Desactiva todas las monedas excepto VEF, USD y EUR.
    """
    print("\nDesactivando monedas no utilizadas...")

    allowed_currencies = ["VEF", "USD", "EUR"]
    disabled_count = 0

    try:
        currencies_to_disable = frappe.get_all(
            "Currency",
            filters={"name": ["not in", allowed_currencies], "enabled": 1},
            fields=["name"]
        )

        for currency_doc in currencies_to_disable:
            frappe.db.set_value("Currency", currency_doc.name, "enabled", 0)
            print(f"  -> Desactivada moneda: {currency_doc.name}")
            disabled_count += 1

        frappe.db.commit()
        print(f"Success: {disabled_count} monedas desactivadas.")

    except Exception as e:
        print(f"Failure: Ocurrió un error al desactivar monedas: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en disable_other_currencies')

def remove_module_onboarding() -> None:
    """
    Marca como completados los registros de 'Module Onboarding' para ocultar la sección
    de 'Primeros Pasos' (barra de progreso).
    """
    print("Iniciando la actualización de Module Onboarding (Primeros Pasos)...")

    try:
        modules_to_clean = frappe.get_all("Module Onboarding", pluck="name")

        if modules_to_clean:
            frappe.db.set_value("Module Onboarding", modules_to_clean, "is_complete", 1)
            print(f"  -> Se marcaron como completos {len(modules_to_clean)} módulos de onboarding.")

        frappe.db.commit()
        print("Success: Onboarding actualizado correctamente.")
    except Exception as e:
        print(f"Failure: Error al actualizar onboarding: {e}")
        frappe.log_error(title='Error en remove_module_onboarding', message=frappe.get_traceback(),)

def set_profiles() -> None:
    """
    Crea o actualiza un perfil de módulo para Domina Base, mostrando solo los módulos especificados.
    """
    profile_name = "Domina Base"
    print(f"Iniciando la creación/actualización del perfil de módulo '{profile_name}'...")

    try:
        modules_to_show = {
            "Stock", "Buying", "Contacts", "Accounts", "Expense Claims",
            "L10N Ve", "Projects", "Selling"
        }

        all_modules = frappe.get_all("Module Def", pluck="name")

        if frappe.db.exists("Module Profile", profile_name):
            module_profile = frappe.get_doc("Module Profile", profile_name)
            module_profile.set("block_modules", [])
            print(f"  -> Actualizando perfil de módulo existente: '{profile_name}'.")
        else:
            module_profile = frappe.new_doc("Module Profile")
            module_profile.module_profile_name = profile_name
            print(f"  -> Creando nuevo perfil de módulo: '{profile_name}'.")

        for module_name in all_modules:
            if module_name not in modules_to_show:
                module_profile.append("block_modules", {"module": module_name})

        module_profile.save(ignore_permissions=True)
        frappe.db.commit()
        print(f"  -> Perfil de módulo '{profile_name}' guardado"
              f"con {len(module_profile.block_modules)} módulos bloqueados.")

    except Exception as e:
        print(f"Failure: Ocurrió un error creando el perfil de módulo '{profile_name}': {e}")
        frappe.log_error(title=f"Error en set_profiles "
                               f"para '{profile_name}'", message=frappe.get_traceback())

def set_roles() -> None:
    """
    Crea dos perfiles de roles: Gerente Administrativo y Analista.
    """
    print("Iniciando la creación de perfiles de roles...")

    def _create_profile(profile_name, roles_to_add):

        if frappe.db.exists("Role Profile", profile_name):
            print(f"  -- Omitiendo (ya existe): Perfil de rol '{profile_name}'.")
            return

        print(f"  -> Creando perfil de rol: {profile_name}")
        if not roles_to_add:
            print(f"  !! ADVERTENCIA: No se encontraron roles para el perfil '{profile_name}'.")
            return

        role_profile = frappe.new_doc("Role Profile")
        role_profile.role_profile = profile_name
        for role_name in roles_to_add:
            role_profile.append("roles", {"role": role_name})
        role_profile.insert(ignore_permissions=True)
        print(f"  -> Perfil '{profile_name}' creado con {len(roles_to_add)} roles.")

    try:
        all_roles = frappe.get_all("Role", fields=["name"])
        all_role_names = {r['name'] for r in all_roles}

        profile_name_admin = "Gerente Administrativo"
        excluded_manager_roles = {"System Manager", "Workspace Manager", "Script Manager", "Website Manager"}
        manager_roles = [name for name in all_role_names if "Manager" in name and name not in excluded_manager_roles]
        _create_profile(profile_name_admin, manager_roles)

        profile_name_analista = "Analista"
        user_roles = [name for name in all_role_names if "User" in name]
        _create_profile(profile_name_analista, user_roles)

        frappe.db.commit()
        print("Success: Creación de perfiles de roles completada.")

    except Exception as e:
        print(f"Failure: Ocurrió un error creando perfiles de roles: {e}")
        frappe.log_error(title="Error en set_roles", message=frappe.get_traceback())

def get_compatible_workspace_name(priorities=None) -> str:
    """
    Busca un nombre de Workspace compatible en el sistema.
    """
    if not priorities:
        priorities = ["Accounting", "Accounts", "Financial Reports"]
        
    for name in priorities:
        if frappe.db.exists("Workspace", name):
            return name
    
    print(f"  !! No se encontró ningún Workspace compatible ({', '.join(priorities)}).")
    return None

def add_reports_to_accounts_workspace() -> None:
    """
    Agrega los reportes 'Customer Retention', 'IGTF received', 'sales_book' y 'purchase_book'
    al Workspace 'Financial Reports' (o 'Accounting').
    Actualiza tanto la tabla 'links' como el JSON 'content'.
    """
    print("Agregando reportes al Workspace...")
    try:
        workspace_name = get_compatible_workspace_name(["Financial Reports", "Accounting", "Accounts"])
        if not workspace_name:
            return

        workspace = frappe.get_doc("Workspace", workspace_name)
        print(f"  -> Workspace encontrado: {workspace_name}")

        reports_to_add = [
            {
                "type": "Link",
                "label": _("Retención de Clientes"),
                "link_to": "Customer Retention",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("IGTF Recibido"),
                "link_to": "IGTF received",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("Libro de Ventas"),
                "link_to": "Sales Book",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("Libro de Compras"),
                "link_to": "purchase_book",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("Retención de ISLR"),
                "link_to": "ISLR Withholding",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("Retención de IVA"),
                "link_to": "VAT Withholding",
                "link_type": "Report",
                "is_query_report": 1
            }
        ]

        links_to_move = [r["link_to"] for r in reports_to_add]
        
        initial_links_count = len(workspace.links)
        workspace.set("links", [l for l in workspace.links if l.link_to not in links_to_move])
        modified = len(workspace.links) != initial_links_count
        
        current_links = {l.link_to for l in workspace.links}

        card_break_label = "Reportes Venezuela"
        card_break_exists = any(l.label == card_break_label and l.type == 'Card Break' for l in workspace.links)

        if not card_break_exists:
            workspace.append("links", {
                "type": "Card Break",
                "label": card_break_label
            })
            modified = True
            print(f"  -> Agregado salto de tarjeta: {card_break_label}")

        for report in reports_to_add:
            if not frappe.db.exists("Report", report["link_to"]):
                print(f"  -- Omitiendo reporte no encontrado: {report['link_to']}")
                continue

            if report["link_to"] not in current_links:
                workspace.append("links", {
                    "label": report["label"],
                    "type": "Link",
                    "link_type": "Report",
                    "link_to": report["link_to"],
                    "is_query_report": 1
                })
                modified = True
                print(f"  -> Agregado a tabla links: {report['label']}")

        content = json.loads(workspace.content) if workspace.content else []
        if workspace.content:
            custom_card_name = "Reportes Venezuela"
            card_found = False

            for block in content:
                if block.get("type") == "card" and block.get("data", {}).get("card_name") == custom_card_name:
                    card_found = True
                    block["data"]["links"] = [r for r in reports_to_add if frappe.db.exists("Report", r["link_to"])]
                    modified = True
                    break
            
            if not card_found:
                print(f"  -> Creando nueva tarjeta visual '{custom_card_name}'...")
                new_card = {
                    "type": "card",
                    "data": {
                        "card_name": custom_card_name,
                        "col": 4,
                        "links": [r for r in reports_to_add if frappe.db.exists("Report", r["link_to"])]
                    }
                }
                content.append(new_card)
                modified = True

        if modified:
            if workspace.content:
                workspace.content = json.dumps(content)
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Workspace '{workspace_name}' actualizado con nuevos reportes.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya estaba actualizado.")

    except Exception as e:
        print(f"Failure: Error actualizando Workspace Accounts: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_reports_to_accounts_workspace')

def add_doctypes_to_accounting_workspace() -> None:
    """
    Agrega los DocTypes de configuración de l10n_ve al Workspace 'Accounting'.
    """
    print("Agregando DocTypes de l10n_ve al Workspace de Contabilidad...")
    try:
        workspace_name = get_compatible_workspace_name()
        if not workspace_name:
            return

        workspace = frappe.get_doc("Workspace", workspace_name)
        print(f"  -> Workspace encontrado: {workspace_name}")

        doctypes_to_add_config = [
            {"link_to": "Tax Unit", "label": _("Unidad Tributaria")},
            {"link_to": "Tabulator ISLR", "label": _("Tabulador de ISLR")},
            {"link_to": "VE Economic Activity", "label": _("Actividades Económicas")},
            {"link_to": "VE Municipality", "label": _("Municipios")},
            {"link_to": "VE Municipality Taxes", "label": _("Impuestos Municipales")},
            {"link_to": "VE Conatel Tax Type", "label": _("Impuestos CONATEL")},
            {"link_to": "Ve Branch", "label": _("Sucursales")},
            {"link_to": "Venezuela Account Settings", "label": _("Configuración")},
        ]

        links_to_add = []
        for dt in doctypes_to_add_config:
            links_to_add.append({
                "type": "Link",
                "label": dt["label"],
                "link_to": dt["link_to"],
                "link_type": "DocType",
            })

        links_to_move = [l["link_to"] for l in links_to_add]
        
        initial_links_count = len(workspace.links)
        workspace.set("links", [l for l in workspace.links if l.link_to not in links_to_move])
        modified = len(workspace.links) != initial_links_count
        
        current_links = {l.link_to for l in workspace.links}

        card_break_label = "Configuración Venezuela"
        card_break_exists = any(l.label == card_break_label and l.type == 'Card Break' for l in workspace.links)

        if not card_break_exists:
            workspace.append("links", {
                "type": "Card Break",
                "label": card_break_label
            })
            modified = True
            print(f"  -> Agregado salto de tarjeta: {card_break_label}")

        for link in links_to_add:
            if link["link_to"] not in current_links:
                workspace.append("links", {
                    "label": link["label"],
                    "type": "Link",
                    "link_type": "DocType",
                    "link_to": link["link_to"],
                })
                modified = True
                print(f"  -> Agregado a tabla links: {link['label']}")

        content = json.loads(workspace.content) if workspace.content else []
        custom_card_name = "Configuración Venezuela"
        card_found = False

        for block in content:
            if block.get("type") == "card" and block.get("data", {}).get("card_name") == custom_card_name:
                card_found = True
                block["data"]["links"] = [l for l in links_to_add if frappe.db.exists("DocType", l["link_to"])]
                modified = True
                break
        
        if not card_found:
            print(f"  -> Creando nueva tarjeta visual '{custom_card_name}'...")
            new_card = {
                "type": "card",
                "data": {
                    "card_name": custom_card_name,
                    "col": 4,
                    "links": [l for l in links_to_add if frappe.db.exists("DocType", l["link_to"])]
                }
            }
            content.append(new_card)
            modified = True
        
        if modified:
            workspace.content = json.dumps(content)
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Workspace '{workspace_name}' actualizado con DocTypes de l10n_ve.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya estaba actualizado.")

    except Exception as e:
        print(f"Failure: Error actualizando Workspace de Contabilidad: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_doctypes_to_accounting_workspace')

def create_conatel_tax_types() -> None:
    """
    Crea los tipos de tributos para la declaración de CONATEL.
    """
    print("Iniciando la creación de tipos de tributos CONATEL...")

    tax_types = [
        {"tax_name": "CONATEL Art. 146", "aliquot": 2.30},
        {"tax_name": "FSU Art. 147", "aliquot": 0.50},
        {"tax_name": "FIDETEL Art. 150", "aliquot": 1.00},
        {"tax_name": "Administración Art. 151", "aliquot": 0.50},
        {"tax_name": "Espectro Art. 148", "aliquot": 0.50}
    ]

    try:
        for t in tax_types:
            if not frappe.db.exists("VE Conatel Tax Type", t["tax_name"]):
                doc = frappe.new_doc("VE Conatel Tax Type")
                doc.tax_name = t["tax_name"]
                doc.aliquot = t["aliquot"]
                doc.insert(ignore_permissions=True)
                print(f"  -> Creado tipo de tributo: {t['tax_name']}")
            else:
                print(f"  -- Omitiendo (ya existe): {t['tax_name']}")

        frappe.db.commit()
        print("Success: Creación de tipos de tributos CONATEL completada.")

    except Exception as e:
        print(f"Failure: Ocurrió un error creando los tipos de tributos CONATEL: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_conatel_tax_types')

def setup_workspaces() -> None:
    """
    Ejecuta todas las configuraciones de Workspaces para l10n_ve.
    """
    print("Iniciando configuración de Workspaces...")
    add_reports_to_accounts_workspace()
    add_doctypes_to_accounting_workspace()
    add_vouchers_to_accounts_workspace()
    add_shortcuts_to_selling_workspace()

def add_shortcuts_to_selling_workspace() -> None:
    """
    Agrega accesos rápidos (shortcuts) al Workspace de Ventas:
      - Factura de Venta (Sales Invoice)
      - Nota de Crédito (VE Sales Credit Note)

    Frappe renderiza la sección "Acceso rápido" desde DOS lugares:
      1. Tabla hija `shortcuts` (datos del shortcut: label, link_to, type, color)
      2. Campo JSON `content` (layout: bloques type="shortcut" con shortcut_name = label)
    Ambos deben estar sincronizados para que aparezca en la UI.
    """
    print("Agregando shortcuts al Workspace de Ventas...")
    try:
        workspace_name = None
        for candidate in ("Selling", "Ventas"):
            if frappe.db.exists("Workspace", candidate):
                workspace_name = candidate
                break

        if not workspace_name:
            print("  !! No se encontró el Workspace 'Selling' / 'Ventas'. Omitiendo.")
            return

        workspace = frappe.get_doc("Workspace", workspace_name)
        print(f"  -> Workspace encontrado: {workspace_name}")

        shortcuts_to_add = [
            {
                "label": "Factura de Venta",
                "link_to": "Sales Invoice",
                "type": "DocType",
                "color": "Blue",
            },
            {
                "label": "Nota de Crédito",
                "link_to": "VE Sales Credit Note",
                "type": "DocType",
                "color": "Grey",
            },
        ]

        # 1. Actualizar tabla hija shortcuts
        current_shortcut_labels = {s.label for s in workspace.shortcuts}
        modified = False

        for shortcut in shortcuts_to_add:
            if not frappe.db.exists("DocType", shortcut["link_to"]):
                print(f"  -- Omitiendo (DocType no encontrado): {shortcut['link_to']}")
                continue

            if shortcut["label"] not in current_shortcut_labels:
                workspace.append("shortcuts", {
                    "label": shortcut["label"],
                    "link_to": shortcut["link_to"],
                    "type": shortcut["type"],
                    "color": shortcut.get("color", "Grey"),
                })
                modified = True
                print(f"  -> Shortcut (tabla) agregado: {shortcut['label']}")
            else:
                print(f"  -- Omitiendo (ya existe en tabla): {shortcut['label']}")

        # 2. Actualizar campo JSON content
        # En content, los shortcuts son bloques {"type": "shortcut", "data": {"shortcut_name": label, "col": 3}}
        # y deben estar DESPUÉS del bloque type=header de Quick Access
        content = json.loads(workspace.content) if workspace.content else []

        existing_shortcut_names = {
            block["data"]["shortcut_name"]
            for block in content
            if block.get("type") == "shortcut"
        }

        # Encontrar el índice del último shortcut existente para insertar después
        last_shortcut_idx = -1
        for i, block in enumerate(content):
            if block.get("type") == "shortcut":
                last_shortcut_idx = i

        shortcuts_added_to_content = []
        for shortcut in shortcuts_to_add:
            if not frappe.db.exists("DocType", shortcut["link_to"]):
                continue

            if shortcut["label"] not in existing_shortcut_names:
                import random
                import string
                rand_id = "".join(random.choices(string.ascii_letters + string.digits, k=10))
                shortcuts_added_to_content.append({
                    "id": rand_id,
                    "type": "shortcut",
                    "data": {
                        "shortcut_name": shortcut["label"],
                        "col": 3,
                    }
                })
                print(f"  -> Shortcut (content) agregado: {shortcut['label']}")
                modified = True
            else:
                print(f"  -- Omitiendo (ya existe en content): {shortcut['label']}")

        if shortcuts_added_to_content:
            insert_at = last_shortcut_idx + 1 if last_shortcut_idx >= 0 else len(content)
            for i, block in enumerate(shortcuts_added_to_content):
                content.insert(insert_at + i, block)

        if modified:
            workspace.content = json.dumps(content)
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Shortcuts agregados al Workspace '{workspace_name}'.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya tenía todos los shortcuts.")

    except Exception as e:
        print(f"Failure: Error agregando shortcuts al Workspace de Ventas: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_shortcuts_to_selling_workspace')


def add_vouchers_to_accounts_workspace() -> None:
    """
    Agrega los DocTypes de comprobantes de retención al Workspace 'Accounting'.
    """
    print("Agregando sección Tributos al Workspace de Contabilidad...")

    try:
        workspace_name = get_compatible_workspace_name()
        if not workspace_name:
            return

        workspace = frappe.get_doc("Workspace", workspace_name)
        print(f"  -> Workspace encontrado: {workspace_name}")

        links_to_add = [
            {
                "label": _("Retención de IVA"),
                "link_to": "VAT Withholding Voucher",
                "type": "Link",
                "link_type": "DocType"
            },
            {
                "label": _("Retención de ISLR"),
                "link_to": "ISLR Withholding Voucher",
                "type": "Link",
                "link_type": "DocType"
            },
            {
                "label": _("Declaración de Municipales"),
                "link_to": "VE Municipality Tax Declaration",
                "type": "Link",
                "link_type": "DocType"
            },
            {
                "label": _("Declaración de CONATEL"),
                "link_to": "VE Conatel Tax Declaration",
                "type": "Link",
                "link_type": "DocType"
            },
        ]

        links_to_move = [l["link_to"] for l in links_to_add]
        
        initial_links_count = len(workspace.links)
        workspace.set("links", [l for l in workspace.links if l.link_to not in links_to_move])
        modified = len(workspace.links) != initial_links_count
        
        current_links = {l.link_to for l in workspace.links}

        card_break_label = _("Tributos")
        card_break_exists = any(l.label == card_break_label and l.type == 'Card Break' for l in workspace.links)

        if not card_break_exists:
            workspace.append("links", {
                "type": "Card Break",
                "label": card_break_label
            })
            modified = True
            print(f"  -> Agregado salto de tarjeta: {card_break_label}")

        for link in links_to_add:
            if link["link_to"] not in current_links:
                workspace.append("links", {
                    "label": link["label"],
                    "type": "Link",
                    "link_type": "DocType",
                    "link_to": link["link_to"],
                })
                modified = True
                print(f"  -> Agregado a tabla links: {link['label']}")

        content = json.loads(workspace.content) if workspace.content else []
        custom_card_name = "Tributos"
        card_found = False

        content = [block for block in content if block.get("data", {}).get("card_name") != "Comprobantes"]

        for block in content:
            if block.get("type") == "card" and block.get("data", {}).get("card_name") == custom_card_name:
                card_found = True
                block["data"]["links"] = [l for l in links_to_add if frappe.db.exists("DocType", l["link_to"])]
                modified = True
                break
        
        if not card_found:
            print(f"  -> Creando nueva tarjeta visual '{custom_card_name}'...")
            new_card = {
                "type": "card",
                "data": {
                    "card_name": custom_card_name,
                    "col": 4,
                    "links": [l for l in links_to_add if frappe.db.exists("DocType", l["link_to"])]
                }
            }
            content.append(new_card)
            modified = True
        
        if modified:
            workspace.content = json.dumps(content)
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Workspace '{workspace_name}' actualizado con sección '{custom_card_name}'.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya estaba actualizado.")

    except Exception as e:
        print(f"Failure: Error actualizando Comprobantes en Workspace: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_vouchers_to_accounts_workspace')


def merge_old_accounts_to_2026(company_name: str = "Galanet Solution C.A.") -> None:
    """
    Fase 1: Renombra 11011 (Caja Tesorería Bs) → 1101002 Caja Tesorería Bolívares
            usando update_account_number (no existe destino, es solo renombrar).
    Fase 2: Fusiona las 17 cuentas restantes con GL Entries hacia sus equivalentes
            del plan 2026 usando merge_account de ERPNext, que ejecuta
            frappe.rename_doc con merge=1 y actualiza TODAS las referencias.

    IMPORTANTE: Ejecutar después de replace_chart_of_accounts y con backup previo.
    """
    from erpnext.accounts.doctype.account.account import merge_account, update_account_number

    print("=" * 70)
    print("MIGRACIÓN CUENTAS ANTIGUAS → PLAN 2026")
    print("=" * 70)

    if not frappe.db.exists("Company", company_name):
        print(f"FATAL: No se encontró la compañía '{company_name}'")
        return

    # ── FASE 1: Renombrar la caja en Bs (no hay destino, solo renumerar) ──
    print("\n── FASE 1: Renombrar Caja Tesorería Bs ──", flush=True)
    old_caja_name: str | None = frappe.db.get_value(
        "Account",
        {"account_number": "11011", "company": company_name},
        "name"
    )
    if old_caja_name:
        try:
            new_name = update_account_number(
                old_caja_name,
                "Caja Tesorería Bolívares",
                "1101002"
            )
            frappe.db.commit()
            gl_caja: int = frappe.db.count("GL Entry", {"account": new_name or old_caja_name})
            print(f"  ✓ #11011 → #1101002 Caja Tesorería Bolívares ({gl_caja} GL)", flush=True)
        except Exception as e:
            print(f"  ✗ #11011 → #1101002: {e}", flush=True)
            frappe.db.rollback()
    else:
        print("  ⏭ #11011 ya no existe o fue renombrada previamente", flush=True)

    # ── FASE 2: Merge de las 17 cuentas restantes ──
    print("\n── FASE 2: Merge cuentas antiguas → nuevas ──", flush=True)

    merge_map: list[tuple[str, str]] = [
        ("110111", "1101001"),      # Caja Tesorería Dolares → Caja Tesoreria dolares
        ("11021", "1102005"),       # Bancamiga Cte 7654 → Bancamiga Bs. Cte 7654 DC-01
        ("110219", "1102006"),      # Bancamiga HQ Cte 2113 → Bancamiga Bs. Cte 2113 HQ
        ("110226", "1102037"),      # Bancaribe 1120 → Bancaribe Bs. 1120 DC-01
        ("11029", "1102022"),       # Bancamiga Cte 1701 → Bancamiga Bs Cte 1701 MIR-01
        ("11041", "1105001"),       # CxC clientes → Cuentas por Cobrar Clientes
        ("11072", "1110002"),       # Ret. ISLR Clientes → Retenciones ISLR Clientes
        ("11073", "1110003"),       # Ret. IVA Clientes → Retencion de IVA Clientes
        ("21021", "2104001"),       # Anticipo Clientes → Anticipo de Clientes
        ("21031", "2105001"),       # IVA Débito Fiscal → IVA Debito Fiscal
        ("210314", "2105005"),      # IGTF por Pagar → IGTF por Pagar
        ("21033", "2105003"),       # Ret. ISLR Proveedores → Retenciones de ISLR Proveedores
        ("41011", "4101001"),       # Ingresos Internet → Ingresos Servicios de Internet
        ("51018", "5101010"),       # Acceso Internet → Acceso a Internet Proveedor Nacional
        ("620114", "6203009"),      # Ret. Gubernamentales → Retenciones Gubernamentales
        ("71014", "7101005"),       # Ganancia en Cambio → Ganancia en Cambio
        ("81017", "8101011"),       # Pérdida en Cambio → Perdida en Cambio
    ]

    total: int = len(merge_map)
    ok_count: int = 0
    err_count: int = 0
    skip_count: int = 0

    for i, (old_num, new_num) in enumerate(merge_map, 1):
        pct: float = (i / total) * 100

        old_doc_name: str | None = frappe.db.get_value(
            "Account",
            {"account_number": old_num, "company": company_name},
            "name"
        )
        new_doc_name: str | None = frappe.db.get_value(
            "Account",
            {"account_number": new_num, "company": company_name},
            "name"
        )

        if not old_doc_name:
            print(f"  [{pct:5.1f}%] {i}/{total} ⏭ #{old_num} ya no existe", flush=True)
            skip_count += 1
            continue

        if not new_doc_name:
            print(f"  [{pct:5.1f}%] {i}/{total} ✗ #{new_num} destino no existe", flush=True)
            err_count += 1
            continue

        if old_doc_name == new_doc_name:
            print(f"  [{pct:5.1f}%] {i}/{total} ⏭ #{old_num} ya es #{new_num}", flush=True)
            skip_count += 1
            continue

        gl_count: int = frappe.db.count("GL Entry", {"account": old_doc_name})

        try:
            merge_account(old_doc_name, new_doc_name)
            frappe.db.commit()
            ok_count += 1
            print(f"  [{pct:5.1f}%] {i}/{total} ✓ #{old_num} → #{new_num} "
                  f"({gl_count} GL migrados)", flush=True)
        except Exception as e:
            err_count += 1
            print(f"  [{pct:5.1f}%] {i}/{total} ✗ #{old_num} → #{new_num}: {e}", flush=True)
            frappe.db.rollback()



    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"Fase 1 - Caja Bs renombrada:  {'✓' if old_caja_name else '⏭'}")
    print(f"Fase 2 - Cuentas fusionadas:  {ok_count}")
    print(f"Fase 2 - Omitidas:            {skip_count}")
    print(f"Fase 2 - Errores:             {err_count}")

    # Verificar cuentas antiguas restantes
    all_old_nums: list[str] = ["11011"] + [m[0] for m in merge_map]
    remaining: list[dict] = []
    for old_num in all_old_nums:
        old_data: dict | None = frappe.db.get_value(
            "Account",
            {"account_number": old_num, "company": company_name},
            ["name", "account_name"],
            as_dict=True
        )
        if old_data:
            gl: int = frappe.db.count("GL Entry", {"account": old_data["name"]})
            remaining.append({"num": old_num, "name": old_data["account_name"], "gl": gl})

    if remaining:
        print(f"\n⚠ {len(remaining)} cuentas antiguas aún existen:")
        for r in remaining:
            print(f"  #{r['num']:10s} {r['name']:45s} ({r['gl']} GL)")
    else:
        print("\n🎉 Todas las cuentas antiguas fueron migradas exitosamente")

    print("=" * 70)


def replace_chart_of_accounts(company_name: str = "Galanet Solution C.A.") -> None:
    """
    Reemplaza completamente el plan de cuentas usando plan_cuentas_2026.csv
    como fuente única de verdad.

    Fases:
    - Fase 1: Normalizar números existentes (quitar puntos)
    - Fase 2: Renombrar cuentas comunes (mismo número, diferente nombre)
    - Fase 3: Crear cuentas nuevas del plan 2026
    - Fase 4: Desactivar/eliminar cuentas obsoletas (verifica GL Entries)
    - Fase 5: Reconstruir árbol de cuentas

    IMPORTANTE: Ejecutar fuera de horario laboral y con backup previo.
    """
    from erpnext.accounts.doctype.account.account import update_account_number

    print("=" * 70)
    print("REEMPLAZO PLAN DE CUENTAS 2026")
    print("=" * 70)

    company_abbr: str = frappe.get_cached_value("Company", company_name, "abbr")
    if not company_abbr:
        print(f"FATAL: No se encontró la compañía '{company_name}'")
        return

    print(f"Compañía: {company_name} ({company_abbr})")

    # --- Cargar CSV definitivo ---
    base_dir: str = os.path.dirname(__file__)
    csv_path: str = os.path.join(
        base_dir, 'resources', 'chart_of_accounts', 'plan_cuentas_2026.csv'
    )

    target_map: dict[str, dict] = _read_plan_2026_csv(csv_path)
    if not target_map:
        print("FATAL: No se pudo leer el CSV del plan 2026")
        return

    target_nums: set[str] = set(target_map.keys())

    # --- Cargar cuentas actuales del sistema ---
    current_accounts: list[dict] = frappe.db.get_all(
        "Account",
        filters={"company": company_name},
        fields=["name", "account_number", "account_name",
                "account_type", "is_group", "parent_account"]
    )
    current_map: dict[str, dict] = {}
    for acc in current_accounts:
        num_norm: str = (acc.get("account_number") or "").replace(".", "")
        if num_norm:
            current_map[num_norm] = acc

    current_nums: set[str] = set(current_map.keys())

    common_nums: set[str] = target_nums & current_nums
    to_create: set[str] = target_nums - current_nums
    to_remove: set[str] = current_nums - target_nums

    print(f"\nPlan 2026 (objetivo): {len(target_map)} cuentas")
    print(f"Sistema actual:       {len(current_map)} cuentas")
    print(f"En común:             {len(common_nums)}")
    print(f"Nuevas (a crear):     {len(to_create)}")
    print(f"Obsoletas (a quitar): {len(to_remove)}")

    # ═══════════════════════════════════════════════════════
    # FASE 1: Normalizar números (quitar puntos)
    # ═══════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("FASE 1: Normalizar números de cuenta (quitar puntos)")
    print(f"{'─' * 50}")

    existing_with_dots: list[dict] = frappe.db.get_all(
        "Account",
        filters={"company": company_name, "account_number": ["like", "%.%"]},
        fields=["name", "account_number", "account_name"]
    )
    total_dots: int = len(existing_with_dots)
    print(f"Cuentas con puntos: {total_dots}")

    norm_ok: int = 0
    norm_err: int = 0

    for i, acc_doc in enumerate(existing_with_dots, 1):
        old_number: str = acc_doc["account_number"]
        new_number: str = old_number.replace(".", "")
        pct: float = (i / total_dots) * 100
        try:
            update_account_number(
                acc_doc["name"], acc_doc["account_name"], new_number
            )
            frappe.db.commit()
            norm_ok += 1
            print(f"  [{pct:5.1f}%] {i}/{total_dots} ✓ #{old_number} → #{new_number}", flush=True)
        except Exception as e:
            frappe.db.rollback()
            # Retry: limpiar caché del doc y reintentar
            try:
                frappe.clear_document_cache("Account", acc_doc["name"])
                update_account_number(
                    acc_doc["name"], acc_doc["account_name"], new_number
                )
                frappe.db.commit()
                norm_ok += 1
                print(f"  [{pct:5.1f}%] {i}/{total_dots} ✓ #{old_number} → #{new_number} (retry)", flush=True)
            except Exception as e2:
                norm_err += 1
                print(f"  [{pct:5.1f}%] {i}/{total_dots} ✗ #{old_number}: {e2}", flush=True)
                frappe.db.rollback()

    print(f"\nNormalizados: {norm_ok}, Errores: {norm_err}")

    # ═══════════════════════════════════════════════════════
    # FASE 2: Renombrar cuentas comunes
    # ═══════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("FASE 2: Renombrar cuentas comunes")
    print(f"{'─' * 50}")

    ren_ok: int = 0
    ren_skip: int = 0
    ren_err: int = 0
    sorted_common: list[str] = sorted(common_nums, key=lambda x: (len(x), x))
    total_common: int = len(sorted_common)

    for i, num in enumerate(sorted_common, 1):
        target_acc: dict = target_map[num]
        new_name: str = target_acc["account_name"]
        new_type: str = target_acc.get("account_type", "")

        current: dict | None = frappe.db.get_value(
            "Account",
            {"account_number": num, "company": company_name},
            ["name", "account_name", "account_type"],
            as_dict=True
        )
        if not current:
            continue

        needs_rename: bool = current["account_name"] != new_name
        needs_type: bool = bool(new_type) and current.get("account_type") != new_type

        if not needs_rename and not needs_type:
            ren_skip += 1
            continue

        try:
            if needs_rename:
                update_account_number(current["name"], new_name, num)
                frappe.db.commit()
                print(f"  ✓ #{num}: '{current['account_name']}' → '{new_name}'")

            if needs_type:
                doc_name: str = frappe.db.get_value(
                    "Account",
                    {"account_number": num, "company": company_name},
                    "name"
                )
                if doc_name:
                    frappe.db.set_value("Account", doc_name, "account_type", new_type)
                    frappe.db.commit()
                    print(f"  ✓ #{num}: account_type → '{new_type}'")

            ren_ok += 1
        except Exception as e:
            ren_err += 1
            print(f"  ✗ Error renombrando #{num}: {e}")
            frappe.db.rollback()

    print(f"  [100%] {total_common}/{total_common} revisadas", flush=True)
    print(f"Renombrados: {ren_ok}, Sin cambios: {ren_skip}, Errores: {ren_err}")

    # ═══════════════════════════════════════════════════════
    # FASE 3: Crear cuentas nuevas
    # ═══════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("FASE 3: Crear cuentas nuevas del plan 2026")
    print(f"{'─' * 50}")

    sorted_to_create: list[str] = sorted(
        to_create, key=lambda x: (len(x), x)
    )
    print(f"Cuentas nuevas a procesar: {len(sorted_to_create)}")

    new_ok: int = 0
    new_err: int = 0
    total_new: int = len(sorted_to_create)

    for i, num in enumerate(sorted_to_create, 1):
        target_acc = target_map[num]
        account_name: str = target_acc["account_name"]
        is_group: int = int(target_acc.get("is_group", "0"))
        root_type: str = target_acc.get("root_type", "")
        account_type: str = target_acc.get("account_type", "")
        parent_number: str = target_acc.get("parent_number", "")

        parent_account: str | None = None
        if parent_number:
            parent_account = frappe.db.get_value(
                "Account",
                {"account_number": parent_number, "company": company_name},
                "name"
            )
            if not parent_account and parent_number in target_map:
                parent_name: str = target_map[parent_number]["account_name"]
                parent_account = frappe.db.get_value(
                    "Account",
                    {"account_name": parent_name, "company": company_name,
                     "is_group": 1},
                    "name"
                )

        pct = (i / total_new) * 100

        if frappe.db.get_value(
            "Account",
            {"account_number": num, "company": company_name},
            "name"
        ):
            print(f"  [{pct:5.1f}%] {i}/{total_new} ⏭ #{num} ya existe", flush=True)
            continue

        try:
            new_acc = frappe.new_doc("Account")
            new_acc.account_name = account_name
            new_acc.account_number = num
            new_acc.company = company_name
            new_acc.is_group = is_group
            new_acc.parent_account = parent_account

            if root_type:
                new_acc.root_type = root_type

            report_type_map: dict[str, str] = {
                "Asset": "Balance Sheet",
                "Liability": "Balance Sheet",
                "Equity": "Balance Sheet",
                "Income": "Profit and Loss",
                "Expense": "Profit and Loss",
            }
            if root_type in report_type_map:
                new_acc.report_type = report_type_map[root_type]

            if account_type:
                new_acc.account_type = account_type

            new_acc.flags.ignore_permissions = True
            new_acc.flags.ignore_mandatory = True
            new_acc.insert(ignore_permissions=True)
            frappe.db.commit()

            new_ok += 1
            print(f"  [{pct:5.1f}%] {i}/{total_new} ✓ #{num} - {account_name}", flush=True)

        except Exception as e:
            new_err += 1
            print(f"  [{pct:5.1f}%] {i}/{total_new} ✗ #{num} - {account_name}: {e}", flush=True)
            frappe.db.rollback()

    print(f"\nCuentas creadas: {new_ok}, Errores: {new_err}")

    # ═══════════════════════════════════════════════════════
    # FASE 4: Desactivar/eliminar cuentas obsoletas
    # ═══════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("FASE 4: Desactivar/eliminar cuentas obsoletas")
    print(f"{'─' * 50}")

    del_ok: int = 0
    dis_ok: int = 0
    del_err: int = 0
    kept_accounts: list[dict] = []

    # Procesar de más profundo a menos (hojas primero, luego grupos)
    sorted_to_remove: list[str] = sorted(
        to_remove, key=lambda x: (-len(x), x)
    )

    total_remove: int = len(sorted_to_remove)

    for i, num in enumerate(sorted_to_remove, 1):
        pct = (i / total_remove) * 100
        acc_data: dict | None = frappe.db.get_value(
            "Account",
            {"account_number": num, "company": company_name},
            ["name", "account_name", "is_group"],
            as_dict=True
        )
        if not acc_data:
            print(f"  [{pct:5.1f}%] {i}/{total_remove} ⏭ #{num} no encontrada", flush=True)
            continue

        doc_name: str = acc_data["name"]
        acc_label: str = acc_data["account_name"]

        has_gl: int = frappe.db.count("GL Entry", {"account": doc_name})

        if has_gl > 0:
            kept_accounts.append({
                "num": num,
                "name": acc_label,
                "gl_entries": has_gl
            })
            print(f"  [{pct:5.1f}%] {i}/{total_remove} ⚠ #{num} CONSERVADA activa ({has_gl} GL)", flush=True)
        else:
            try:
                has_children: int = frappe.db.count(
                    "Account", {"parent_account": doc_name}
                )
                if has_children > 0:
                    frappe.db.set_value("Account", doc_name, "disabled", 1)
                    frappe.db.commit()
                    dis_ok += 1
                    print(f"  [{pct:5.1f}%] {i}/{total_remove} 🔒 #{num} desactivada (hijos)", flush=True)
                else:
                    frappe.delete_doc(
                        "Account", doc_name,
                        ignore_permissions=True, force=True
                    )
                    frappe.db.commit()
                    del_ok += 1
                    print(f"  [{pct:5.1f}%] {i}/{total_remove} 🗑 #{num} eliminada", flush=True)
            except Exception:
                try:
                    frappe.db.rollback()
                    frappe.db.set_value("Account", doc_name, "disabled", 1)
                    frappe.db.commit()
                    dis_ok += 1
                    print(f"  [{pct:5.1f}%] {i}/{total_remove} 🔒 #{num} desactivada (fallback)", flush=True)
                except Exception as e2:
                    del_err += 1
                    print(f"  [{pct:5.1f}%] {i}/{total_remove} ✗ #{num}: {e2}", flush=True)
                    frappe.db.rollback()

    print(f"\nEliminadas: {del_ok}")
    print(f"Desactivadas: {dis_ok}")
    print(f"Errores: {del_err}")

    if kept_accounts:
        print(f"\n{'─' * 50}")
        print("CUENTAS CONSERVADAS (tienen GL Entries):")
        print(f"{'─' * 50}")
        for acc in sorted(kept_accounts, key=lambda x: x["num"]):
            print(f"  #{acc['num']:12s} {acc['name']:45s} "
                  f"({acc['gl_entries']} asientos)")

    # ═══════════════════════════════════════════════════════
    # FASE 5: Reconstruir árbol
    # ═══════════════════════════════════════════════════════
    print(f"\n{'─' * 50}")
    print("FASE 5: Reconstruir árbol de cuentas")
    print(f"{'─' * 50}")

    try:
        from frappe.utils.nestedset import rebuild_tree
        rebuild_tree("Account", "parent_account")
        frappe.db.commit()
        print("  ✅ Árbol reconstruido exitosamente")
    except Exception as e:
        print(f"  ❌ Error reconstruyendo árbol: {e}")

    # ═══════════════════════════════════════════════════════
    # RESUMEN FINAL
    # ═══════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("RESUMEN FINAL")
    print("=" * 70)
    print(f"Fase 1 - Números normalizados:     {norm_ok}")
    print(f"Fase 2 - Cuentas renombradas:       {ren_ok}")
    print(f"Fase 3 - Cuentas creadas:           {new_ok}")
    print(f"Fase 4 - Cuentas eliminadas:        {del_ok}")
    print(f"Fase 4 - Cuentas desactivadas:      {dis_ok}")
    print(f"Fase 4 - Con GL Entries (revisar):  {len(kept_accounts)}")
    print(f"Total errores:                      "
          f"{norm_err + ren_err + new_err + del_err}")

    print("\n" + "=" * 70)
    print("MIGRACIÓN COMPLETADA")
    print("=" * 70)

    # Ejecutar merge de cuentas antiguas con GL Entries
    merge_old_accounts_to_2026(company_name)

    _verify_replacement(company_name)


def _read_plan_2026_csv(file_path: str) -> dict[str, dict]:
    """
    Lee el CSV definitivo plan_cuentas_2026.csv y retorna un mapa
    {account_number: {account_name, parent_number, is_group, root_type, account_type}}.
    """
    result: dict[str, dict] = {}

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            num: str = (row.get("account_number") or "").strip()
            name: str = (row.get("account_name") or "").strip()

            if not num or not name:
                continue

            result[num] = {
                "account_number": num,
                "account_name": name,
                "parent_number": (row.get("parent_number") or "").strip(),
                "is_group": (row.get("is_group") or "0").strip(),
                "root_type": (row.get("root_type") or "").strip(),
                "account_type": (row.get("account_type") or "").strip(),
            }

    return result


def _build_account_doc_name(
    account_number: str, account_name: str, company_abbr: str
) -> str:
    """
    Construye el name del documento Account tal como lo genera ERPNext.
    Formato: '{account_number} - {account_name} - {company_abbr}'
    """
    if account_number:
        return f"{account_number} - {account_name} - {company_abbr}"
    return f"{account_name} - {company_abbr}"


def _verify_replacement(company_name: str = "Galanet Solution C.A.") -> None:
    """
    Ejecuta verificaciones post-reemplazo del plan de cuentas.
    Muestra resultados con indicadores ✅/❌ en consola.
    """
    print("\n" + "=" * 70)
    print("VERIFICACIÓN POST-MIGRACIÓN")
    print("=" * 70)

    passed: int = 0
    failed: int = 0

    # V1: Sin puntos en números de cuenta activas
    dots_count: int = frappe.db.sql(
        """SELECT COUNT(*) FROM tabAccount
           WHERE company = %s AND account_number LIKE '%%.%%'
           AND IFNULL(disabled, 0) = 0""",
        company_name
    )[0][0]
    if dots_count == 0:
        print("  ✅ V1: Sin puntos en números de cuenta (activas)")
        passed += 1
    else:
        print(f"  ❌ V1: {dots_count} cuentas activas con puntos")
        failed += 1

    # V2: Total de cuentas activas ≈ plan 2026 + 1 (1101002 Caja Bs)
    base_dir_v: str = os.path.dirname(__file__)
    csv_path_v: str = os.path.join(
        base_dir_v, 'resources', 'chart_of_accounts', 'plan_cuentas_2026.csv'
    )
    csv_count: int = len(_read_plan_2026_csv(csv_path_v))
    expected_min: int = csv_count
    expected_max: int = csv_count + 5
    active_total: int = frappe.db.sql(
        """SELECT COUNT(*) FROM tabAccount
           WHERE company = %s AND IFNULL(disabled, 0) = 0""",
        company_name
    )[0][0]
    if expected_min <= active_total <= expected_max:
        print(f"  ✅ V2: Total activas en rango ({active_total}, "
              f"esperado {expected_min}-{expected_max})")
        passed += 1
    else:
        print(f"  ❌ V2: Total activas fuera de rango: {active_total} "
              f"(esperado: {expected_min}-{expected_max})")
        failed += 1

    # V3: Cuentas renombradas correctamente
    expected_names: dict[str, str] = {
        "21": "CORRIENTE",
        "31": "CAPITAL",
        "71": "OTROS INGRESOS",
        "81": "OTROS EGRESOS",
        "1102": "BANCOS NACIONALES",
        "1107": "ADELANTOS A PROVEEDORES",
        "1202": "ACTIVOS TANGIBLES",
        "2101": "EFECTOS A PAGAR",
        "2102": "PRESTAMOS BANCARIO CORTO PLAZO",
        "2103": "CUENTAS POR PAGAR",
        "6101": "GASTOS DE PERSONAL",
        "6201": "GASTOS OPERACIONALES",
    }
    name_mismatches: list[str] = []
    for acc_num, expected_name in expected_names.items():
        actual_name: str | None = frappe.db.get_value(
            "Account",
            {"account_number": acc_num, "company": company_name},
            "account_name"
        )
        if actual_name != expected_name:
            name_mismatches.append(
                f"#{acc_num}: '{actual_name}' (esperado: '{expected_name}')"
            )

    if not name_mismatches:
        print("  ✅ V3: 12 cuentas renombradas correctamente")
        passed += 1
    else:
        print(f"  ❌ V3: {len(name_mismatches)} nombres no coinciden:")
        for m in name_mismatches:
            print(f"       - {m}")
        failed += 1

    # V4: Sin GL Entries huérfanos
    orphans: int = frappe.db.sql(
        """SELECT COUNT(DISTINCT gle.account)
           FROM `tabGL Entry` gle
           LEFT JOIN tabAccount a ON a.name = gle.account
           WHERE a.name IS NULL AND gle.company = %s""",
        company_name
    )[0][0]
    if orphans == 0:
        print("  ✅ V4: Sin GL Entries huérfanos (integridad referencial OK)")
        passed += 1
    else:
        print(f"  ❌ V4: {orphans} cuentas en GL Entry sin Account")
        failed += 1

    # V5: Sin cuentas huérfanas activas (sin padre y no root)
    orphan_accounts: int = frappe.db.sql(
        """SELECT COUNT(*) FROM tabAccount
           WHERE company = %s
             AND IFNULL(disabled, 0) = 0
             AND (parent_account IS NULL OR parent_account = '')
             AND LENGTH(account_number) > 1""",
        company_name
    )[0][0]
    if orphan_accounts == 0:
        print("  ✅ V5: Jerarquía correcta (sin cuentas huérfanas activas)")
        passed += 1
    else:
        print(f"  ❌ V5: {orphan_accounts} cuentas activas sin padre")
        failed += 1

    # Resumen
    print("\n" + "-" * 40)
    total_checks: int = passed + failed
    if failed == 0:
        print(f"  🎉 {passed}/{total_checks} verificaciones aprobadas")
    else:
        print(f"  ⚠️  {passed}/{total_checks} aprobadas, {failed} fallidas")
    print("=" * 70)
