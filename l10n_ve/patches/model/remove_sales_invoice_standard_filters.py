"""Elimina los filtros estándar de 'Es Nota de Crédito' y 'Nota de Débito'
del listado de Sales Invoice.

En Venezuela las notas de crédito se manejan como un doctype separado
(VE Sales Credit Note), no como Sales Invoice con is_return=1,
por lo que estos filtros no aplican y confunden al usuario.
"""

import frappe


def execute() -> None:
    property_setters_to_remove: list[str] = [
        "Sales Invoice-is_return-in_standard_filter",
        "Sales Invoice-is_debit_note-in_standard_filter",
    ]

    for ps_name in property_setters_to_remove:
        if frappe.db.exists("Property Setter", ps_name):
            frappe.delete_doc("Property Setter", ps_name, force=True)

    frappe.clear_cache(doctype="Sales Invoice")
