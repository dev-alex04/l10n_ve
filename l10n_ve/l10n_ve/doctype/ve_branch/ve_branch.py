# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _, _dict
from frappe.utils.nestedset import NestedSet


class VEBranch(NestedSet):

    def before_validate(self) -> None:
        """
        Hereda los datos de la sucursal padre si es aplicable (ej. en creación por API/importación).
        """
        self.inherit_from_parent_if_applicable()

    def validate(self) -> None:
        self.validate_unique_users()
        self.validate_payment_modes()

    def inherit_from_parent_if_applicable(self) -> None:
        """
        Si se ha seleccionado un padre y las tablas hijas están vacías, hereda los datos.
        """
        if self.is_group:
            return

        is_new_with_parent = self.is_new() and self.parent_ve_branch
        parent_has_changed = False
        if not self.is_new():
            doc_before_save = self.get_doc_before_save()
            if doc_before_save and self.parent_ve_branch != doc_before_save.get("parent_ve_branch"):
                parent_has_changed = True

        if not (is_new_with_parent or parent_has_changed):
            return

        if self.users or self.mode_of_payments:
            return

        if not self.parent_ve_branch:
            return

        try:
            parent = frappe.get_doc("VE Branch", self.parent_ve_branch)
        except frappe.DoesNotExistError:
            return

        for user_row in parent.get("users", []):
            self.append("users", {"user": user_row.user})

        for payment_row in parent.get("mode_of_payments", []):
            self.append("mode_of_payments", {
                "mode_of_payment": payment_row.mode_of_payment,
                "is_default": payment_row.is_default,
                "account": payment_row.account,
                "payment_information": payment_row.payment_information
            })

    @frappe.whitelist()
    def get_details_from_parent(self, parent_branch: str) -> dict:
        """Obtiene los detalles de la sucursal padre para heredarlos en el cliente."""
        if not parent_branch:
            return {}

        parent = frappe.get_doc("VE Branch", parent_branch)

        return {
            "users": [d.as_dict() for d in parent.users],
            "mode_of_payments": [d.as_dict() for d in parent.mode_of_payments]
        }

    def validate_payment_modes(self) -> None:
        """Valida la tabla de modos de pago de la sucursal."""
        payment_modes = self.get("mode_of_payments", [])

        if not payment_modes:
            frappe.throw(
                _("La tabla de modos de pago no puede estar vacía. Debe agregar al menos un modo de pago.")
            )

        default_rows = [row for row in payment_modes if row.is_default]

        if len(payment_modes) == 1:

            payment_modes[0].is_default = 1

        elif len(default_rows) == 0:
            frappe.throw(
                _("Debe marcar un modo de pago como predeterminado.")
            )

        elif len(default_rows) > 1:
            frappe.throw(
                _("Solo puede haber un modo de pago predeterminado.")
            )


    def validate_unique_users(self) -> None:
        """Valida que un usuario no esté asignado a más de una sucursal y no esté duplicado en la misma."""
        users = [row.user for row in self.get("users", []) if row.user]
        if not users:
            return

        if len(users) != len(set(users)):
            seen = set()
            for user in users:
                if user in seen:
                    frappe.throw(
                        _("El usuario {0} está asignado varias veces en esta sucursal.").format(
                            frappe.bold(user)
                        )
                    )
                seen.add(user)

        existing_assignments = frappe.get_all(
            "VE Branch Users",
            filters={"user": ["in", users], "parent": ["!=", self.name], "parenttype": "VE Branch"},
            fields=["user", "parent"],
        )

        if not existing_assignments:
            return

        other_branch_names = list(set(d.parent for d in existing_assignments))
        other_branches_info = frappe.get_all(
            "VE Branch",
            filters={"name": ["in", other_branch_names]},
            fields=["name", "parent_ve_branch"],
        )
        other_branches_parent_map = {b.name: b.parent_ve_branch for b in other_branches_info}

        current_branch_parent = self.parent_ve_branch

        for assignment in existing_assignments:
            user = assignment.user
            other_branch = assignment.parent

            is_other_parent = (current_branch_parent and current_branch_parent == other_branch)

            other_branch_parent = other_branches_parent_map.get(other_branch)
            is_other_child = (other_branch_parent and other_branch_parent == self.name)

            is_sibling = (current_branch_parent and other_branch_parent and current_branch_parent == other_branch_parent)

            if not (is_other_parent or is_other_child or is_sibling):
                frappe.throw(
                    _("El usuario {0} ya está asignado a la sucursal {1}. " 
                      "Solo se permite repetir usuarios entre ramas relacionadas "
                      "(Padre, Hija, Hermana).").format(
                        frappe.bold(user), frappe.bold(other_branch)
                    )
                )

    def get_default_payment_mode(self) -> _dict:
        """Obtiene el modo de pago predeterminado de la sucursal."""

        default_payment_mode = next(
            (row for row in self.get("mode_of_payments", []) if row.is_default),
            None
        )

        return _dict(default_payment_mode.as_dict())


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_modes_of_payment_for_company(doctype, txt, searchfield, start, page_len, filters):
    """Obtiene los modos de pago que tienen cuenta configurada para una empresa."""
    company = filters.get("company")
    if not company:
        return []

    return frappe.db.sql("""
        SELECT DISTINCT mop.name
        FROM `tabMode of Payment` mop
        INNER JOIN `tabMode of Payment Account` mopa ON mopa.parent = mop.name
        WHERE mopa.company = %(company)s
        AND mop.name LIKE %(txt)s
        ORDER BY mop.name
        LIMIT %(start)s, %(page_len)s
    """, {
        "company": company,
        "txt": "%" + txt + "%",
        "start": start,
        "page_len": page_len
    })
