# -*- coding: utf-8 -*-
import frappe
from typing import List, Dict, Union, Any

def is_admin_user(user: str) -> bool:
    """
    Retorna True si el usuario es Administrator o cuenta con el rol 'System Manager'.

    OJO: esta función gobierna el sistema de permisos por sucursal COMPLETO
    --`get_allowed_branches`, `get_ve_branch_permission_query` y
    `has_ve_branch_permission`--, no una pantalla en particular. Sumarle un rol acá le
    da lectura cross-sucursal sobre todo lo restringido por VE Branch: facturas, pagos,
    clientes. Si un reporte necesita ver todas las sucursales, la excepción va en ese
    reporte, no acá.
    """
    if user == "Administrator":
        return True
    return "System Manager" in frappe.get_roles(user)


#: Roles autorizados a registrar comprobantes de retención en un período fiscal
#: ya cerrado.
#:
#: Es la excepción al candado de quincenas: una vez declarado el período, la fecha
#: del comprobante no debería moverse porque arrastra la retención a otro Libro de
#: Ventas. Contabilidad sí necesita poder corregir a mano, así que estos roles
#: saltan la validación.
ACCOUNTING_ROLES = frozenset({
    "Accounts Manager",
    "Accounts User",
    "Administrador Contable",
    "Auxiliar Contable",
    "ISP Finance",
    "ISP Finance Pro",
    "VE Sales Book HQ",
    "System Manager",
})


def has_accounting_permission(user: str = None) -> bool:
    """Retorna True si el usuario puede operar sobre períodos fiscales cerrados."""
    user = user or frappe.session.user
    if user == "Administrator":
        return True
    return bool(ACCOUNTING_ROLES.intersection(frappe.get_roles(user)))


def get_allowed_branches(user: str = None, include_ancestors: bool = False) -> List[str]:
    """Retorna la lista de sucursales permitidas para el usuario.

    Incluye siempre los descendientes (vía lft/rgt) de cada sucursal asignada
    en User Permission. Si include_ancestors=True, también devuelve los
    ancestros de cada sucursal asignada — necesario para renderizar la vista
    de árbol de VE Branch con el path completo. En cualquier otro contexto
    debe usarse include_ancestors=False para no exponer ramas no permitidas.

    Usa la caché de Redis para responder sin consultar la base de datos.
    En developer_mode no se escribe ni se lee caché.
    """
    if not user:
        user = frappe.session.user

    if is_admin_user(user):
        all_branches = frappe.cache().get_value("all_ve_branches")
        if all_branches is None:
            all_branches = frappe.get_all("VE Branch", pluck="name")
            frappe.cache().set_value("all_ve_branches", all_branches)
        return all_branches

    use_cache: bool = not frappe.conf.get("developer_mode")
    cache_key: str = f"allowed_ve_branches:{user}:{'1' if include_ancestors else '0'}"
    if use_cache:
        allowed: Union[List[str], None] = frappe.cache().get_value(cache_key)
        if allowed is not None:
            return allowed

    # Consultar base de datos si no esta en cache
    direct_branches: List[str] = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "VE Branch"},
        pluck="for_value"
    )

    if not direct_branches:
        if use_cache:
            frappe.cache().set_value(cache_key, [])
        return []

    # Obtener limites jerarquicos de las sucursales asignadas (Nested Set: lft, rgt)
    branch_limits: List[Dict[str, int]] = frappe.db.sql("""
        SELECT name, lft, rgt FROM `tabVE Branch`
        WHERE name IN %(branches)s
    """, {"branches": tuple(direct_branches)}, as_dict=True)

    if not branch_limits:
        if use_cache:
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

    if use_cache:
        frappe.cache().set_value(cache_key, all_allowed)
    return all_allowed

