import frappe


def execute():
    """Evita que la restriccion del Reporte Gerencial deje al reporte sin dueno.

    El JSON del DocType pasó a declarar un solo rol —`Executive Reporting Manager`—
    en el commit ffcab25c del 14-ago. Como `tabDocPerm` se deriva del JSON, la
    sincronizacion de DocTypes de cada `bench migrate` se lleva puestas las filas
    viejas (System Manager, Accounts User, Accounts Manager). Medido en produccion,
    esas tres eran las unicas que daban acceso, y el rol nuevo no lo tenia NADIE:
    el resultado es un reporte que no puede abrir ni un System Manager.

    Este patch corre una sola vez y cierra ese hueco. Lo que NO hace es imponer los
    permisos por SQL: de eso ya se encarga el JSON.
    """
    if not frappe.db.exists("DocType", "Reporte Gerencial"):
        return

    ROL = "Executive Reporting Manager"

    # `create_custom_roles` ya lo crea en after_migrate, pero este patch corre antes
    # que los hooks y no puede depender de ese orden.
    if not frappe.db.exists("Role", ROL):
        frappe.get_doc({
            "doctype": "Role", "role_name": ROL, "desk_access": 1,
        }).insert(ignore_permissions=True)

    # Un Custom DocPerm PISA al DocPerm del JSON, asi que una fila heredada aca
    # anularia la restriccion entera. Se limpian por ORM y no por SQL, para que la
    # invalidacion de cache y los hooks corran como corresponde.
    heredados = frappe.get_all(
        "Custom DocPerm", filters={"parent": "Reporte Gerencial"}, pluck="name"
    )
    for nombre in heredados:
        frappe.delete_doc("Custom DocPerm", nombre, ignore_permissions=True, force=True)
    if heredados:
        print(f"  Reporte Gerencial: {len(heredados)} Custom DocPerm heredado(s) eliminado(s)")

    # Si ya hay alguien con el rol, la decision de a quien darselo esta tomada y no
    # se toca.
    con_rol = frappe.db.count("Has Role", {"role": ROL})
    if con_rol:
        print(f"  Reporte Gerencial: {con_rol} usuario(s) ya tienen '{ROL}', sin cambios")
        frappe.clear_cache(doctype="Reporte Gerencial")
        return

    # Nadie lo tiene: se le asigna a los System Manager activos. No es una concesion
    # de privilegios —un System Manager puede asignarse cualquier rol por su cuenta—,
    # es evitar que el deploy deje el reporte inaccesible hasta que alguien se acuerde.
    # Que el acceso definitivo sea mas angosto es una decision de negocio: se quita el
    # rol a quien no corresponda desde el Gestor de Roles.
    admins = frappe.get_all(
        "Has Role", filters={"role": "System Manager"}, pluck="parent", distinct=True
    )
    asignados = 0
    for usuario in admins:
        if usuario in ("Administrator", "Guest"):
            continue
        if not frappe.db.get_value("User", usuario, "enabled"):
            continue
        doc = frappe.get_doc("User", usuario)
        doc.append("roles", {"role": ROL})
        doc.save(ignore_permissions=True)
        asignados += 1

    print(
        f"  Reporte Gerencial: '{ROL}' asignado a {asignados} System Manager(s) activo(s) "
        "para no dejar el reporte sin acceso. Ajustar desde el Gestor de Roles."
    )
    frappe.clear_cache(doctype="Reporte Gerencial")
