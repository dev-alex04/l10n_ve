# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class VenezuelaAccountSettings(Document):
	# El método de cálculo de impuestos (tax_calculation_method) no requiere
	# lógica aquí: lo lee el motor (l10n_ve.controllers.taxes_and_totals) en
	# cada cálculo, y el guardado del Single invalida su caché solo.
	pass
