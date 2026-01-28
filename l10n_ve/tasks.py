import requests

import frappe
from frappe.utils import getdate, formatdate, get_datetime_str


@frappe.whitelist()
def create_currency_exchange() -> None:

    doctype_name_str = "Currency Exchange"
    response_error_str = "Error obteniendo las tasas de cambio del BCV"
    bcv_endpoint = frappe.get_site_config().bcv_endpoint
    bcv_api_key = frappe.get_site_config().bcv_api_key
    error_message = frappe._("Ocurrió un error al intentar actualizar las tasas de cambio. " \
                      "Por favor, contacte al administrador del sistema.")

    if not bool(bcv_endpoint):
        frappe.log_error(
        response_error_str,
        f"debe establecer la URL del endpoint al" \
        f"bcv en el site_config.json")
        frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")
        return

    try:

        headers = {}
        if bcv_api_key:
            headers["x-dolarvzla-key"] = bcv_api_key

        response = requests.get(bcv_endpoint, headers=headers)

        if response.status_code != 200:
            frappe.log_error(response_error_str, f"{response.text}")
            frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")

        else:
            to_currency = "VEF"
            currency_data = response.json()
            current_rates = currency_data.get("current", {})
            date_str = current_rates.get("date")

            if not date_str:
                frappe.log_error(f"La fecha no fue encontrada en la respuesta de"
                                 f" la API del BCV. Datos recibidos: {currency_data}")
                frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")
                return

            exchange_date = getdate(date_str)
            purpose = "Selling-Buying"

            for from_currency in ['USD', 'EUR']:
                exchange_rate = current_rates.get(from_currency.lower())

                if not exchange_rate:
                    frappe.log_error(f"Tasa de cambio no encontrada para {from_currency} "
                                     f"en la respuesta del BCV. Datos recibidos: {currency_data}")
                    frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")
                    continue

                exchange_name = "{}-{}-{}{}".format(
                    formatdate(get_datetime_str(exchange_date), "yyyy-MM-dd"),
                    from_currency,
                    to_currency,
                    ("-" + purpose) if purpose else "")

                if bool(frappe.db.exists(doctype_name_str, exchange_name)):

                    frappe.db.set_value(doctype_name_str,
                                         exchange_name,
                                         "exchange_rate",
                                         exchange_rate )

                else:
                    currency_exchange = frappe.new_doc(doctype_name_str)

                    currency_exchange.for_buying = True
                    currency_exchange.for_selling = True
                    currency_exchange.date =  exchange_date
                    currency_exchange.to_currency = to_currency
                    currency_exchange.from_currency = from_currency
                    currency_exchange.exchange_rate = exchange_rate

                    currency_exchange.insert()

    except Exception as e:
        frappe.log_error(response_error_str, f"{e}")
        frappe.msgprint(error_message, title=frappe._("Error"), indicator="red")
