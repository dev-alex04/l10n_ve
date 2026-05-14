"""
Patch: Sanitización y corrección de nombres de Customers.

Fase 1: Corrige espacios (leading/trailing/dobles) en name y customer_name.
Fase 2: Renombra Customers con IDs incorrectos (duplicados -1, IDs numéricos,
        case sensitivity) a su nombre correcto.

Usa frappe.rename_doc() para renombrar el Customer.name (PK),
lo cual actualiza automáticamente todos los campos Link que
apuntan al Customer (Sales Invoice.customer, GL Entry.party, etc.).

Ejecución:
    bench --site domina.galanet migrate
    -- o manualmente:
    bench --site domina.galanet execute l10n_ve.patches.sanitize_customer_names.execute
"""
import re

import frappe


def _clean_name(name: str) -> str:
    """Elimina espacios leading/trailing y colapsa dobles espacios internos."""
    cleaned: str = name.strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned


# Renames manuales: (old_name, new_name)
# Cada caso fue verificado individualmente con diagnóstico SQL.
# HKA usa customer_name (no el ID), así que el rename de la PK es seguro.
MANUAL_RENAMES: list[tuple[str, str]] = [
    # Caso 1: Duplicado -1 reutilizado para otra persona.
    #         customer_name ya es SONIA, tax_id ya es V20411880.
    #         La EMERILIS original (sin -1) sigue existiendo.
    (
        "EMERILIS JOSEFINA GARCIA DE BELEÑO - 1",
        "SONIA MARGARITA RAMOS QUIÑONEZ",
    ),
    # Caso 2: Duplicado -1 cuyo original no existe.
    #         customer_name ya es correcto.
    (
        "WILLIAM FRANCISCO CASTRO ZIEGLER - 1",
        "WILLIAM FRANCISCO CASTRO ZIEGLER",
    ),
    # Caso 3: ID numérico basura (error de importación).
    #         customer_name ya es FERMIN ENRIQUE DIAZ MUJICA.
    (
        "12995,1",
        "FERMIN ENRIQUE DIAZ MUJICA",
    ),
    # Caso 4: ID con case mixto (minúsculas en apellido).
    #         customer_name ya es ERMELY JOSEFINA MORALES VARGAS (correcto).
    (
        "Ermely Josefina morales Vargas",
        "ERMELY JOSEFINA MORALES VARGAS",
    ),
    # Caso 5: Typo en PK — falta la "S" inicial.
    (
        "INAI GABRIELA PIÑATE RAMIREZ",
        "SINAI GABRIELA PIÑATE RAMIREZ",
    ),
    # Caso 6: Typo en PK — "S" por "Z" y "N" por "R".
    (
        "SOYUMA LEONON BAQUEDANO DE WU",
        "ZOYUMA LEONOR BAQUEDANO DE WU",
    ),
    # Caso 7: Typo en PK — falta la "N" en PADRON.
    (
        "NANCY DEL VALLE PADRO DE CADENAS",
        "NANCY DEL VALLE PADRON DE CADENAS",
    ),
    # Caso 8: PK duplicada (nombre pegado dos veces).
    (
        "FRANCISCO FELIPE DE LA CRUZ GONZALEZFRANCISCO FELIPE DE LA CRUZ GONZALEZ",
        "FRANCISCO FELIPE DE LA CRUZ GONZALEZ",
    ),
    # Caso 9: PK con sufijo basura (nombre de organismo en paréntesis).
    (
        "NAIBELIN BERLATIS MARTINEZ MORALES (TELEMATICA DE LA GOBERNACIONO DE MIRANDA )",
        "NAIBELIN BERLATIS MARTINEZ MORALES",
    ),
    # Caso 10: Registro reutilizado para otra entidad (0 facturas).
    (
        "PAOLA KAROLY ARTAHONA",
        "GOBERNACION BOLIVARIANA DE MIRANDA",
    ),
]


def execute() -> None:
    """Punto de entrada del patch."""
    _fix_spaces()
    _fix_manual_renames()
    _fix_contact_links()

    # Fase 4: Reconciliar facturas con respuesta HKA exitosa
    # pero bill_no/bill_control vacíos.
    from l10n_ve.digital_invoice.reconciliation import reconcile_hka_fiscal_fields

    print("=" * 80)
    print("📋 Fase 4: Reconciliación HKA (bill_no / bill_control).")
    print("=" * 80)
    reconcile_hka_fiscal_fields()
    print("✅ Fase 4 completada.")


