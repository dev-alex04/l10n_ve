import json

import frappe
import erpnext.stock.utils as stock_utils
from frappe.utils import flt

# Guardar una referencia a la función original
original_get_incoming_rate = stock_utils.get_incoming_rate

@frappe.whitelist()
def get_incoming_rate(args, raise_error_if_no_rate=True, **kwargs):
	"""
	Obtiene la tasa de entrada.
	Prioriza el 'price_purchase' del maestro de artículos.
	Si no existe, delega a la función original de ERPNext.

	Acepta **kwargs para compatibilidad futura con parámetros adicionales
	que ERPNext pueda agregar (ej: fallbacks).
	"""
	if isinstance(args, str):
		args = json.loads(args)

	item_code = args.get("item_code")
	if item_code:
		price_purchase = frappe.db.get_value("Item", item_code, "price_purchase")
		if price_purchase:
			return flt(price_purchase)

	kwargs.clear()

	return original_get_incoming_rate(args, raise_error_if_no_rate, **kwargs)

stock_utils.get_incoming_rate = get_incoming_rate