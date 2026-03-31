app_name = "l10n_ve"
app_title = "L10N Ve"
app_publisher = "DominaERP"
app_description = "Localizacion Venezolana para ERPNext"
app_email = "dominaerp@domina.com.ve"
app_license = "mit"

app_include_js = [
    "/assets/l10n_ve/js/toolbar/toolbar.js",
    "/assets/l10n_ve/js/item_logic/item_logic.js",
    "/assets/l10n_ve/js/utils/report_view_patch.js",
    "/assets/l10n_ve/js/widgets/number_card_widget.js",
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

# include js, css files in header of desk.html
# app_include_css = "/assets/l10n_ve/css/l10n_ve.css"


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

}

doctype_list_js = {
    "Project": "public/js/doctype/project/project_list.js",
    "Sales Invoice": "public/js/doctype/sales_invoice/sales_invoice_list.js",
    "Journal Entry": "public/js/doctype/journal_entry/journal_entry_list.js",
    "Purchase Invoice": "public/js/doctype/purchase_invoice/purchase_invoice_list.js",
    "Currency Exchange": "public/js/doctype/currency_exchange/currency_exchange_list.js",
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


# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
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
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Delivery Note": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "Purchase Receipt": {
        "before_submit": "l10n_ve.helpers.helpers.set_ve_branch",
    },
    "File": {
        "after_insert": "l10n_ve.overrides.task.sync_attachment_to_project",
    }
}
# Scheduled Tasks
# ---------------

scheduler_events = {
       "cron": {
        "0 * * * *": ["l10n_ve.tasks.create_currency_exchange"],
    }
    # "all": [
# 		"l10n_ve.tasks.all"
# 	],
# 	"daily": [
# 		"l10n_ve.tasks.daily"
# 	],
# 	"hourly": [
# 		"l10n_ve.tasks.hourly"
# 	],
# 	"weekly": [
# 		"l10n_ve.tasks.weekly"
# 	],
# 	"monthly": [
# 		"l10n_ve.tasks.monthly"
# 	],
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
# before_request = ["l10n_ve.utils.before_request"]
# after_request = ["l10n_ve.utils.after_request"]

# Job Events
# ----------
# before_job = ["l10n_ve.utils.before_job"]
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
