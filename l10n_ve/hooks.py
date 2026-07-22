app_name = "l10n_ve"
app_title = "L10N Ve"
app_publisher = "DominaERP"
app_description = "Localizacion Venezolana para ERPNext"
app_email = "dominaerp@domina.com.ve"
app_license = "mit"

# Branding Domina de fábrica (kit oficial): wordmark en Desk/login, isotipo en el splash,
# ícono en el favicon — el mismo mapeo que los sites brandeados a mano en Website Settings.
# Mismo patrón de erpnext (app_logo_url + website_context).
#
# Es un DEFAULT, no una imposición: los logos configurados POR SITE ganan siempre —
# frappe resuelve Website Settings/Navbar Settings ANTES del hook (navbar_settings.py:
# get_app_logo usa el hook solo como fallback) y aplica settings.favicon/splash_image
# DESPUÉS del hook (website_settings.py). Un site brandeado (ej. galanet prod con sus
# logos Galanet) conserva lo suyo; un site virgen nace con la marca Domina.
#
# Entre apps GANA la instalada DESPUÉS: en las imágenes de producto (erpnext -> l10n_ve
# -> ...) l10n_ve pisa a erpnext; en sites viejos donde l10n_ve se instaló antes que
# erpnext, ajustar por site. El wordmark por producto (ej. "Domina ISP") va en su app.
app_logo_url = "/assets/l10n_ve/images/domina-wordmark.png"
website_context = {
    "favicon": "/assets/l10n_ve/images/domina-favicon.png",
    "splash_image": "/assets/l10n_ve/images/domina-logo.png",
}

extend_bootinfo = "l10n_ve.boot.get_boot_info"
app_include_js = [
    "/assets/l10n_ve/js/toolbar/toolbar.js",
    "/assets/l10n_ve/js/item_logic/item_logic.js",
    "/assets/l10n_ve/js/utils/report_view_patch.js",
    "/assets/l10n_ve/js/utils/sales_billing_indicators.js",
    "/assets/l10n_ve/js/utils/fiscal_preview.js",
    "/assets/l10n_ve/js/doctype/sales_invoice/fiscal_invoice_preview.js",
    "/assets/l10n_ve/js/controllers/populate_from_invoice.js",
    "/assets/l10n_ve/js/widgets/number_card_widget.js",
    "/assets/l10n_ve/js/report/payment_period_based_on_invoice_date.js",
    "/assets/l10n_ve/js/report/general_ledger.js",
    "/assets/l10n_ve/js/report/accounts_receivable.js",
    "/assets/l10n_ve/js/report/accounts_payable.js",
]

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "l10n_ve",
# 		"logo": "/assets/l10n_ve/logo.png",
# 		"title": "L10N Ve",
# 		"route": "/l10n_ve",
# 		"has_permission": "l10n_ve.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

app_include_css = [
    "/assets/l10n_ve/css/digital_invoice_preview.css",
]

# page_js = {
#     "dashboard-view": "public/js/widgets/number_card_widget.js"
# }


# include js, css files in header of web template
# web_include_css = "/assets/l10n_ve/css/l10n_ve.css"
# web_include_js = "/assets/l10n_ve/js/l10n_ve.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "l10n_ve/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page

