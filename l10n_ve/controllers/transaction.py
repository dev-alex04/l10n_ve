import frappe

@frappe.whitelist()
def get_currency_symbol(currency) -> str:

    return frappe.db.get_value('Currency', currency, 'symbol') or currency
