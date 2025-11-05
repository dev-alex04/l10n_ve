import os
import json
import frappe

from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import get_charts_for_country as erpnext_get_charts_for_country

@frappe.whitelist()
def get_charts_for_country(country, with_standard=False) -> list:
    """Busca planes de cuenta personalizados para un país y, si no los encuentra,
    recurre a los planes estándar de ERPNext.
    """

    custom_charts = []
    app_name = __name__.split('.')[0]
    app_path = frappe.get_app_path(app_name)

    country_code = frappe.get_cached_value("Country", country, "code")
    if not country_code:
        return erpnext_get_charts_for_country(country, with_standard)

    charts_path = os.path.join(app_path, 'resources/chart_of_accounts')
    if not os.path.exists(charts_path):
        return erpnext_get_charts_for_country(country, with_standard)

    for fname in os.listdir(charts_path):
        fname = frappe.as_unicode(fname)

        if (fname.startswith(country_code) or \
            fname.startswith(country)) and fname.endswith(".json"):

            try:
                with open(os.path.join(charts_path, fname), "r", encoding="utf-8") as f:
                    content = json.load(f)

                    if (content and content.get("disabled", "No") == "No") or \
                        frappe.local.flags.allow_unverified_charts:
                        custom_charts.append(content["name"])

            except (IOError, json.JSONDecodeError, KeyError) as e:
                frappe.log_error(
                    message=f"No se pudo leer o procesar el archivo del plan de cuentas: {fname}. Error: {e}",
                    title="Error en Plan de Cuentas"
                )

    if custom_charts:
        return custom_charts

    return erpnext_get_charts_for_country(country, with_standard)