def _is_ve_branch_tree_context() -> bool:
    """True si la consulta proviene de la vista de árbol de VE Branch.

    Diferencia entre contextos donde se necesitan ancestros (vista de árbol) y
    contextos donde solo deben verse sucursales con permiso explícito (Link
    dropdowns, list view, etc).

    Se valida tanto `form_dict.cmd` como `request.path` para evitar que un
    cliente malicioso force el modo árbol con `?cmd=...` sobre otro endpoint.
    En developer_mode se emite un log cuando una consulta sobre VE Branch no
    matchea ningún patrón conocido, para detectar cambios entre versiones de
    Frappe (el endpoint exacto de carga inicial del árbol ha variado).
    """
    # Señal PRIMARIA y robusta: la marca el propio método del árbol
    # (get_ve_branch_tree_children) vía frappe.flags, sin depender del cmd/path
    # del request — que varía entre versiones de Frappe y rompía el árbol. Los
    # patrones de sniffing de abajo quedan solo como respaldo.
    if frappe.flags.get("in_ve_branch_tree"):
        return True

    form_dict = getattr(frappe.local, "form_dict", None) or {}
    cmd: str = (form_dict.get("cmd") or "").lower()
    doctype: str = form_dict.get("doctype") or ""

    request = getattr(frappe.local, "request", None)
    path: str = (getattr(request, "path", "") or "").lower()

    # Patrón 1: expansión de nodos vía treeview.get_children. Validamos cmd y path
    # para descartar spoofing de cmd contra otro endpoint.
    if (
        "treeview.get_children" in cmd
        and doctype == "VE Branch"
        and "treeview" in path
    ):
        return True

    # Patrón 2: carga inicial del árbol vía get_list con filtros propios del árbol.
    # El filtro is_root/parent_ve_branch ya es suficientemente específico — no
    # exigimos coincidencia de path para no romper si Frappe cambia el endpoint.
    if cmd == "frappe.client.get_list" and doctype == "VE Branch":
        filters: str = str(form_dict.get("filters") or "")
        if "is_root" in filters or "parent_ve_branch" in filters:
            return True

    # Diagnóstico para developer_mode: si la consulta es sobre VE Branch y no
    # matcheamos ningún patrón conocido, dejar rastro para revisar.
    if doctype == "VE Branch" and frappe.conf.get("developer_mode"):
        frappe.logger("l10n_ve.permissions").debug(
            f"_is_ve_branch_tree_context: unmatched VE Branch query "
            f"cmd={cmd!r} path={path!r} filters={form_dict.get('filters')!r}"
        )

    return False


@frappe.whitelist()
def get_ve_branch_tree_children(doctype, parent="", **filters):
    """get_children del árbol de VE Branch, marcando el contexto de forma EXPLÍCITA.

    Es el `get_tree_nodes` del treeview de VE Branch (ve_branch_tree.js). Pone
    frappe.flags.in_ve_branch_tree para que get_ve_branch_permission_query
    incluya los ancestros de las sucursales permitidas y el árbol pinte el path
    completo (raíz → ... → sucursal del usuario). No depende del cmd/path del
    request, que varía entre versiones de Frappe y dejaba el árbol vacío.

    Fuera del árbol el permission query sigue estricto (dropdowns, list view),
    y has_ve_branch_permission sigue bloqueando abrir un ancestro no permitido:
    los ancestros solo se exponen como nodos de navegación, no como acceso real.
    """
    from frappe.desk.treeview import get_children

    frappe.flags.in_ve_branch_tree = True
    try:
        return get_children(doctype, parent, **filters)
    finally:
        frappe.flags.in_ve_branch_tree = False


def get_ve_branch_permission_query(user: str, doctype: str = None) -> str:
    """
    Funcion principal de intercepcion de consultas SQL para el hook de Frappe.
    Frappe le pasa el doctype de forma nativa como argumento clave-valor (doctype=self.doctype).
    """
    if not doctype:
        return ""

    if not user:
        user = frappe.session.user

    if is_admin_user(user):
        return ""

    # Solo se incluyen ancestros cuando se está pintando la vista de árbol de VE Branch.
    # En cualquier otro contexto (dropdown, list view), el filtro es estricto.
    include_ancestors: bool = doctype == "VE Branch" and _is_ve_branch_tree_context()
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

    # Estricto: si el usuario intenta abrir un ancestro al que no tiene permiso
    # explícito, debe ser bloqueado aunque la vista de árbol lo muestre.
    allowed: List[str] = get_allowed_branches(user, include_ancestors=False)
    if not allowed:
        return False

    # Permitir inicialización y creación general si el usuario tiene sucursales asignadas.
    # La validación estricta de la sucursal específica se ejecutará al guardar (save/write).
    #
    # Un documento aún NO guardado entra en el mismo caso que un `create`: todavía no
    # tiene sucursal, así que compararlo contra `allowed` lo rechazaba siempre. Frappe
    # evalúa el permiso sobre un documento en blanco cuando se adjunta un archivo antes
    # del primer guardado (`frappe.handler.check_write_permission`), y eso dejaba a los
    # usuarios con sucursal asignada sin poder adjuntar nada en documentos nuevos. El
    # guardado sí valida la sucursal real, así que no se relaja ninguna restricción.
    if ptype in ("create", "select") or doc.is_new():
        return len(allowed) > 0
        
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
        
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return []

    if meta.issingle:
        frappe.cache().set_value(cache_key, [])
        return []
        
    all_fields = [df.fieldname for df in meta.get("fields") if df.fieldtype == "Link" and df.options == "VE Branch"]
    
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

