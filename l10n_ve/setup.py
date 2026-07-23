import os
import csv
import json
import frappe
from frappe import _
from frappe.utils import getdate

def set_default_site_config() -> None:
    """Defaults de site_config que TODO site con l10n_ve debe tener.

    - bcv_endpoint: API pública de la tasa BCV (tasks.py la lee de site_config; sin
      ella cae a web scraping). Es igual para todos los sites -> default de la app.
      NO se pisa si el site ya la definió.

    Las credenciales por cliente (digital_billing_settings/HKA, pasarelas) NUNCA van
    aquí: son secretos por servidor y se aprovisionan al crear el site.
    """
    from frappe.installer import update_site_config

    if not frappe.get_site_config().get("bcv_endpoint"):
        update_site_config(
            "bcv_endpoint", "https://api.dolarvzla.com/public/exchange-rate"
        )


def set_default_branding() -> None:
    """Logo del login/Desk de fábrica, SOLO si el site no tiene uno propio.

    get_app_logo() de frappe ignora el hook app_logo_url cuando MÁS de dos apps
    lo definen (toma logos[0] salvo len==2): con frappe+erpnext+l10n_ve el login
    mostraba el logo de frappe. Fijar Navbar Settings.app_logo cubre login y Desk.
    Los sites brandeados conservan lo suyo: Website Settings.app_logo SIEMPRE gana
    en la resolución de frappe, y aquí además no se escribe nada si ya hay valor
    en Website Settings o en Navbar Settings.
    """
    if frappe.get_website_settings("app_logo") or frappe.db.get_single_value(
        "Navbar Settings", "app_logo"
    ):
        return
    frappe.db.set_single_value(
        "Navbar Settings", "app_logo", "/assets/l10n_ve/images/domina-wordmark.png"
    )


def set_data() -> None:
    print("Iniciando la configuración de datos para l10n_ve...")

    try:

        set_default_site_config()
        set_default_branding()
        create_currency_exchange()
        create_tax_unit()
        create_islr_tabulator()
        set_chart_of_accounts()
        create_government_withholding_custom_fields()
        link_government_withholding_account()
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
        create_stamp_tax_rates()
        create_conatel_tax_types()
        set_stock_settings()
        create_bank_transaction_mappings()
        disable_other_currencies()
        remove_module_onboarding()
        set_profiles()
        set_roles()
        setup_workspaces()
        create_retention_reminder_email_template()

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
                'account_name': 'Retenciones Gubernamentales',
                'account_number': '6.2.01.14',
                'company_field': 'government_withholding_account',
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


def create_government_withholding_custom_fields() -> None:
    """Custom fields de las retenciones gubernamentales (timbre, ISAE, Responsabilidad Social).

    - Company.government_withholding_account: cuenta ÚNICA de gasto (6.2.01.14 Retenciones
      Gubernamentales) donde se registran TODAS estas retenciones (directiva contable 21-jul:
      todas son gasto, no anticipo). La enlaza set_chart_of_accounts vía account_map.
    - Customer.government_withholdings: tabla opt-in que declara QUÉ retenciones practica el ente
      y su jurisdicción (estado para timbre, municipio para ISAE).
    - Payment Entry.government_withholdings: tabla de captura en el cobro (monto sugerido calculado
      read-only + monto real del comprobante + n° + adjunto). El motor la usa para poblar deductions.
    """
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    print("Creando custom fields de retenciones gubernamentales...")

    custom_fields = {
        "Company": [
            {
                "fieldname": "government_withholding_account",
                "label": "Cuenta de Retenciones Gubernamentales",
                "fieldtype": "Link",
                "options": "Account",
                "insert_after": "sales_igtf_account",
                "description": "Cuenta de gasto única (6.2.01.14) para timbre, ISAE y Responsabilidad Social.",
            },
        ],
        "Customer": [
            {
                "fieldname": "government_withholding_section",
                "label": "Retenciones Gubernamentales",
                "fieldtype": "Section Break",
                "insert_after": "nature_of_the_taxpayer",
                "depends_on": "eval:doc.nature_of_the_taxpayer=='Government'",
                "collapsible": 1,
            },
            {
                "fieldname": "government_withholdings",
                "label": "Retenciones que practica el ente",
                "fieldtype": "Table",
                "options": "VE Government Withholding",
                "insert_after": "government_withholding_section",
                "description": "Qué retenciones descuenta este ente al pagar (y de qué estado/municipio).",
            },
        ],
        "Payment Entry": [
            {
                "fieldname": "government_withholding_section",
                "label": "Retenciones Gubernamentales",
                "fieldtype": "Section Break",
                "insert_after": "received_amount",
                "collapsible": 1,
            },
            {
                "fieldname": "government_withholdings",
                "label": "Retenciones Gubernamentales",
                "fieldtype": "Table",
                "options": "VE Payment Government Withholding",
                "insert_after": "government_withholding_section",
                "description": "Retenciones capturadas en este cobro. El monto sugerido es de solo lectura; ajuste el monto real según el comprobante del ente.",
            },
        ],
    }

    create_custom_fields(custom_fields, ignore_validate=True)
    frappe.db.commit()
    print("Success: Custom fields de retenciones gubernamentales creados.")


