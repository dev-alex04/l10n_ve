app_name = "l10n_ve"
app_title = "L10N Ve"
app_publisher = "DominaERP"
app_description = "Localizacion Venezolana"
app_email = "dominaerp@domina.com.ve"
app_license = "mit"

override_doctype_class = {
    "Purchase Invoice": "l10n_ve.overrides.purchase_invoice.CustomPurchaseInvoice",
    "Company": "l10n_ve.overrides.company.CustomCompany",
}

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
# app_include_js = "/assets/l10n_ve/js/l10n_ve.js"

# include js, css files in header of web template
# web_include_css = "/assets/l10n_ve/css/l10n_ve.css"
# web_include_js = "/assets/l10n_ve/js/l10n_ve.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "l10n_ve/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

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
# after_install = "l10n_ve.install.after_install"

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

# override_doctype_class = {
#     "Purchase Invoice": "l10n_ve.overrides.purchase_invoice.CustomPurchaseInvoice"
# }


# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
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
# }

# Testing
# -------

# before_tests = "l10n_ve.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "l10n_ve.event.get_events"
# }
#
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
            
             ["dt", "in", ["Sales Invoice", "Company" , "Customer", "Sales Taxes and Charges Template", "VAT Withholding Voucher", "VAT Withholding Voucher Item", "Purchase Invoice"]],
            
            ["module", "=", "L10N Ve"],
        ]
    },
    {
        "doctype": "Property Setter",
        "filters": [
            ["doc_type", "=", "Branch"],
            ["module", "=", "L10N Ve"],

        ]
    },
    {
        "doctype": "Print Format",
        "filters": [
            ["module", "=", "L10N Ve"]
        ]
    },
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
