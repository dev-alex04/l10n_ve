import frappe
from frappe import _


from erpnext.accounts.utils import get_company_default

@frappe.whitelist()
def custom_get_company_default(company, fieldname, ignore_validation=False):
    value = frappe.get_value("Company", company, fieldname)

    if not ignore_validation and not value:
        frappe.throw(
            _("Please set default {0} in Company {1}").format(
                _(frappe.get_meta("Company").get_label(fieldname)), company
            )
        )

    return value


get_company_default = custom_get_company_default