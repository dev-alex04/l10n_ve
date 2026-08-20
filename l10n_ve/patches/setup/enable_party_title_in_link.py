"""Activa ``show_title_field_in_link`` en Customer y Supplier.

Con el naming por serie (CUST-.YYYY.- / SUP-.YYYY.-), el ``name`` del
Customer/Supplier pasa a ser un ID opaco. Este flag hace que Frappe muestre el
``title_field`` (customer_name / supplier_name) en TODOS los campos Link y en las
columnas Link de listas/reportes del Desk, en vez del ID. Complementa los
reapuntes de display de las fases previas (print formats, SQL crudo, mensajes,
HTML/JS) que Frappe no auto-titula.

Idempotente: ``make_property_setter`` actualiza el Property Setter si ya existe.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute() -> None:
	for doctype in ("Customer", "Supplier"):
		make_property_setter(
			doctype,
			None,
			"show_title_field_in_link",
			1,
			"Check",
			for_doctype=True,
		)
		frappe.clear_cache(doctype=doctype)
