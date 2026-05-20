# -*- coding: utf-8 -*-
import frappe
from typing import List, Dict, Union, Any

def is_admin_user(user: str) -> bool:
    """
    Retorna True si el usuario es Administrator o cuenta con el rol 'System Manager'.
    """
    if user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(user)

def get_allowed_branches(user: str = None, include_ancestors: bool = False) -> List[str]:
    """
    Retorna la lista expandida de sucursales (con hijas) para el usuario.
    Usa la cache de Redis para responder inmediatamente sin consultar la base de datos.
    """
    if not user:
        user = frappe.session.user
        
    if is_admin_user(user):
        all_branches = frappe.cache().get_value("all_ve_branches")
        if all_branches is None:
            all_branches = frappe.get_all("VE Branch", pluck="name")
            frappe.cache().set_value("all_ve_branches", all_branches)
        return all_branches
        
    cache_key: str = f"allowed_ve_branches:{user}:{'1' if include_ancestors else '0'}"
    allowed: Union[List[str], None] = None
    if not frappe.conf.get("developer_mode"):
        allowed = frappe.cache().get_value(cache_key)
        
    if allowed is not None:
        return allowed
        
    # Consultar base de datos si no esta en cache
    direct_branches: List[str] = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "VE Branch"},
        pluck="for_value"
    )
    
    if not direct_branches:
        frappe.cache().set_value(cache_key, [])
        return []
        
    # Obtener limites jerarquicos de las sucursales asignadas (Nested Set: lft, rgt)
    branch_limits: List[Dict[str, int]] = frappe.db.sql("""
        SELECT name, lft, rgt FROM `tabVE Branch`
        WHERE name IN %(branches)s
    """, {"branches": tuple(direct_branches)}, as_dict=True)
    
    if not branch_limits:
        frappe.cache().set_value(cache_key, [])
        return []
        
    or_conditions: List[str] = []
    query_args: Dict[str, int] = {}
    
    for i, branch in enumerate(branch_limits):
        lft_key: str = f"lft_{i}"
        rgt_key: str = f"rgt_{i}"
        or_conditions.append(f"(lft >= %({lft_key})s AND rgt <= %({rgt_key})s)")
        query_args[lft_key] = branch["lft"]
        query_args[rgt_key] = branch["rgt"]
        
        if include_ancestors:
            lft_anc_key: str = f"lft_anc_{i}"
            rgt_anc_key: str = f"rgt_anc_{i}"
            or_conditions.append(f"(lft < %({lft_anc_key})s AND rgt > %({rgt_anc_key})s)")
            query_args[lft_anc_key] = branch["lft"]
            query_args[rgt_anc_key] = branch["rgt"]
        
    where_clause: str = " OR ".join(or_conditions)
    
    all_allowed: List[str] = frappe.db.sql(f"""
        SELECT name FROM `tabVE Branch`
        WHERE {where_clause}
    """, query_args, pluck="name")
    
    frappe.cache().set_value(cache_key, all_allowed)
    return all_allowed

def get_ve_branch_permission_query(user: str, doctype: str = None) -> str:
    """
    Funcion principal de intercepcion de consultas SQL para el hook de Frappe.
    Frappe le pasa el doctype de forma nativa como argumento clave-valor (doctype=self.doctype).
    """
    if not doctype:
        # Detectar doctype desde el stack de ejecucion
        import inspect
        frame = inspect.currentframe()
        while frame:
            if 'self' in frame.f_locals and frame.f_locals['self'].__class__.__name__ == 'DatabaseQuery':
                doctype = frame.f_locals['self'].doctype
                break
            frame = frame.f_back
            
    if not doctype:
        return ""
        
    if not user:
        user = frappe.session.user
        
    if is_admin_user(user):
        return ""
        
    include_ancestors: bool = doctype == "VE Branch"
    allowed: List[str] = get_allowed_branches(user, include_ancestors=include_ancestors)
    
    if not allowed:
        return "1 = 0"
        
    # Caso especial: El DocType consultado es VE Branch mismo
    if doctype == "VE Branch":
        escaped_branches: str = ", ".join([frappe.db.escape(b) for b in allowed])
        return f"`tabVE Branch`.name IN ({escaped_branches})"
        
    # Otros DocTypes: buscar campos Link que apunten a VE Branch
    branch_fields: List[str] = _get_branch_fields_for_doctype(doctype)
    if not branch_fields:
        return ""
        
    escaped_branches = ", ".join([frappe.db.escape(b) for b in allowed])
    conditions: List[str] = []
    for field in branch_fields:
        conditions.append(f"`tab{doctype}`.{field} IN ({escaped_branches})")
        
    return " OR ".join(conditions)

