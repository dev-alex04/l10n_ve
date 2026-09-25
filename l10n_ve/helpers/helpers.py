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

        is_expense_doc = doc.doctype in ["Expense", "Expense Report", "Expenses Entry", "Expenses Request"]

        if not doc.branch and doc.doctype == "Payment Entry":
            for ref in (doc.get("references") or []):
                if ref.reference_doctype == "Sales Invoice" and ref.reference_name:
                    si_branch = frappe.db.get_value("Sales Invoice", ref.reference_name, "branch")
                    if si_branch:
                        doc.branch = si_branch
                        break

        if not doc.branch:
            # 1. Intentar resolver por sucursal principal o sucursal de gastos de la compañía
            if getattr(doc, "company", None):
                main_branch = frappe.db.get_value("VE Branch", {"company": doc.company, "is_main": 1, "is_group": 0}, "name")
                if not main_branch:
                    main_branch = frappe.db.get_value("VE Branch", {"company": doc.company, "is_expenses_branch": 1, "is_group": 0}, "name")
                if main_branch:
                    doc.branch = main_branch

            # 2. Intentar por usuario si aún no tiene branch
            if not doc.branch:
                branches = frappe.get_all("VE Branch Users", filters={
                    "user": frappe.session.user,
                    "parenttype": "VE Branch"
                }, fields=["parent"])

                unique_branches = list(set([b.parent for b in branches if b.parent]))

                if len(unique_branches) == 1:
                    doc.branch = unique_branches[0]

                elif len(unique_branches) > 1:
                    if is_expense_doc:
                        # Para gastos en empresas pequeñas o sin sucursal fija, usar la primera o dejar opcional
                        doc.branch = unique_branches[0]
                    else:
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


def _payment_entry_invoice_cost_centers(doc: "Document") -> set:
    """Centros de costo de las Sales Invoice que este cobro salda."""
    names = [
        ref.reference_name
        for ref in (doc.get("references") or [])
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name
    ]
    if not names:
        return set()

    rows = frappe.get_all(
        "Sales Invoice",
        filters={"name": ["in", names]},
        fields=["name", "cost_center"],
    )
    found = {r.name: r.cost_center for r in rows}
    return {found.get(name) or None for name in names}


def _set_cost_center_from_branch(doc: "Document") -> None:
    """Establece el centro de costos del documento."""
    if not frappe.get_meta(doc.doctype).get_field("cost_center"):
        return

    branch_cost_center: str | None = (
        frappe.get_cached_value("VE Branch", doc.branch, "cost_center")
        if doc.branch else None
    )

    cost_center: str | None = branch_cost_center

    if doc.doctype == "Payment Entry":
        invoice_cost_centers = _payment_entry_invoice_cost_centers(doc)
        if len(invoice_cost_centers) == 1 and None not in invoice_cost_centers:
            cost_center = invoice_cost_centers.pop()

    if not cost_center and getattr(doc, "company", None):
        cost_center = frappe.get_cached_value("Company", doc.company, "cost_center")

    if not cost_center:
        return

    doc.cost_center = cost_center

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
            item.cost_center = cost_center


def get_root_branches() -> list[str]:
    """Obtiene dinámicamente las sucursales raíz del árbol (is_group = 1 sin padre)."""
    return frappe.db.get_all(
        "VE Branch",
        filters={"is_group": 1, "parent_ve_branch": ["in", ["", None]]},
        pluck="name"
    ) or []


def is_root_branch_user(user: str | None = None) -> bool:
    """Verifica dinámicamente si un usuario tiene acceso global a modos de pago de la compañía.

    Retorna True si:
    - Es Administrator o cuenta con roles de administración global (System Manager / Super Admin),
      incluso si tiene permisos de usuario acotados a sucursales locales.
    - Tiene permiso de usuario (User Permission) sobre alguna sucursal raíz del árbol VE Branch.
    - Está asignado en la tabla hija de usuarios (VE Branch Users) de alguna sucursal raíz.

    Retorna False si el usuario es un operador exclusivo de sucursal local o si no existen
    sucursales raíz configuradas en el sistema (falla cerrado por seguridad).
    """
    if not user:
        user = frappe.session.user

    if user == "Administrator":
        return True

    roles = frappe.get_roles(user)
    if "System Manager" in roles or "Super Admin" in roles:
        return True

    root_branches = get_root_branches()
    if not root_branches:
        # Sin raíces la detección no puede decidir: se falla cerrado. Abrir el permiso
        # a todos cuando falta el dato convierte un error de configuración del árbol en
        # una ampliación silenciosa de acceso (permiso de ver todo el catálogo).
        # Una sola vez por petición: como la llama el `search_link` del campo Modo de
        # Pago, que se dispara en cada pulsación (5 letras = 5 filas idénticas).
        if not frappe.flags.get("l10n_ve_no_root_branch_logged"):
            frappe.flags.l10n_ve_no_root_branch_logged = True
            frappe.log_error(
                title="is_root_branch_user: no hay sucursales raíz",
                message="Ningún VE Branch con is_group=1 y sin padre; se deniega el acceso.",
            )
        return False

    # 1. Permiso de usuario sobre alguna sucursal raíz
    if frappe.db.exists("User Permission", {
        "user": user,
        "allow": "VE Branch",
        "for_value": ["in", root_branches]
    }):
        return True

    # 2. Asignado en la tabla de usuarios de alguna sucursal raíz
    if frappe.db.exists("VE Branch Users", {
        "user": user,
        "parent": ["in", root_branches]
    }):
        return True

    return False

