# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.utils.nestedset import NestedSet


class VEEconomicActivity(NestedSet):
	pass

@frappe.whitelist()
def get_economic_activity_options(sector=None, group=None):
    """
    Devuelve una lista de opciones para los campos 'group' o 'branch'
    basándose en las selecciones de 'sector' y 'group'.

    :param sector: El sector seleccionado.
    :param group: El grupo seleccionado.
    :return: Una lista de strings con las opciones.
    """
    if not sector:
        return []


    if sector and not group:
        groups = frappe.db.get_all(
            "VE Economic Activity",
            filters={"sector": sector},
            fields=["group"],
            distinct=True,
            order_by="group"
        )
        return sorted([d.get("group") for d in groups if d.get("group")])


    branches = frappe.db.get_all(
        "VE Economic Activity",
        filters={"sector": sector, "group": group},
        fields=["branch"],
        distinct=True,
        order_by="branch"
    )
    return sorted([d.get("branch") for d in branches if d.get("branch")])
