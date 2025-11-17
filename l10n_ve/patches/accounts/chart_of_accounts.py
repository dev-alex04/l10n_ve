import os
import json
import frappe

from frappe.utils import cstr

from l10n_ve.whitelisted.account.chart_of_accounts import get_app_charts_path
from erpnext.accounts.doctype.account.chart_of_accounts import chart_of_accounts


@frappe.whitelist()
def get_chart(chart_template, existing_company=None):

    chart = {}
    if existing_company:
        return chart_of_accounts.get_account_tree_from_existing_company(existing_company)

    elif chart_template == "Standard":
        from erpnext.accounts.doctype.account.chart_of_accounts.verified import (
            standard_chart_of_accounts,
        )

        return standard_chart_of_accounts.get()
    elif chart_template == "Standard with Numbers":
        from erpnext.accounts.doctype.account.chart_of_accounts.verified import (
            standard_chart_of_accounts_with_account_number,
        )

        return standard_chart_of_accounts_with_account_number.get()
    else:
        folders = ("verified", get_app_charts_path())
        if frappe.local.flags.allow_unverified_charts:
            folders = ("verified", "unverified")
        for folder in folders:

            if not os.path.exists(os.path.join(os.path.dirname(__file__), folder)):
                continue

            path = os.path.join(os.path.dirname(__file__), folder)
            for fname in os.listdir(path):
                fname = frappe.as_unicode(fname)
                if fname.endswith(".json"):
                    with open(os.path.join(path, fname)) as f:
                        chart = f.read()
                        if chart and json.loads(chart).get("name") == chart_template:
                            return json.loads(chart).get("tree")


@frappe.whitelist()
def build_tree_from_json(chart_template, chart_data=None, from_coa_importer=False):# -> None | list[Any]:

    """get chart template from its folder and parse the json to be rendered as tree"""
    chart = chart_data or get_chart(chart_template)

    # if no template selected, return as it is
    if not chart:
        return

    accounts = []

    def _import_accounts(children, parent) -> None:
        """recursively called to form a parent-child based list of dict from chart template"""
        for account_name, child in children.items():
            account = {}
            if account_name in [
                "account_name",
                "account_number",
                "account_type",
                "root_type",
                "is_group",
                "tax_rate",
                "account_currency",
            ]:
                continue

            if from_coa_importer:
                account_name = child["account_name"]

            account["parent_account"] = parent
            account["expandable"] = True if chart_of_accounts.identify_is_group(child) else False
            account["value"] = (
                (cstr(child.get("account_number")).strip() + " - " + account_name)
                if child.get("account_number")
                else account_name
            )
            accounts.append(account)
            _import_accounts(child, account["value"])

    _import_accounts(chart, None)
    return accounts

chart_of_accounts.get_chart = get_chart
chart_of_accounts.build_tree_from_json = build_tree_from_json
