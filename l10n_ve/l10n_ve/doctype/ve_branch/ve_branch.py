# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class VEBranch(NestedSet):

    def validate(self) -> None:
        self.validate_unique_users()

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

        user_to_branch_map = {d["user"]: d["parent"] for d in existing_assignments}
        for user in users:
            if user in user_to_branch_map:
                frappe.throw(
                    _("El usuario {0} ya está asignado a la sucursal {1}").format(
                        frappe.bold(user), frappe.bold(user_to_branch_map[user])
                    )
                )