def _fix_spaces() -> None:
    """Fase 1: Corrige espacios en name y customer_name."""

    customers_with_issues: list[dict] = frappe.db.sql("""
        SELECT
            c.name,
            c.customer_name
        FROM `tabCustomer` c
        WHERE c.name != TRIM(c.name)
           OR c.name LIKE '%%  %%'
           OR c.customer_name != TRIM(c.customer_name)
           OR c.customer_name LIKE '%%  %%'
        ORDER BY c.name
    """, as_dict=True)

    if not customers_with_issues:
        print("✅ Fase 1 (espacios): No se encontraron Customers con problemas.")
        return

    print(f"📋 Fase 1: {len(customers_with_issues)} Customers con espacios.")
    print("=" * 80)

    renamed_count: int = 0
    updated_count: int = 0
    skipped: list[str] = []

    for cust in customers_with_issues:
        old_name: str = cust["name"]
        old_customer_name: str = cust["customer_name"]
        new_name: str = _clean_name(old_name)
        new_customer_name: str = _clean_name(old_customer_name)

        if new_name != old_name and frappe.db.exists("Customer", new_name):
            skipped.append(
                f"  ⛔ \"{old_name}\" → \"{new_name}\" YA EXISTE. "
                f"Requiere merge manual."
            )
            continue

        try:
            if new_name != old_name:
                frappe.rename_doc(
                    "Customer", old_name, new_name,
                    merge=False, force=True,
                )
                renamed_count += 1
                print(f"  🔄 Rename: \"{old_name}\" → \"{new_name}\"")

            if new_customer_name != old_customer_name:
                frappe.db.set_value(
                    "Customer", new_name, "customer_name",
                    new_customer_name, update_modified=False,
                )
                updated_count += 1
                print(f"  ✏️  customer_name: \"{old_customer_name}\" → "
                      f"\"{new_customer_name}\"")

            _update_customer_name_snapshots(
                customer=new_name,
                old_customer_name=old_customer_name,
                new_customer_name=new_customer_name,
                old_pk=old_name,
            )

        except Exception as e:
            skipped.append(f"  ❌ Error con \"{old_name}\": {str(e)}")
            frappe.log_error(
                frappe.get_traceback(),
                f"Sanitize Customer: {old_name}"
            )

    frappe.db.commit()

    print()
    print(f"  Renombrados: {renamed_count} | Actualizados: {updated_count} "
          f"| Omitidos: {len(skipped)}")
    if skipped:
        print("  ⚠️  Casos omitidos:")
        for s in skipped:
            print(s)
    print()


def _fix_manual_renames() -> None:
    """Fase 2: Renames manuales de Customers con IDs incorrectos."""

    print("=" * 80)
    print(f"📋 Fase 2: {len(MANUAL_RENAMES)} renames manuales.")
    print("=" * 80)

    done: int = 0
    skipped: list[str] = []

    for old_name, new_name in MANUAL_RENAMES:
        if not frappe.db.exists("Customer", old_name):
            skipped.append(f"  ⏭️  \"{old_name}\" no existe (ya corregido).")
            continue

        # MariaDB usa collation case-insensitive: frappe.db.exists
        # retorna True si el mismo registro tiene case diferente.
        # Solo bloqueamos si es un Customer DIFERENTE (case-sensitive).
        if old_name != new_name and frappe.db.exists("Customer", new_name):
            is_same_record: bool = old_name.lower() == new_name.lower()
            if not is_same_record:
                skipped.append(
                    f"  ⛔ \"{old_name}\" → \"{new_name}\" YA EXISTE. "
                    f"Requiere merge manual."
                )
                continue

        try:
            # Capturar customer_name actual antes del rename
            old_customer_name: str = frappe.db.get_value(
                "Customer", old_name, "customer_name"
            ) or old_name

            is_case_only: bool = old_name.lower() == new_name.lower()
            if is_case_only:
                # Case-only rename: frappe.rename_doc falla por bug de
                # collation case-insensitive en validate_rename.
                # Workaround: double-rename con nombre temporal para que
                # rename_doc actualice todos los Link fields automáticamente.
                temp_name: str = f"{old_name}__temp_rename"
                frappe.rename_doc(
                    "Customer", old_name, temp_name,
                    merge=False, force=True,
                )
                frappe.rename_doc(
                    "Customer", temp_name, new_name,
                    merge=False, force=True,
                )
            else:
                frappe.rename_doc(
                    "Customer", old_name, new_name,
                    merge=False, force=True,
                )
            print(f"  🔄 Rename PK: \"{old_name}\" → \"{new_name}\"")

            # Sincronizar customer_name si difiere del nuevo name
            current_customer_name: str = frappe.db.get_value(
                "Customer", new_name, "customer_name"
            ) or ""
            if current_customer_name != new_name:
                frappe.db.set_value(
                    "Customer", new_name, "customer_name",
                    new_name, update_modified=False,
                )
                print(f"  ✏️  customer_name: \"{current_customer_name}\" → "
                      f"\"{new_name}\"")

            # Siempre actualizar snapshots (GL against, customer_name en SI/NC/ND)
            _update_customer_name_snapshots(
                customer=new_name,
                old_customer_name=old_customer_name,
                new_customer_name=new_name,
                old_pk=old_name,
            )

            done += 1

        except Exception as e:
            skipped.append(f"  ❌ Error con \"{old_name}\": {str(e)}")
            frappe.log_error(
                frappe.get_traceback(),
                f"Manual Rename Customer: {old_name}"
            )

    frappe.db.commit()

    print()
    print(f"  Completados: {done} | Omitidos: {len(skipped)}")
    if skipped:
        print("  ⚠️  Casos omitidos:")
        for s in skipped:
            print(s)
    print()


