# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


def set_ve_branch(doc: "Document", method: str) -> None:
    """Asigna la sucursal VE Branch al documento y establece el centro de costos correspondiente."""

    try:
        if not frappe.get_meta(doc.doctype).get_field("branch"):
            return

        if not doc.branch and doc.doctype == "Payment Entry":
            for ref in (doc.get("references") or []):
                if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
                    si_branch = frappe.db.get_value("Sales Invoice", ref.reference_name, "branch")
                    if si_branch:
                        doc.branch = si_branch
                        break

        if not doc.branch:
            branches = frappe.get_all("VE Branch Users", filters={
                "user": frappe.session.user,
                "parenttype": "VE Branch"
            }, fields=["parent"])

            unique_branches = list(set([b.parent for b in branches if b.parent]))

            if len(unique_branches) == 1:
                doc.branch = unique_branches[0]

            elif len(unique_branches) > 1:
                branches_list = ", ".join([frappe.bold(frappe.utils.escape_html(b)) for b in unique_branches])

                frappe.throw(
                    frappe._("El usuario tiene múltiples sucursales asignadas: {0}. Por favor seleccione una.").format(branches_list),
                    title=frappe._("Selección de Sucursal")
                )

        _set_cost_center_from_branch(doc)

    except Exception as e:
        if isinstance(e, frappe.exceptions.ValidationError):
            raise

        frappe.log_error(
            title="Error al asignar sucursal",
            message=f"Error al asignar sucursal: {str(e)} \n{frappe.get_traceback()}"
        )


def _set_cost_center_from_branch(doc: "Document") -> None:
    """Establece el centro de costos del documento basado en la sucursal VE Branch asignada.

    Aplica el cost_center a nivel de documento, a cada item de la tabla hija `items`,
    `taxes`, `references` y `deductions`.
    """
    if not doc.branch:
        return

    if not frappe.get_meta(doc.doctype).get_field("cost_center"):
        return

    branch_cost_center: str | None = frappe.get_cached_value(
        "VE Branch", doc.branch, "cost_center"
    )

    if not branch_cost_center:
        return

    doc.cost_center = branch_cost_center

    child_tables = [
        "items",
        "taxes",
        "references",
        "deductions"
    ]

    for table in child_tables:
        for item in (doc.get(table) or []):
            if not hasattr(item, "cost_center"):
                continue
            item.cost_center = branch_cost_center
