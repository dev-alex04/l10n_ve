# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe


def set_ve_branch(doc, method):

    try:
        if not frappe.get_meta(doc.doctype).get_field("branch"):
            return

        if doc.branch:
            return

        branch = frappe.db.get_value("VE Branch Users", {
            "user": frappe.session.user,
        }, "parent")

        if not branch:
            return

        doc.branch = branch

    except Exception as e:
        frappe.log_error(
            title=f"Error al asignar sucursal",
            message=f"Error al asignar sucursal: {str(e)} \n{frappe.get_traceback()}"
        )
