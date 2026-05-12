"""Script de auditoría: busca TODAS las referencias huérfanas a Account en la BD.

Recorre dinámicamente todos los campos Link→Account del schema y verifica
que los valores apunten a cuentas existentes.

Uso:
    bench --site domina.galanet execute l10n_ve.patches.accounts.audit_orphan_accounts.execute
"""
import re

import frappe


# Patrón para validar identificadores SQL seguros (letras, números, espacios, guiones)
_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_ ]+$")


def _is_safe_identifier(value: str) -> bool:
    """Valida que un identificador SQL no contenga caracteres peligrosos."""
    return bool(_SAFE_IDENTIFIER.match(value))


def execute() -> None:
    """Audita todas las tablas buscando referencias a cuentas inexistentes."""

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

        # Validar identificadores contra inyección SQL
        if not _is_safe_identifier(dt) or not _is_safe_identifier(fn):
            print(f"  ⚠ Identificador no seguro omitido: {dt}.{fn}")
            continue

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

        # Conteo real de huérfanos (sin LIMIT)
        orphan_count: int = frappe.db.sql(f"""
            SELECT COUNT(*) FROM `{table_name}` t
            WHERE IFNULL(t.`{fn}`, '') != ''
            AND t.`{fn}` NOT IN (SELECT name FROM `tabAccount`)
        """)[0][0]

        if orphan_count == 0:
            continue

        total_orphans += orphan_count

        # Mostrar solo los primeros 5 ejemplos para legibilidad
        examples: list[dict] = frappe.db.sql(f"""
            SELECT t.name, t.`{fn}` as orphan_value
            FROM `{table_name}` t
            WHERE IFNULL(t.`{fn}`, '') != ''
            AND t.`{fn}` NOT IN (SELECT name FROM `tabAccount`)
            LIMIT 5
        """, as_dict=True)

        suffix: str = f" (mostrando 5 de {orphan_count})" if orphan_count > 5 else ""
        print(f"\n🔴 {dt}.{fn} — {orphan_count} referencia(s) huérfana(s){suffix}:")
        for o in examples:
            print(f"   doc: {o['name'][:50]}  →  {o['orphan_value']}")

    print("\n" + "=" * 80)
    print(f"Campos verificados: {checked}")
    print(f"Referencias huérfanas encontradas: {total_orphans}")

    if total_orphans == 0:
        print("🎉 No se encontraron referencias huérfanas a cuentas contables")
    else:
        print("⚠ Corregir las referencias listadas arriba")

    print("=" * 80)
