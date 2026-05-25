# -*- coding: utf-8 -*-
import frappe
import frappe.permissions
import frappe.core.doctype.user_permission.user_permission as up_module
from typing import Dict, List, Any, Union

def apply():
    """
    Aplica el monkeypatch para interceptar get_user_permissions.
    """
    # Guardar referencia al original de la fuente real (el doctype controller module)
    original_get_user_permissions = up_module.get_user_permissions
    
    def custom_get_user_permissions(user: str = None) -> Dict[str, List[Dict[str, Any]]]:
        if not user:
            user = frappe.session.user
            
        # Usar la función original sin parches para evitar bucles infinitos
        original_perms = original_get_user_permissions(user)
        
        # Administrator y System Manager no tienen restricciones
        if user == "Administrator" or "System Manager" in frappe.get_roles(user):
            return original_perms
            
        # Hacer una copia superficial para evitar mutar el objeto en caché en memoria directamente
        user_permissions: Dict[str, List[Dict[str, Any]]] = dict(original_perms) if original_perms else {}

        # Incluir ancestros siempre para que los selectores Link de VE Branch muestren
        # la jerarquía completa. El filtrado real por DocType lo maneja
        # permission_query_conditions en permissions.py.
        from l10n_ve.permissions import get_allowed_branches
        allowed: List[str] = get_allowed_branches(user, include_ancestors=True)

        if allowed:
            new_ve_branch_perms = [{"doc": branch, "applicable_for": None} for branch in allowed]
            user_permissions["VE Branch"] = new_ve_branch_perms

        return user_permissions

    # Reemplazar en ambos lugares para interceptar cualquier tipo de importación
    up_module.get_user_permissions = custom_get_user_permissions
    frappe.permissions.get_user_permissions = custom_get_user_permissions

# Aplicar el parche inmediatamente al importar este modulo
apply()
