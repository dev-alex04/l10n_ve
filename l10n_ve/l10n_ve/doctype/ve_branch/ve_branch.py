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

    def on_update(self) -> None:
        super().on_update()
        self.sync_user_permissions()
        self.propagate_users_to_children()

        if self.municipality:
            self.check_municipality_taxes()

    def sync_user_permissions(self) -> None:
        """Sincroniza (crea y elimina) permisos de usuario para esta sucursal."""
        current_users = set(row.user for row in self.get("users", []) if row.user)

        existing_permissions = frappe.get_all("User Permission", filters={
            "allow": "VE Branch",
            "for_value": self.name
        }, fields=["name", "user"])

        existing_user_map = {perm.user: perm.name for perm in existing_permissions}
        existing_user_names = set(existing_user_map.keys())

        users_to_add = current_users - existing_user_names
        for user in users_to_add:
            perm = frappe.new_doc("User Permission")
            perm.user = user
            perm.allow = "VE Branch"
            perm.for_value = self.name
            perm.insert(ignore_permissions=True)

        users_to_remove = existing_user_names - current_users
        for user in users_to_remove:
            frappe.delete_doc("User Permission", existing_user_map[user], ignore_permissions=True)

    def propagate_users_to_children(self) -> None:
        """Propaga adiciones y eliminaciones de usuarios a las sucursales hijas."""
        # Detectar cambios comparando con la versión anterior
        old_doc = self.get_doc_before_save()
        old_users = set()
        if old_doc:
            old_users = {row.user for row in old_doc.get("users", []) if row.user}

        new_users = {row.user for row in self.get("users", []) if row.user}

        users_to_add = new_users - old_users
        users_to_remove = old_users - new_users

        if not users_to_add and not users_to_remove:
            return

        children = frappe.get_all("VE Branch", filters={"parent_ve_branch": self.name}, pluck="name")
        if not children:
            return

        for child_name in children:
            child_doc = frappe.get_doc("VE Branch", child_name)
            child_users: set[str] = {row.user for row in child_doc.get("users", []) if row.user}
            modified: bool = False

            for user in users_to_add:
                if user not in child_users:
                    child_doc.append("users", {"user": user})
                    modified = True

            if users_to_remove:
                before_count: int = len(child_doc.users)
                child_doc.users = [row for row in child_doc.users if row.user not in users_to_remove]

                if len(child_doc.users) != before_count:
                    modified = True

            if modified:
                child_doc.save(ignore_permissions=True)

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
                "send_in_email": getattr(payment_row, "send_in_email", 0),
                "account": payment_row.account,
                "payment_information": payment_row.payment_information
            })

    @frappe.whitelist()
    def get_details_from_parent(self, parent_branch: str) -> dict:
        """Obtiene los detalles de la sucursal padre para heredarlos en el cliente."""
        if not parent_branch:
            return {}

        parent = frappe.get_cached_doc("VE Branch", parent_branch)

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
        """Valida que un usuario no esté duplicado dentro de la misma sucursal."""
        users: list[str] = [row.user for row in self.get("users", []) if row.user]
        if not users:
            return

        if len(users) != len(set(users)):
            seen: set[str] = set()
            for user in users:
                if user in seen:
                    frappe.throw(
                        _("El usuario {0} está asignado varias veces en esta sucursal.").format(
                            frappe.bold(user)
                        )
                    )
                seen.add(user)

    def get_default_payment_mode(self) -> _dict:
        """Obtiene el modo de pago predeterminado de la sucursal."""
        default_payment_mode = next(
            (row for row in self.get("mode_of_payments", []) if row.is_default),
            None
        )

        if not default_payment_mode:
            frappe.throw(
                _("La sucursal {0} no tiene un modo de pago predeterminado.").format(
                    frappe.bold(self.name)
                )
            )

        return _dict(default_payment_mode.as_dict())

    def check_municipality_taxes(self) -> None:
        """Verifica y crea impuestos municipales si no existen."""
        if not frappe.db.exists("VE Municipality Taxes", {"municipality": self.municipality}):
            frappe.enqueue(
                method='l10n_ve.setup.create_municipality_taxes_for_municipality',
                queue='long',
                timeout=600,
                municipality_doc_name=self.municipality
            )


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
