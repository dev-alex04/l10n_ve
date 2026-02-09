# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe


def set_ve_branch(doc, method):

    try:
        if not frappe.get_meta(doc.doctype).get_field("branch"):
            return

        if doc.branch:
            return

        branches = frappe.get_all("VE Branch Users", filters={
            "user": frappe.session.user,
            "parenttype": "VE Branch"
        }, fields=["parent"])

        unique_branches = list(set([b.parent for b in branches if b.parent]))

        if len(unique_branches) == 1:
            doc.branch = unique_branches[0]

        elif len(unique_branches) > 1:
            branches_list = ", ".join([frappe.bold(frappe.utils.escape_html(b)) for b in unique_branches])
            
            frappe.msgprint(
                frappe._("El usuario tiene múltiples sucursales asignadas: {0}. Por favor seleccione una.").format(branches_list),
                title=frappe._("Selección de Sucursal"),
                indicator='blue'
            )
    except Exception as e:
        frappe.log_error(
            title=f"Error al asignar sucursal",
            message=f"Error al asignar sucursal: {str(e)} \n{frappe.get_traceback()}"
        )