def link_government_withholding_account(company_name: str = None) -> None:
    """Enlaza Company.government_withholding_account por NOMBRE de cuenta ('Retenciones
    Gubernamentales'), en cada company donde esté vacío. Robusto a la numeración: funciona con
    6.2.01.14 (plantilla genérica/Galanet), 6203009 (Galanet/Black renumerado) o cualquier número.
    Solo setea si el campo está vacío (respeta la cuenta que ya haya elegido contabilidad). Idempotente.
    """
    print("Enlazando cuenta de Retenciones Gubernamentales por nombre...")
    try:
        filters = {"name": company_name} if company_name else {}
        for company in frappe.get_all("Company", filters=filters, pluck="name"):
            if frappe.db.get_value("Company", company, "government_withholding_account"):
                continue  # ya configurada; no la pisamos
            account = frappe.db.get_value(
                "Account",
                {"company": company, "account_name": "Retenciones Gubernamentales", "is_group": 0},
                "name",
            )
            if account:
                frappe.db.set_value("Company", company, "government_withholding_account", account)
                print(f"  -> {company}: government_withholding_account = {account}")
            else:
                print(f"  -- {company}: no existe la cuenta 'Retenciones Gubernamentales'; se omite.")
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Error en link_government_withholding_account")


def create_stamp_tax_rates() -> None:
    """Siembra la tabla de tarifas de timbre fiscal por estado en Venezuela Account Settings.

    Patrón idéntico a create_municipality_taxes: lee resources/ve_stamp_tax_rates.csv y puebla el
    child stamp_tax_rates del Single. Idempotente: no duplica un estado ya cargado (respeta ediciones
    posteriores de contabilidad). Valores con base legal verificada 21-jul (ver plan).
    """
    print("Sembrando tarifas de timbre fiscal por estado...")

    try:
        csv_file_path = frappe.get_app_path('l10n_ve', 'resources', 've_stamp_tax_rates.csv')
        if not os.path.exists(csv_file_path):
            print(f"  !! ADVERTENCIA: no existe {csv_file_path}. Se omite el seed de timbre.")
            return

        settings = frappe.get_single('Venezuela Account Settings')
        existing_states = {row.state for row in settings.stamp_tax_rates}

        # Default de la tarifa de Responsabilidad Social (fija) si no está configurada.
        dirty = False
        if not frappe.utils.flt(settings.responsibility_social_rate):
            settings.responsibility_social_rate = 3
            dirty = True

        added = 0
        with open(csv_file_path, mode='r', encoding='utf-8') as f:
            for record in csv.DictReader(f):
                state_label = (record.get('state') or '').strip()
                if not state_label:
                    continue
                # VE State se nombra por el campo `state`; resolvemos el name real por el label.
                state_name = frappe.db.get_value('VE State', {'state': state_label}, 'name')
                if not state_name:
                    print(f"  !! Estado '{state_label}' no existe (VE State); se omite su tarifa de timbre.")
                    continue
                if state_name in existing_states:
                    continue
                settings.append('stamp_tax_rates', {
                    'state': state_name,
                    'rate': frappe.utils.flt(record.get('rate')),
                    'threshold': frappe.utils.flt(record.get('threshold')),
                    'threshold_unit': (record.get('threshold_unit') or 'Sin umbral').strip(),
                    'enabled': 1,
                })
                existing_states.add(state_name)
                added += 1

        if added or dirty:
            settings.save(ignore_permissions=True)
            frappe.db.commit()
        print(f"Success: {added} tarifa(s) de timbre sembrada(s); Resp. Social {settings.responsibility_social_rate}%.")

    except Exception as e:
        print(f"  !! ERROR sembrando tarifas de timbre: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_stamp_tax_rates')


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
        imagen_banco = banco_data.get('image')

        if not codigo_banco or not nombre_banco:
            frappe.log_message("Entrada de banco inválida, se omite", f"Datos: {banco_data}")
            errores.append(f"Entrada de banco inválida: {banco_data}")
            continue

        try:
            bank_name = frappe.db.get_value("Bank", {"swift_number": codigo_banco}, "name") or frappe.db.get_value("Bank", {"bank_name": nombre_banco}, "name")
            bank_doc = frappe.get_doc("Bank", bank_name) if bank_name else None

            if bank_doc:
                bancos_existentes += 1
                needs_save = False
                if not bank_doc.swift_number:
                    bank_doc.swift_number = codigo_banco
                    needs_save = True
                if imagen_banco and not getattr(bank_doc, "image", None):
                    if frappe.db.has_column("Bank", "image"):
                        bank_doc.image = imagen_banco
                        needs_save = True
                if needs_save:
                    bank_doc.save(ignore_permissions=True)
                print(f"  -- Actualizado/Verificado: '{nombre_banco}' ({codigo_banco})")
            else:
                bank_dict = {
                    "doctype": "Bank",
                    "bank_name": nombre_banco,
                    "swift_number": codigo_banco,
                    "country": country_name
                }
                if imagen_banco and frappe.db.has_column("Bank", "image"):
                    bank_dict["image"] = imagen_banco

                nuevo_banco = frappe.get_doc(bank_dict)
                nuevo_banco.insert(ignore_permissions=True)
                bancos_creados += 1
                print(f"  -> Creado Banco: '{nombre_banco}' ({codigo_banco})")

        except Exception as e:
            error_msg = f"Error al crear o actualizar el banco '{nombre_banco}' ({codigo_banco}): {e}"
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
                "label": _("Retención de Cliente IVA/ISLR"),
                "link_to": "Customer Retention",
                "link_type": "Report",
                "is_query_report": 1
            },
            {
                "type": "Link",
                "label": _("Reporte de IVA"),
                "link_to": "VAT report",
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
    add_links_to_selling_workspace()
    add_links_to_buying_workspace()
    remove_number_cards_from_accounting_workspace()
    restrict_admin_workspaces()

def restrict_admin_workspaces() -> None:
    """
    Agrega el rol 'System Manager' a los workspaces de administración para ocultarlos
    del resto de usuarios. Esto corre en after_migrate para evitar clobbering.
    """
    print("Restringiendo Workspaces administrativos...")
    workspaces = ["Users", "Build", "ERPNext Settings"]
    
    for ws_name in workspaces:
        if not frappe.db.exists("Workspace", ws_name):
            continue
            
        try:
            ws = frappe.get_doc("Workspace", ws_name)
            
            # Buscar si ya tiene System Manager en roles
            has_system_manager = any(r.role == "System Manager" for r in ws.roles)
            
            # Si no tiene System Manager pero tiene otros roles (o no tiene ninguno), aseguramos System Manager
            if not has_system_manager:
                # Limpiar cualquier rol previo que pudiera haber (para que solo sea System Manager)
                # si se requiere, o simplemente añadirlo si es vacío
                ws.set("roles", [])
                ws.append("roles", {"role": "System Manager"})
                ws.save(ignore_permissions=True)
                print(f"  -> Workspace '{ws_name}' restringido a System Manager.")
            else:
                print(f"  -- Workspace '{ws_name}' ya estaba restringido.")
                
        except Exception as e:
            print(f"  !! Error restringiendo Workspace '{ws_name}': {e}")
            
def remove_number_cards_from_accounting_workspace() -> None:
    """
    Remueve la tarjeta de 'Tasa BCV del Día' del Workspace de Contabilidad
    y restaura el ancho de las 4 tarjetas originales a col: 3.
    """
    print("Removiendo tarjeta de Tasa BCV del Día del Workspace de Contabilidad...")
    try:
        workspace_name = get_compatible_workspace_name()
        if not workspace_name:
            return

        workspace = frappe.get_doc("Workspace", workspace_name)
        
        card_name = "Tasa BCV del Día"
        modified = False

        # 1. Remover del child table number_cards
        original_cards = [c for c in workspace.number_cards if c.number_card_name != card_name]
        if len(original_cards) != len(workspace.number_cards):
            workspace.set("number_cards", original_cards)
            modified = True
            print(f"  -> Removida tarjeta '{card_name}' de la tabla number_cards.")

        # 2. Remover del layout JSON content y restaurar col: 3 para las tarjetas de erpnext
        content = json.loads(workspace.content) if workspace.content else []
        new_content = []
        target_cards = {"Total Outgoing Bills", "Total Incoming Bills", "Total Incoming Payment", "Total Outgoing Payment"}
        
        for block in content:
            if block.get("type") == "number_card":
                name = block.get("data", {}).get("number_card_name")
                if name == card_name:
                    modified = True
                    continue # Omitir/borrar
                elif name in target_cards:
                    block["data"]["col"] = 3
                    modified = True
            new_content.append(block)

        if modified:
            workspace.content = json.dumps(new_content)
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Workspace '{workspace_name}' restaurado (tarjeta BCV removida).")

        # 3. Eliminar el documento de Number Card 'Tasa BCV del Día' de la base de datos si existe
        if frappe.db.exists("Number Card", card_name):
            frappe.delete_doc("Number Card", card_name, ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Documento Number Card '{card_name}' eliminado.")

    except Exception as e:
        print(f"Failure: Error limpiando el Workspace de Contabilidad: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en remove_number_cards_from_accounting_workspace')

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
            {
                "label": "Nota de Débito",
                "link_to": "VE Sales Debit Note",
                "type": "DocType",
                "color": "Orange",
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


def add_links_to_selling_workspace() -> None:
    """
    Agrega Nota de Crédito y Nota de Débito como links en la sección 'Ventas'
    del Workspace de Ventas, justo después de 'Sales Invoice'.

    Frappe renderiza los links del menú lateral desde la tabla hija `links`.
    Los links se insertan después de Sales Invoice para mantener el orden lógico:
      Factura de Venta → Nota de Crédito → Nota de Débito
    """
    print("Agregando NC/ND a la sección Ventas del Workspace...")
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

        links_to_add = [
            {
                "label": _("Nota de Crédito"),
                "link_to": "VE Sales Credit Note",
                "type": "Link",
                "link_type": "DocType",
            },
            {
                "label": _("Nota de Débito"),
                "link_to": "VE Sales Debit Note",
                "type": "Link",
                "link_type": "DocType",
            },
        ]

        current_links = {l.link_to for l in workspace.links}
        modified = False

        sales_invoice_idx = None
        for i, link in enumerate(workspace.links):
            if link.link_to == "Sales Invoice":
                sales_invoice_idx = i
                break

        insert_offset = 1
        for link_config in links_to_add:
            if not frappe.db.exists("DocType", link_config["link_to"]):
                print(f"  -- Omitiendo (DocType no encontrado): {link_config['link_to']}")
                continue

            if link_config["link_to"] in current_links:
                print(f"  -- Omitiendo (ya existe): {link_config['label']}")
                continue

            new_link = workspace.append("links", {})
            new_link.label = link_config["label"]
            new_link.type = link_config["type"]
            new_link.link_type = link_config["link_type"]
            new_link.link_to = link_config["link_to"]

            if sales_invoice_idx is not None:
                target_idx = sales_invoice_idx + insert_offset + 1
                links_list = workspace.links
                last_link = links_list.pop()
                links_list.insert(target_idx, last_link)
                insert_offset += 1

            modified = True
            print(f"  -> Link agregado: {link_config['label']}")

        if modified:
            for i, link in enumerate(workspace.links, start=1):
                link.idx = i
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Links NC/ND agregados al Workspace '{workspace_name}'.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya tenía los links.")

    except Exception as e:
        print(f"Failure: Error agregando links NC/ND al Workspace: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_links_to_selling_workspace')

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
                "label": _("Comprobantes de Retención de IVA"),
                "link_to": "VAT Withholding Voucher",
                "type": "Link",
                "link_type": "DocType"
            },
            {
                "label": _("Comprobantes de Retención de ISLR"),
                "link_to": "ISLR Withholding Voucher",
                "type": "Link",
                "link_type": "DocType"
            },
            {
                "label": _("Declaración de Impuestos Municipales"),
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


def add_links_to_buying_workspace() -> None:
    """Agrega VE Purchase Credit Note y VE Purchase Debit Note como links
    en la sección 'Compras' del Workspace de Compras, justo después de
    'Purchase Invoice'.

    Sigue el mismo patrón de add_links_to_selling_workspace.
    """
    print("Agregando NC/ND de Compras al Workspace de Compras...")
    try:
        workspace_name = None
        for candidate in ("Buying", "Compras"):
            if frappe.db.exists("Workspace", candidate):
                workspace_name = candidate
                break

        if not workspace_name:
            print("  !! No se encontró el Workspace 'Buying' / 'Compras'. Omitiendo.")
            return

        workspace = frappe.get_doc("Workspace", workspace_name)

        links_to_add: list[dict] = [
            {
                "label": _("Nota de Crédito"),
                "link_to": "VE Purchase Credit Note",
                "type": "Link",
                "link_type": "DocType",
            },
            {
                "label": _("Nota de Débito"),
                "link_to": "VE Purchase Debit Note",
                "type": "Link",
                "link_type": "DocType",
            },
        ]

        current_links: set[str] = {link.link_to for link in workspace.links}
        modified: bool = False

        purchase_invoice_idx: int | None = None
        for i, link in enumerate(workspace.links):
            if link.link_to == "Purchase Invoice":
                purchase_invoice_idx = i
                break

        insert_offset: int = 1
        for link_config in links_to_add:
            if not frappe.db.exists("DocType", link_config["link_to"]):
                print(f"  -- Omitiendo (DocType no encontrado): {link_config['link_to']}")
                continue

            if link_config["link_to"] in current_links:
                print(f"  -- Omitiendo (ya existe): {link_config['label']}")
                continue

            new_link = workspace.append("links", {})
            new_link.label = link_config["label"]
            new_link.type = link_config["type"]
            new_link.link_type = link_config["link_type"]
            new_link.link_to = link_config["link_to"]

            if purchase_invoice_idx is not None:
                target_idx: int = purchase_invoice_idx + insert_offset + 1
                links_list = workspace.links
                last_link = links_list.pop()
                links_list.insert(target_idx, last_link)
                insert_offset += 1

            modified = True
            print(f"  -> Link agregado: {link_config['label']}")

        if modified:
            for i, link in enumerate(workspace.links, start=1):
                link.idx = i
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            print(f"Success: Links NC/ND agregados al Workspace '{workspace_name}'.")
        else:
            print(f"  -- Workspace '{workspace_name}' ya tenía los links.")

    except Exception as e:
        print(f"Failure: Error agregando links NC al Workspace de Compras: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en add_links_to_buying_workspace')


def create_retention_reminder_email_template() -> None:
    """Crea la plantilla predeterminada en Email Template."""
    print("Creando plantilla de correo predeterminada para recordatorio de retención...")
    try:
        # Crear la plantilla predeterminada en Email Template
        template_name = "Recordatorio de Retenciones Pendientes"
        
        html_content = """<div style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
    <div style="background-color: #1e3a8a; padding: 24px; text-align: center; color: #ffffff;">
        <h2 style="margin: 0; font-size: 20px; font-weight: 600; letter-spacing: 0.5px;">Recordatorio de Retenciones Pendientes</h2>
    </div>
    <div style="padding: 24px; color: #2d3748; line-height: 1.6;">
        <p style="margin-top: 0; font-size: 16px; font-weight: bold;">Estimado(a) {{ customer_name }},</p>
        <p style="font-size: 14px; color: #4a5568;">
            Le escribimos para recordarle que tenemos pendiente el registro de los comprobantes de retención correspondientes a las siguientes facturas de venta. Agradecemos su valioso apoyo gestionando el envío de estos soportes a la brevedad:
        </p>
        
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; border: 1px solid #e2e8f0;">
            <thead>
                <tr style="background-color: #f7fafc;">
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Factura</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Control</th>
                    <th style="padding: 12px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Fecha Emisión</th>
                    <th style="padding: 12px; text-align: center; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #718096; border-bottom: 2px solid #e2e8f0;">Retención Faltante</th>
                </tr>
            </thead>
            <tbody>
                {% for inv in invoices %}
                <tr>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #2d3748; font-weight: 500;">{{ inv.name }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #4a5568;">{{ inv.bill_control or "" }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; color: #4a5568;">{{ inv.formatted_date }}</td>
                    <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; font-size: 14px; text-align: center;">
                        {% if inv.missing_vat %}
                        <span style="background-color: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 4px; display: inline-block;">IVA</span>
                        {% endif %}
                        {% if inv.missing_islr %}
                        <span style="background-color: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">ISLR</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        
        <p style="font-size: 14px; color: #4a5568; margin-bottom: 24px;">
            Por favor, responda a este correo adjuntando los comprobantes fiscales correspondientes para que podamos procesarlos y conciliar su cuenta.
        </p>
        
        <div style="border-top: 1px solid #e2e8f0; padding-top: 16px; font-size: 12px; color: #718096; text-align: center;">
            <p style="margin: 0 0 8px 0; font-style: italic;">Este es un mensaje automático del sistema de facturación.</p>
            {% if company %}
            <div style="background-color: #f8fafc; border: 1px solid #edf2f7; border-radius: 6px; padding: 12px; margin-top: 12px; text-align: center; display: inline-block; min-width: 250px;">
                <strong style="color: #2d3748; font-size: 13px;">{{ company }}</strong>
            </div>
            {% endif %}
        </div>
    </div>
</div>"""

        if not frappe.db.exists("Email Template", template_name):
            doc = frappe.new_doc("Email Template")
            doc.name = template_name
            doc.subject = "Recordatorio: Comprobantes de Retención Pendientes"
            doc.use_html = 1
            doc.response_html = html_content
            doc.insert(ignore_permissions=True)
            print("Success: Plantilla predeterminada 'Recordatorio de Retenciones Pendientes' creada.")
        else:
            # Si ya existe pero el HTML está vacío, tiene un bucle Jinja roto o tiene info de sucursal obsoleta, lo actualizamos
            doc = frappe.get_doc("Email Template", template_name)
            is_broken = False
            current_html = doc.response_html or doc.response or ""
            if current_html and "{% for inv in invoices %}" in current_html and "{% endfor %}" in current_html:
                loop_content = current_html.split("{% for inv in invoices %}")[1].split("{% endfor %}")[0]
                if "<tr>" not in loop_content and "<tr" not in loop_content:
                    is_broken = True
            
            if current_html and ("branch_info" in current_html or "formatted_total" in current_html or "Monto Total" in current_html):
                is_broken = True

            if not current_html or len(current_html.strip()) < 50 or is_broken:
                doc.response_html = html_content
                doc.use_html = 1
                doc.save(ignore_permissions=True)
                print("Success: Plantilla 'Recordatorio de Retenciones Pendientes' actualizada con contenido base corregido.")
            else:
                print("  -- La plantilla 'Recordatorio de Retenciones Pendientes' ya existe y tiene contenido.")

    except Exception as e:
        print(f"Failure: Error en create_retention_reminder_email_template: {e}")
        frappe.log_error(frappe.get_traceback(), 'Error en create_retention_reminder_email_template')

