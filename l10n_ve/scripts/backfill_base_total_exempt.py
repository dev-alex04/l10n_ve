"""
Backfill del campo base_total_exempt (VEF) en documentos de venta.

Replica la fórmula de calculate_total_exempt(): suma base_net_amount de las
líneas exentas (misma base y redondeo per-ítem que base_net_total), de modo que
el Libro de Ventas y el payload HKA cuadren sin arrastrar céntimos.

Escribe un solo campo con frappe.db.set_value (no dispara hooks; no toca GL ni
el ledger), por lo que es idempotente: re-ejecutar produce los mismos valores.

Uso:
    # simula (no escribe)
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_base_total_exempt.execute

    # ejecuta
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_base_total_exempt.execute \
        --kwargs "{'dry_run': False}"
"""
import frappe
from frappe.utils import flt

# Documento de venta -> su child table de líneas
_TARGETS: dict[str, str] = {
    "Sales Invoice": "Sales Invoice Item",
    "VE Sales Credit Note": "VE Sales Credit Note Item",
    "VE Sales Debit Note": "VE Sales Debit Note Item",
}

_TOLERANCE: float = 0.01


def _has_base_column(parent_dt: str) -> bool:
    """¿Existe físicamente la columna base_total_exempt?

    Consulta information_schema directo en vez de frappe.db.get_table_columns:
    ese helper cachea y durante `bench migrate` puede devolver un valor
    desactualizado, reportando como ausente una columna que sí existe.
    """
    return bool(
        frappe.db.sql(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = DATABASE()
                AND table_name = %s
                AND column_name = 'base_total_exempt'
            LIMIT 1
            """,
            (f"tab{parent_dt}",),
        )
    )


def _exempt_base_sums(parent_dt: str, child_dt: str) -> dict:
    """Mapa {parent: suma de base_net_amount de líneas exentas}.

    Una sola query agregada por doctype (evita N+1 al recorrer documentos).
    child_dt proviene de _TARGETS (hardcoded), no de entrada externa.
    """
    rows: list = frappe.db.sql(
        f"""
        SELECT parent, ROUND(SUM(base_net_amount), 2) AS total
        FROM `tab{child_dt}`
        WHERE parenttype = %s AND vat_exempt = 1
        GROUP BY parent
        """,
        (parent_dt,),
        as_dict=True,
    )
    return {r.parent: flt(r.total) for r in rows}


def execute(dry_run: bool = True) -> None:
    mode: str = "DRY-RUN (no escribe)" if dry_run else "EJECUCIÓN (escribe)"
    print(f"\n=== Backfill base_total_exempt — {mode} ===\n")

    grand_scanned: int = 0
    grand_written: int = 0

    for parent_dt, child_dt in _TARGETS.items():
        has_col: bool = _has_base_column(parent_dt)

        # En ejecución real, sin columna no hay nada que escribir: se omite el
        # doctype (el dry-run sí continúa para poder previsualizar antes del migrate).
        if not has_col and not dry_run:
            print(f"  [omitido] {parent_dt}: la columna base_total_exempt no existe; "
                  f"corre la migración primero.\n")
            continue

        fields: list[str] = ["name", "total_exempt"]
        if has_col:
            fields.append("base_total_exempt")
        else:
            print(f"  [aviso] {parent_dt}: la columna base_total_exempt no existe aún; "
                  f"se muestra el valor que se escribiría.\n")

        docs: list = frappe.get_all(
            parent_dt,
            filters={"docstatus": ["in", [1, 2]], "total_exempt": [">", 0]},
            fields=fields,
        )

        sum_map: dict = _exempt_base_sums(parent_dt, child_dt)
        scanned: int = len(docs)
        written: int = 0

        for doc in docs:
            new_value: float = flt(sum_map.get(doc.name, 0.0))
            current: float = flt(doc.get("base_total_exempt")) if has_col else 0.0

            if abs(new_value - current) <= _TOLERANCE:
                continue

            print(f"  [{parent_dt}] {doc.name}: base_total_exempt "
                  f"{current} -> {new_value}  (total_exempt={doc.total_exempt})")
            if not dry_run:
                frappe.db.set_value(
                    parent_dt, doc.name, "base_total_exempt", new_value,
                    update_modified=False,
                )
            written += 1

        verb: str = "a actualizar" if dry_run else "actualizados"
        print(f"-- {parent_dt}: {scanned} escaneados, {written} {verb}\n")
        grand_scanned += scanned
        grand_written += written

    if not dry_run:
        frappe.db.commit()
        print(f"=== COMMIT: {grand_written} documentos actualizados de {grand_scanned} escaneados ===\n")
    else:
        print(
            f"=== DRY-RUN: {grand_written} documentos cambiarían de {grand_scanned} escaneados. "
            f"Re-ejecutar con --kwargs \"{{'dry_run': False}}\" para aplicar. ===\n"
        )
