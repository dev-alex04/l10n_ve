"""Cambia el autonaming de Customer y Supplier a Naming Series.

El ``name`` (PK) deja de ser la razón social y pasa a una serie
(CUST-.YYYY.- / SUP-.YYYY.-), permitiendo homónimos con distinto RIF. Solo
afecta a los registros NUEVOS; los existentes conservan su ``name`` actual (no
hay rename masivo).

Prerrequisitos ya cubiertos: los displays fueron reapuntados a
customer_name / supplier_name / party_name (PRs l10n_ve#444 y domina_isp#503), el
Desk muestra el título en los Links (patch ``enable_party_title_in_link``), y el
payload a HKA usa la razón social (``customer.customer_name`` /
``supplier.supplier_name``), no el ``name``.

Se hace vía ``save()`` para disparar el ``on_update`` de Selling/Buying Settings,
que es quien propaga el valor al *global default* (``frappe.db.set_default``) que
lee el ``autoname`` de Customer/Supplier. Idempotente: no hace nada si ya está en
"Naming Series".
"""

import frappe

_TARGETS = (
	("Selling Settings", "cust_master_name"),
	("Buying Settings", "supp_master_name"),
)


def execute() -> None:
	for doctype, fieldname in _TARGETS:
		settings = frappe.get_single(doctype)
		if settings.get(fieldname) == "Naming Series":
			continue
		settings.set(fieldname, "Naming Series")
		settings.flags.ignore_permissions = True
		settings.save()
