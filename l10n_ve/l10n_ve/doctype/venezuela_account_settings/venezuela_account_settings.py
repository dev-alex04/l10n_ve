# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

VAT_FROM_TOTAL = "Desde el total de la factura"


class VenezuelaAccountSettings(Document):

	def on_update(self):
		self._sync_vat_calculation_method()

	def _sync_vat_calculation_method(self) -> None:
		"""Sincroniza el método de cálculo del IVA con las plantillas de venta.

		El método elegido se materializa en el flag nativo de ERPNext
		`included_in_print_rate` de las filas VAT de las Sales Taxes and
		Charges Template: es el mecanismo estándar del framework para precios
		con IVA incluido, y todo lo que consume montos aguas abajo (HKA,
		retenciones, IGTF, libros) lee los campos que ese motor produce.

		Solo actúa cuando el valor cambia. Las facturas ya creadas conservan
		sus filas de impuestos (el flag viaja copiado a cada documento).
		"""
		if not self.has_value_changed("vat_calculation_method"):
			return

		inclusive: int = 1 if self.vat_calculation_method == VAT_FROM_TOTAL else 0

		rows: list[str] = frappe.get_all(
			"Sales Taxes and Charges",
			filters={
				"parenttype": "Sales Taxes and Charges Template",
				"charge_type": "VAT",
			},
			pluck="name",
		)

		for name in rows:
			frappe.db.set_value(
				"Sales Taxes and Charges", name,
				"included_in_print_rate", inclusive,
				update_modified=False,
			)

		frappe.clear_cache(doctype="Sales Taxes and Charges Template")

		if not rows:
			return

		if inclusive:
			frappe.msgprint(
				_("Método cambiado a <b>Desde el total de la factura</b>: se actualizaron "
				  "{0} fila(s) de IVA en las plantillas de venta.<br><br>"
				  "<b>⚠ Recuerde:</b> a partir de ahora los precios de planes y listas "
				  "deben cargarse <b>CON IVA incluido</b> (ej.: 35,00 en lugar de 30,17). "
				  "Los precios existentes deben migrarse a la nueva convención.").format(len(rows)),
				title=_("Método de cálculo del IVA"),
				indicator="orange",
			)
		else:
			frappe.msgprint(
				_("Método cambiado a <b>Desde la base imponible</b>: se actualizaron "
				  "{0} fila(s) de IVA en las plantillas de venta. Los precios de planes "
				  "y listas deben cargarse <b>SIN IVA</b> (base imponible).").format(len(rows)),
				title=_("Método de cálculo del IVA"),
				indicator="orange",
			)
