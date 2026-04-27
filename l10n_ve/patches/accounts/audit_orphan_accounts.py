"""Script de auditoría: busca TODAS las referencias huérfanas a Account en la BD.

Recorre dinámicamente todos los campos Link→Account del schema y verifica
que los valores apunten a cuentas existentes.

Uso:
    bench --site domina.galanet execute l10n_ve.patches.accounts.audit_orphan_accounts
"""
import frappe


def execute() -> None:
    """Audita todas las tablas buscando referencias a cuentas inexistentes."""

    company: str = "Galanet Solution C.A."

    # Obtener todos los campos Link→Account del schema
    link_fields: list[dict] = frappe.db.sql("""
        SELECT parent as doctype_name, fieldname
        FROM `tabDocField`
        WHERE fieldtype = 'Link' AND options = 'Account'
        UNION
        SELECT dt as doctype_name, fieldname
        FROM `tabCustom Field`
        WHERE fieldtype = 'Link' AND options = 'Account'
        ORDER BY 1, 2
    """, as_dict=True)

    print(f"Auditando {len(link_fields)} campos Link→Account...")
    print("=" * 80)

    total_orphans: int = 0
    checked: int = 0

    for field in link_fields:
        dt: str = field["doctype_name"]
        fn: str = field["fieldname"]
        table_name: str = f"tab{dt}"

        # Verificar que la tabla existe
        if not frappe.db.sql(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
            table_name
        ):
            continue

        # Verificar que la columna existe
        if not frappe.db.sql(
            "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s "
            "AND COLUMN_NAME = %s",
            (table_name, fn)
        ):
            continue

        checked += 1

        # Buscar valores huérfanos
        orphans: list[dict] = frappe.db.sql(f"""
            SELECT t.name, t.`{fn}` as orphan_value
            FROM `{table_name}` t
            WHERE IFNULL(t.`{fn}`, '') != ''
            AND t.`{fn}` NOT IN (SELECT name FROM `tabAccount`)
            LIMIT 10
        """, as_dict=True)

        if orphans:
            total_orphans += len(orphans)
            print(f"\n🔴 {dt}.{fn} — {len(orphans)} referencia(s) huérfana(s):")
            for o in orphans:
                print(f"   doc: {o['name'][:50]}  →  {o['orphan_value']}")

    print("\n" + "=" * 80)
    print(f"Campos verificados: {checked}")
    print(f"Referencias huérfanas encontradas: {total_orphans}")

    if total_orphans == 0:
        print("🎉 No se encontraron referencias huérfanas a cuentas contables")
    else:
        print("⚠ Corregir las referencias listadas arriba")

    print("=" * 80)