# include js in doctype views
doctype_js = {
    "Journal Entry": [
        "public/js/doctype/journal_entry/journal_entry.js",
    ],
    "Bank Statement Import": [
        "public/js/doctype/bank_statement_import/bank_statement_import.js",
    ],
    "Company": [
        "public/js/utils/utils.js",
        "public/js/doctype/company/company.js",
    ],
    "Customer": [
        "public/js/utils/utils.js",
        "public/js/doctype/customer/customer.js",
    ],
    "Supplier": [
        "public/js/utils/utils.js",
        "public/js/doctype/supplier/supplier.js",
    ],
    "Payment Entry": [
        "public/js/doctype/payment_entry/payment_entry.js",
        "public/js/utils/utils.js",
    ],
    "Sales Invoice": [
        "public/js/utils/utils.js",
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
        "public/js/doctype/sales_invoice/sales_invoice.js",
        "public/js/doctype/sales_invoice/sales_invoice_pdf_generator.js",
    ],
    "Purchase Invoice": [
        "public/js/utils/utils.js",
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
        "public/js/doctype/purchase_invoice/purchase_invoice.js",
    ],
    "Address": [
        "public/js/doctype/address/address.js",
    ],
    "Purchase Order": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
        "public/js/doctype/purchase_order/purchase_order.js",
    ],
    "Sales Order": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "Item": [
        "public/js/doctype/item/item.js",
    ],
    "Material Request": [
        "public/js/doctype/material_request/material_request.js",
    ],
    "Supplier Quotation": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "Quotation": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "Sales Taxes and Charges Template": [
        "public/js/doctype/sales_taxes_and_charges/sales_taxes_and_charges.js",
    ],
    "Purchase Taxes and Charges Template": [
        "public/js/doctype/purchase_taxes_and_charges/purchase_taxes_and_charges.js",
    ],
    "Stock Entry": [
        "public/js/doctype/stock_entry/stock_entry.js",
    ],
    "Project": [
        "public/js/doctype/project/project.js"
    ],
    "Task": [
        "public/js/doctype/task/task.js"
    ],
    "Installation Note": [
        "public/js/doctype/installation_note/installation_note.js"
    ],
    "VE Sales Debit Note": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "VE Sales Credit Note": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "VE Purchase Credit Note": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "VE Purchase Debit Note": [
        "public/js/controllers/transaction.js",
        "public/js/controllers/taxes_and_totals.js",
    ],
    "Mode of Payment": [
         "public/js/doctype/mode_of_payment/mode_of_payment.js"
    ],

}

doctype_list_js = {
    "Project": "public/js/doctype/project/project_list.js",
    "Sales Invoice": "public/js/doctype/sales_invoice/sales_invoice_list.js",
    "Journal Entry": "public/js/doctype/journal_entry/journal_entry_list.js",
    "Purchase Invoice": "public/js/doctype/purchase_invoice/purchase_invoice_list.js",
    "Currency Exchange": "public/js/doctype/currency_exchange/currency_exchange_list.js",
}

query_report_js = {
    "General Ledger": "public/js/report/general_ledger.js",
    "Accounts Receivable": "public/js/report/accounts_receivable.js",
    "Accounts Payable": "public/js/report/accounts_payable.js",
}

# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
doctype_calendar_js = {"Project": "public/js/doctype/project/project_calendar.js"}


# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "l10n_ve/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "l10n_ve.utils.jinja_methods",
# 	"filters": "l10n_ve.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "l10n_ve.install.before_install"

after_install = [
    "l10n_ve.patches.monkey_patches.apply_post_db_patches",
    "l10n_ve.setup.set_data"
]

after_migrate = [
    "l10n_ve.patches.monkey_patches.apply_post_db_patches",
    "l10n_ve.setup.create_currency_exchange",
    "l10n_ve.setup.setup_workspaces",
    # self-heal: los defaults de site_config (bcv_endpoint) se garantizan en cada migrate
    "l10n_ve.setup.set_default_site_config",
    # self-heal: logo del login/Desk solo-si-vacío (get_app_logo ignora el hook con >2 apps)
    "l10n_ve.setup.set_default_branding",
    # self-heal: custom fields y seed de tarifas de las retenciones gubernamentales (idempotentes)
    "l10n_ve.setup.create_government_withholding_custom_fields",
    "l10n_ve.setup.create_stamp_tax_rates",
]

# Uninstallation
# ------------

# before_uninstall = "l10n_ve.uninstall.before_uninstall"
# after_uninstall = "l10n_ve.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "l10n_ve.utils.before_app_install"
# after_app_install = "l10n_ve.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "l10n_ve.utils.before_app_uninstall"
# after_app_uninstall = "l10n_ve.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "l10n_ve.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