def has_ve_branch_permission(doc: Any, ptype: str = "read", user: str = None) -> bool:
    """
    Valida permisos a nivel de documento individual (has_permission hook).
    Previene accesos no autorizados a documentos especificos.
    """
    if not user:
        user = frappe.session.user
        
    if is_admin_user(user):
        return True
        
    include_ancestors: bool = doc.doctype == "VE Branch"
    allowed: List[str] = get_allowed_branches(user, include_ancestors=include_ancestors)
    if not allowed:
        return False
        
    # Caso especial: El documento es VE Branch mismo
    if doc.doctype == "VE Branch":
        return doc.name in allowed
        
    # Caso especial: Si el DocType es de tipo 'Single' (ej. ISP Control Dashboard),
    # permitimos el acceso a la pantalla siempre y cuando el usuario tenga al menos una sucursal permitida.
    if frappe.get_meta(doc.doctype).issingle:
        return len(allowed) > 0
        
    # Otros DocTypes: verificar si sus campos de branch apuntan a una sucursal permitida
    branch_fields: List[str] = _get_branch_fields_for_doctype(doc.doctype)
    if not branch_fields:
        return True
        
    for field in branch_fields:
        val = doc.get(field)
        if val and val in allowed:
            return True
            
    return False

def _get_branch_fields_for_doctype(doctype: str) -> List[str]:
    """
    Obtiene los nombres de los campos de tipo Link que apuntan a 'VE Branch' para un DocType.
    Usa la cache de Redis para evitar consultas recurrentes de metadatos.
    """
    cache_key: str = f"ve_branch_fields:{doctype}"
    
    cached_fields: Union[List[str], None] = frappe.cache().get_value(cache_key)
    if cached_fields is not None:
        return cached_fields
        
    # Consultar campos estandar
    fields: List[str] = frappe.get_all(
        "DocField",
        filters={"parent": doctype, "fieldtype": "Link", "options": "VE Branch"},
        pluck="fieldname"
    )
    
    # Consultar campos personalizados (Custom Field)
    custom_fields: List[str] = frappe.get_all(
        "Custom Field",
        filters={"dt": doctype, "fieldtype": "Link", "options": "VE Branch"},
        pluck="fieldname"
    )
    
    all_fields: List[str] = list(set(fields + custom_fields))
    frappe.cache().set_value(cache_key, all_fields)
    return all_fields

def clear_ve_branch_cache(doc: Any, method: str = None) -> None:
    """
    Limpia la cache de Redis cuando cambian los permisos o el arbol de sucursales.
    """
    if doc.doctype == "User Permission" and doc.allow == "VE Branch":
        # Invalidar la cache especifica del usuario
        frappe.cache().delete_value(f"allowed_ve_branches:{doc.user}:0")
        frappe.cache().delete_value(f"allowed_ve_branches:{doc.user}:1")
        
    elif doc.doctype == "VE Branch":
        # Invalidar toda la cache del arbol de sucursales
        frappe.cache().delete_keys("allowed_ve_branches:*")
        frappe.cache().delete_value("all_ve_branches")
        frappe.cache().delete_keys("ve_branch_fields:*")

