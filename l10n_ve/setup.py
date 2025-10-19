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
                'account_number': '1.2.1.1.05',
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
                'account_number': '2.1.2.2.06',
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
        ]

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

                print(f"  Cuenta '{account_name}' enlazada satisfactoriamente en el campo '{company_field}'.")

        frappe.db.commit()

    except Exception as e:
        print(f" !! ERROR configurando las cuentas contables: {e}")
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
