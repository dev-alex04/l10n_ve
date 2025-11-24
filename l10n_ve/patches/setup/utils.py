import frappe
from frappe import _
from frappe.utils import add_days, flt, get_datetime_str, nowdate
import erpnext.setup.utils as utils
import requests

PEGGED_CURRENCIES = {
	"USD": {"AED": 3.6725},  # AED is pegged to USD at a rate of 3.6725 since 1997
}


def get_pegged_rate(from_currency: str, to_currency: str, transaction_date) -> float | None:
	if rate := PEGGED_CURRENCIES.get(from_currency, {}).get(to_currency):
		return rate
	elif rate := PEGGED_CURRENCIES.get(to_currency, {}).get(from_currency):
		return 1 / rate
	return None


def format_ces_api(data: str, param: dict) -> str:
	return data.format(
		transaction_date=param.get("transaction_date"),
		to_currency=param.get("to_currency"),
		from_currency=param.get("from_currency"),
	)

@frappe.whitelist()
def get_exchange_rate(from_currency, to_currency, transaction_date=None, args=None) -> int | float | None:
	"""
	Busca la tasa de cambio para un par de divisas en una fecha determinada.

	1. Busca en la base de datos una tasa para la fecha exacta de la transacción.
	2. Si no la encuentra, busca la tasa más reciente disponible en la base de datos,

	"""
	if not (from_currency and to_currency):
		return

	if from_currency == to_currency:
		return 1

	if not transaction_date:
		transaction_date = nowdate()

	currency_settings = frappe.get_doc("Accounts Settings").as_dict()
	allow_stale_rates = currency_settings.get("allow_stale")

	exact_date_filters = [
		["date", "=", get_datetime_str(transaction_date)],
		["from_currency", "=", from_currency],
		["to_currency", "=", to_currency],
	]

	entries = frappe.get_all(
		"Currency Exchange",
		fields=["exchange_rate"],
		filters=exact_date_filters,
		order_by="date desc",
		limit=1
	)

	if entries:
		return flt(entries[0].exchange_rate)

	filters = [
		["from_currency", "=", from_currency],
		["to_currency", "=", to_currency],
	]

	if args == "for_buying":
		filters.append(["for_buying", "=", "1"])

	elif args == "for_selling":
		filters.append(["for_selling", "=", "1"])

	if not allow_stale_rates:

		stale_days = currency_settings.get("stale_days")
		checkpoint_date = add_days(transaction_date, -stale_days)
		filters.append(["date", ">", get_datetime_str(checkpoint_date)])

	entries = frappe.get_all(
		"Currency Exchange",
		fields=["exchange_rate"],
		filters=filters,
		order_by="date desc",
		limit=1
	)

	if entries:
		return flt(entries[0].exchange_rate)

	if frappe.get_cached_value("Currency Exchange Settings",
							   "Currency Exchange Settings",
							   "disabled"):
		return 0.00

	if rate := get_pegged_rate(from_currency, to_currency, transaction_date):
		return rate

	try:
		cache = frappe.cache()
		key = f"currency_exchange_rate_{transaction_date}:{from_currency}:{to_currency}"
		value = cache.get(key)

		if not value:

			settings = frappe.get_cached_doc("Currency Exchange Settings")
			req_params = {
				"transaction_date": transaction_date,
				"from_currency": from_currency if from_currency != "AED" else "USD",
				"to_currency": to_currency if to_currency != "AED" else "USD",
			}

			params = {}
			for row in settings.req_params:
				params[row.key] = format_ces_api(row.value, req_params)

			response = requests.get(format_ces_api(settings.api_endpoint, req_params), params=params)
			response.raise_for_status()
			value = response.json()

			for res_key in settings.result_key:
				value = value[format_ces_api(str(res_key.key), req_params)]

			cache.setex(name=key, time=21600, value=flt(value))

		value = flt(value)
		if to_currency == "AED":
			value *= 3.6725

		if from_currency == "AED":
			value /= 3.6725

		return flt(value)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Unable to fetch exchange rate")

		frappe.msgprint(
			_(
				"Unable to find exchange rate for {0} to {1} for key date {2}." \
				" Please create a Currency Exchange record manually"
			).format(from_currency, to_currency, transaction_date)
		)
		return 0.0

utils.get_exchange_rate = get_exchange_rate