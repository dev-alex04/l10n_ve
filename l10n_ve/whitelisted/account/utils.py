import frappe
from frappe import _

@frappe.whitelist()
def get_coa(doctype, parent, is_root=None, chart=None) -> list:
    from l10n_ve.patches.accounts.chart_of_accounts import build_tree_from_json

    # add chart to flags to retrieve when called from expand all function
    chart = chart if chart else frappe.flags.chart
    frappe.flags.chart = chart

    parent = None if parent == _("All Accounts") else parent
    accounts = build_tree_from_json(chart)  # returns alist of dict in a tree render-able form

    # filter out to show data for the selected node only
    accounts = [d for d in accounts if d["parent_account"] == parent]

    return accounts
