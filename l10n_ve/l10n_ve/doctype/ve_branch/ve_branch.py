# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class VEBranch(NestedSet):

    def validate(self) -> None:
        self.validate_unique_users()

    def validate_unique_users(self) -> None:
        """Valida que un usuario no esté asignado a más de una sucursal."""
        for row in self.get("users", []):
            existing = frappe.db.get_value(
                "VE Branch Users",
                {
                    "user": row.user,
                    "parent": ["!=", self.name],
                    "parenttype": "VE Branch"
                },
                ["parent"],
                as_dict=True
            )

            if existing:
                frappe.throw(
                    _("El usuario {0} ya está asignado a la sucursal {1}").format(
                        frappe.bold(row.user),
                        frappe.bold(existing.parent)
                    )
                )
