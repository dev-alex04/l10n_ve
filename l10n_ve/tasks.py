import requests

import frappe
from frappe.utils import getdate, formatdate, get_datetime_str


def create_currency_exchange() -> None:

    doctype_name_str = "Currency Exchange"
    response_error_str = "Error obteniendo la tasa USD del BCV"
    bcv_endpoint = frappe.get_site_config().bcv_endpoint

    if not bool(bcv_endpoint):
        frappe.log_error(
        response_error_str,
        f"debe establecer la URL del endpoint al" \
        f"bcv en el site_config.json")
        return

    try:

        response = requests.get(bcv_endpoint)

        if response.status_code != 200:
            frappe.log_error(response_error_str, f"{response.text}")


        else:
            to_currency = "VEF"
            currency_data = response.json()

            for from_currency in ('USD', 'EUR'):

                purpose = "Selling-Buying"
                exchange_rate = currency_data["promedio"]
                exchange_date =  getdate(currency_data["fechaActualizacion"])

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
                    currency_exchange.exchange_rate = currency_data["promedio"]

                    currency_exchange.insert()

    except Exception as e:
            frappe.log_error(response_error_str, f"{e}")