def _fix_contact_links() -> None:
    """Fase 3: Corrige Dynamic Links y Contacts huérfanos post-rename.

    frappe.rename_doc no siempre actualiza los Dynamic Links dentro
    de Contacts, dejándolos apuntando al viejo Customer ID.
    """
    print("=" * 80)
    print("📋 Fase 3: Limpieza de Contacts y Dynamic Links.")
    print("=" * 80)

    fixed: int = 0

    for old_name, new_name in MANUAL_RENAMES:
        if old_name == new_name:
            continue

        # 1. Corregir Dynamic Links huérfanos
        frappe.db.sql("""
            UPDATE `tabDynamic Link`
            SET link_name = %(new_name)s
            WHERE link_doctype = 'Customer'
              AND link_name = %(old_name)s
        """, {"old_name": old_name, "new_name": new_name})

        if frappe.db.sql(
            "SELECT ROW_COUNT()", as_list=True
        )[0][0] > 0:
            print(f"  🔗 Dynamic Links: '{old_name}' → '{new_name}'")
            fixed += 1

        # 2. Corregir Contact first_name si tiene el viejo ID
        dirty_contacts: list[dict] = frappe.db.sql("""
            SELECT c.name
            FROM `tabContact` c
            WHERE c.first_name = %(old_name)s
        """, {"old_name": old_name}, as_dict=True)

        for contact in dirty_contacts:
            frappe.db.set_value(
                "Contact", contact["name"], "first_name",
                new_name.split()[0] if " " in new_name else new_name,
                update_modified=False,
            )
            print(f"  👤 Contact first_name: '{contact['name']}' → '{new_name.split()[0]}'")
            fixed += 1

        # 3. Limpiar snapshots contact_person/contact_display en facturas
        #    Se ponen en NULL para que Frappe los re-resuelva al abrir.
        for doctype in ("Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note"):
            frappe.db.sql("""
                UPDATE `tab{doctype}`
                SET contact_person = NULL,
                    contact_display = NULL
                WHERE contact_person LIKE %(pattern)s
            """.format(doctype=doctype), {
                "pattern": f"%{old_name}%",
            })

    frappe.db.commit()
    print(f"\n  Correcciones aplicadas: {fixed}")
    print()


def _update_customer_name_snapshots(
    customer: str,
    old_customer_name: str,
    new_customer_name: str,
    old_pk: str = "",
) -> None:
    """Actualiza el campo customer_name (Data snapshot) en documentos relacionados.

    Estos campos NO son Link fields, así que frappe.rename_doc() no los actualiza.
    Se actualizan directamente en la base de datos para no disparar hooks.

    Args:
        customer: PK actual (nuevo) del Customer.
        old_customer_name: Valor previo de customer_name.
        new_customer_name: Valor nuevo de customer_name.
        old_pk: PK previo del Customer (si difiere del old_customer_name).
    """
    if old_customer_name == new_customer_name and not old_pk:
        return

    if old_customer_name != new_customer_name:
        for table in ("tabSales Invoice", "tabVE Sales Credit Note", "tabVE Sales Debit Note"):
            frappe.db.sql(f"""
                UPDATE `{table}`
                SET customer_name = %(new_name)s
                WHERE customer = %(customer)s
                  AND customer_name = %(old_name)s
            """, {
                "customer": customer,
                "old_name": old_customer_name,
                "new_name": new_customer_name,
            })

    # tabGL Entry — campo `against` es Text, almacena el Customer PK viejo.
    # Actualizar por old_customer_name (si era igual al PK)
    # y por old_pk (si el PK difería del customer_name).
    # NOTA: `against` puede contener valores separados por comas en Journal
    # Entries compuestos. Para Sales Invoices (scope de este patch) siempre
    # es un valor único. Si se extiende a JE, considerar usar LIKE/REPLACE.
    against_values_to_fix: list[str] = [old_customer_name]
    if old_pk and old_pk != old_customer_name:
        against_values_to_fix.append(old_pk)

    for old_against in against_values_to_fix:
        if old_against == customer:
            continue  # Ya coincide, no necesita fix
        frappe.db.sql("""
            UPDATE `tabGL Entry`
            SET against = %(new_against)s
            WHERE against = %(old_against)s
        """, {
            "old_against": old_against,
            "new_against": customer,
        })

