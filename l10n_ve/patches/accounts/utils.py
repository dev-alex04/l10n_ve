import frappe
from frappe import _

import erpnext.accounts.utils

@frappe.whitelist()
def get_company_default(company, fieldname, ignore_validation=False):
    value = frappe.get_value("Company", company, fieldname)
    if not ignore_validation and not value:
        frappe.throw(
            _("Please set default {0} in Company {1}").format(
                _(frappe.get_meta("Company").get_label(fieldname)), company
            )
        )
    return value

erpnext.accounts.utils.get_company_default = get_company_default