override_doctype_class = {
    "Item": "l10n_ve.overrides.item.CustomItem",
    "Company": "l10n_ve.overrides.company.CustomCompany",
    "Address": "l10n_ve.overrides.address.CustomAddress",
    "Supplier": "l10n_ve.overrides.supplier.CustomSupplier",
    "Customer": "l10n_ve.overrides.customer.VECustomer",
    "Quotation": "l10n_ve.overrides.quotation.CustomQuotation",
    "Item Price": "l10n_ve.overrides.item_price.CustomItemPrice",
    "Sales Order": "l10n_ve.overrides.sales_order.CustomSalesOrder",
    "Payment Entry": "l10n_ve.overrides.payment_entry.CustomPaymentEntry",
    "Sales Invoice": "l10n_ve.overrides.sales_invoice.VESalesInvoice",
    "Purchase Order": "l10n_ve.overrides.purchase_order.CustomPurchaseOrder",
    "Purchase Invoice": "l10n_ve.overrides.purchase_invoice.CustomPurchaseInvoice",
    "Supplier Quotation": "l10n_ve.overrides.supplier_quotation.CustomSupplierQuotation",
    "Tax Withholding Category": "l10n_ve.overrides.tax_withholding_category.CustomTaxWithholdingCategory",
    "Project": "l10n_ve.overrides.project.CustomProject",
    "Task": "l10n_ve.overrides.task.CustomTask",
    "Bank Statement Import": "l10n_ve.overrides.bank_statement_import.CustomBankStatementImport",
}

override_doctype_dashboards = {
    "Customer": "l10n_ve.overrides.customer.get_customer_dashboard_data",
    "Sales Invoice": "l10n_ve.overrides.sales_invoice.get_sales_invoice_dashboard_data",
    "Purchase Invoice": "l10n_ve.overrides.purchase_invoice.get_purchase_invoice_dashboard_data",
}


# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
    "Bank": {
        "on_change": "l10n_ve.api.clear_portal_banks_cache",
        "on_trash": "l10n_ve.api.clear_portal_banks_cache",
    },
    "ToDo": {
        "after_insert": "l10n_ve.overrides.task.auto_share_on_assignment",
    },
    "Sales Invoice": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Expense": {
        "before_insert": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Expense Report": {
        "before_insert": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Purchase Invoice": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Payment Entry": {
        # Conciliación migrada a mint (mint.apis.reconciliation): before_submit_receive_payment
        # y on_submit_receive_payment ahora se enganchan desde mint/hooks.py. Aquí queda
        # solo lo fiscal/sucursal.
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Mode of Payment": {
        "validate": "l10n_ve.overrides.mode_of_payment.validate_mode_of_payment",
    },
    # "Bank Transaction": conciliación (validate dup + reconcile drafts) migrada a mint/hooks.py.
    "Delivery Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Purchase Receipt": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "VE Purchase Credit Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "VE Purchase Debit Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "VE Sales Credit Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "VE Sales Debit Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "File": {
        "after_insert": "l10n_ve.overrides.task.sync_attachment_to_project",
    },
    "GL Entry": {
        "on_update": "l10n_ve.overrides.gl_entry.update_ve_outstanding_amount",
    },
    "User Permission": {
        "on_change": "l10n_ve.permissions.clear_ve_branch_cache",
    },
    "VE Branch": {
        "on_change": "l10n_ve.permissions.clear_ve_branch_cache",
    },
    "Currency Exchange": {
        "on_change": "l10n_ve.utils.utils.clear_exchange_rate_cache",
    },
    "Payment Ledger Entry": {
        "on_submit": "l10n_ve.overrides.payment_ledger_entry.on_submit_payment_ledger_entry",
        "on_cancel": "l10n_ve.overrides.payment_ledger_entry.on_cancel_payment_ledger_entry",
        "on_trash": "l10n_ve.overrides.payment_ledger_entry.on_trash_payment_ledger_entry",
    }
}
# Scheduled Tasks
# ---------------

scheduler_events = {
       "cron": {
        "0 8 10,20 * *": ["l10n_ve.tasks.send_missing_retentions_reminders"],
        "0 * * * *": [
            "l10n_ve.tasks.create_currency_exchange",
            "l10n_ve.tasks.cleanup_resolved_digital_invoice_error_logs",
            "l10n_ve.digital_invoice.reconciliation.reconcile_hka_fiscal_fields",
        ],
        "*/5 * * * *": ["l10n_ve.digital_invoice.tfhka_integration.send_pending_documents_to_hka"],
        "*/15 * * * *": ["l10n_ve.tasks.reset_all_prepared_reports"],
        "0 3 1 * *": ["l10n_ve.tasks.purge_old_digital_invoice_success_logs"],
        "0 4 * * *": ["l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.purge_old_fiscal_download_zips"],
    }
}

# Testing
# -------

# before_tests = "l10n_ve.install.before_tests"

# Overriding Methods
# ------------------------------
#

