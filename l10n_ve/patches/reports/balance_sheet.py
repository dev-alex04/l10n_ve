import frappe
from frappe import _
import erpnext.accounts.report.balance_sheet.balance_sheet as bs

original_execute = bs.execute

def custom_execute(filters=None):
    result = original_execute(filters)
    
    res_list = list(result)
    
    if filters and filters.get("company"):
        tax_id = frappe.get_cached_value("Company", filters.get("company"), "tax_id")
        if tax_id:

            rif_html = f"<div style='color: black; font-weight: bold; margin-bottom: 15px; font-size: 1.1em;'>{_('RIF')}: {tax_id}</div>"
            original_msg = res_list[2] or ""
            res_list[2] = rif_html + original_msg

    return tuple(res_list)

bs.execute = custom_execute
