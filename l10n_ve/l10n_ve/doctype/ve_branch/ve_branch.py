# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _, _dict
from frappe.utils.nestedset import NestedSet


class VEBranch(NestedSet):

    def validate(self) -> None:
        self.validate_unique_users()
        self.validate_payment_modes()

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

        user_to_branch_map = {d["user"]: d["parent"] for d in existing_assignments}
        for user in users:
            if user in user_to_branch_map:
                frappe.throw(
                    _("El usuario {0} ya está asignado a la sucursal {1}").format(
                        frappe.bold(user), frappe.bold(user_to_branch_map[user])
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