override_whitelisted_methods = {
    "frappe.desk.calendar.get_events": "l10n_ve.overrides.project.get_events",
    "erpnext.accounts.utils.get_coa": "l10n_ve.whitelisted.account.utils.get_coa",
    "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry": "l10n_ve.overrides.payment_entry.get_payment_entry",
    "erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_chart": "l10n_ve.patches.accounts.chart_of_accounts.get_chart",
    "erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.build_tree_from_json": "l10n_ve.patches.accounts.chart_of_accounts.build_tree_from_json",
    "erpnext.accounts.doctype.payment_entry.payment_entry.get_outstanding_reference_documents": "l10n_ve.overrides.payment_entry.get_outstanding_reference_documents",
    "erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.get_charts_for_country": "l10n_ve.whitelisted.account.chart_of_accounts.get_charts_for_country",
    "erpnext.accounts.doctype.bank_statement_import.bank_statement_import.get_preview_from_template": "l10n_ve.overrides.bank_statement_import.get_preview_from_template",
    # Capa 2: aislamiento de prepared_report por sesión de usuario
    "frappe.desk.query_report.run": "l10n_ve.patches.frappe.report_session_patch.run",
}

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "l10n_ve.task.get_dashboard_data"
# }


fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["module", "=", "L10N Ve"],
        ]
    },
    {
        "doctype": "Property Setter",
        "filters": [
            ["module", "=", "L10N Ve"],

        ]
    },
    {
        "doctype": "Print Format",
        "filters": [
            ["module", "=", "L10N Ve"]
        ]
    },
    {
        "doctype": "Report",
        "filters": [
            ["name", "=", "purchase_book"]
        ]
    },
    {
        "doctype": "Address Template",
        "filters": [
            ["name", "=", "Venezuela, Bolivarian Republic of"]
        ]
    },
    {
        "doctype": "Custom DocPerm",
        "filters": [
            ["parent", "=", "Sales Taxes and Charges Template"],
            ["role", "=", "System Manager"],
        ]
    }
]

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# Garantiza que los patches de reportes queden aplicados en los workers web
# (idempotente: solo la primera request de cada proceso hace trabajo real).
before_request = ["l10n_ve.patches.monkey_patches.ensure_post_db_patches"]
# after_request = ["l10n_ve.utils.after_request"]

# Job Events
# ----------
# Igual que before_request pero para workers de RQ (scheduler, Auto Email
# Reports, jobs encolados): sin esto los reportes corren sin parchear.
before_job = ["l10n_ve.patches.monkey_patches.ensure_post_db_patches"]
# after_job = ["l10n_ve.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"l10n_ve.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Registros Dinamicos de Permisos de Sucursal (VE Branch)
permission_query_conditions = {}
has_permission = {}

def _register_ve_branch_restrictions() -> None:
    """
    Busca dinamicamente todos los DocTypes del sistema que se enlazan con VE Branch
    y registra las funciones de intercepcion de permisos de forma segura para evitar
    romper la instalacion inicial del sitio.
    """
    try:
        import frappe
        if frappe.db and frappe.db.exists("DocType", "DocField"):
            # 1. Buscar DocTypes con campos Link estandar a VE Branch
            std_doctypes = frappe.db.sql("""
                SELECT DISTINCT parent FROM tabDocField 
                WHERE fieldtype='Link' AND options='VE Branch'
            """, as_dict=True)
            
            # 2. Buscar DocTypes con campos Link personalizados a VE Branch
            cust_doctypes = frappe.db.sql("""
                SELECT DISTINCT dt AS parent FROM `tabCustom Field` 
                WHERE fieldtype='Link' AND options='VE Branch'
            """, as_dict=True)

            # 3. Buscar DocTypes modificados via Property Setter a VE Branch
            prop_doctypes = frappe.db.sql("""
                SELECT DISTINCT doc_type AS parent FROM `tabProperty Setter` 
                WHERE property='options' AND value='VE Branch'
            """, as_dict=True)
            
            all_dt = {d.parent for d in (std_doctypes + cust_doctypes + prop_doctypes)}
            all_dt.add("VE Branch") # Registrar tambien a si mismo
            
            for dt in all_dt:
                permission_query_conditions[dt] = "l10n_ve.permissions.get_ve_branch_permission_query"
                has_permission[dt] = "l10n_ve.permissions.has_ve_branch_permission"
    except Exception:
        # Silenciar excepciones durante bench new-site o restauraciones iniciales
        pass

_register_ve_branch_restrictions()

