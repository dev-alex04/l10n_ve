import os
import json
import frappe

from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import get_charts_for_country as erpnext_get_charts_for_country

@frappe.whitelist()
def get_charts_for_country(country, with_standard=False) -> list:

    def _get_chart_name(content) -> None:
        if content:
            content = json.loads(content)
            if (
                content and content.get("disabled", "No") == "No"
            ) or frappe.local.flags.allow_unverified_charts:
                charts.append(content["name"])

    charts = erpnext_get_charts_for_country(country, with_standard)

    app_name = __name__.split('.')[0]
    app_path = frappe.get_app_path(app_name)

    country_code = frappe.get_cached_value("Country", country, "code")
    if country_code:

        path = os.path.join(app_path, 'resources/chart_of_accounts')
        if not os.path.exists(path):
            return charts

        for fname in os.listdir(path):
            fname = frappe.as_unicode(fname)
            if (fname.startswith(country_code) or fname.startswith(country)) and fname.endswith(".json"):
                with open(os.path.join(path, fname)) as f:
                    _get_chart_name(f.read())

    # En caso de que contenga los 2 plaes de cuentas estandard + los verificados

    if len(charts) > 2:
        original_charts = charts
        charts = list(filter(lambda s: "Standard" not in s, original_charts))

    return charts
