# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Backfill histórico de hka_status y hka_series en documentos de venta.

Deriva el estado fiscal HKA de cada documento (Sales Invoice, VE Sales
Credit Note, VE Sales Debit Note con docstatus 1 o 2) replicando la lógica
del reporte "VE HKA Invoices Status", con precedencia:

    1. is_void = 1                        -> Anulada
    2. bill_control no vacío              -> Emitida
    3. último VE Digital Invoice Log Error -> Error
    4. resto                              -> Pendiente

La derivación se ancla en bill_control (no en el log): hay miles de
documentos emitidos sin log Success por deduplicación/registro tardío.

La serie (hka_series) solo se rellena en documentos Emitida, con cascada
de fuentes (de más a menos confiable):

    1. response_received del último log Success  -> resultado.serie
    2. payload_sent del último log Success       -> Encabezado.IdentificacionDocumento.Serie
    3. remarks del documento (JSON de HKA)       -> resultado.serie
    4. mapping actual sucursal -> serie (best-effort, refleja el mapping de HOY)

Escribe con frappe.db.set_value (sin hooks, no toca GL) y solo cuando el
valor derivado difiere del actual, por lo que es idempotente y re-ejecutable.

Uso:
    # simula (no escribe)
    bench --site [sitio] execute l10n_ve.scripts.backfill_hka_status.execute
    # ejecuta
    bench --site [sitio] execute l10n_ve.scripts.backfill_hka_status.execute --kwargs "{'dry_run': False}"
"""

import json

import frappe

_TARGETS: tuple[str, ...] = (
    "Sales Invoice",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
)


def derive_hka_status(row: dict, last_log_status: str | None) -> str:
    """Deriva el estado HKA de un documento (misma lógica que el reporte).

    Args:
        row: dict con is_void, bill_control (del documento).
        last_log_status: status del último VE Digital Invoice Log del
            documento ('Success' | 'Error' | '' | None).
    """
    if row.get("is_void"):
        return "Anulada"
    if row.get("bill_control"):
        return "Emitida"
    if last_log_status == "Error":
        return "Error"
    return "Pendiente"


def _serie_from_response(response_received: str | None) -> str:
    """Extrae resultado.serie del JSON de respuesta HKA. '' si no se puede."""
    if not response_received:
        return ""
    try:
        data = json.loads(response_received)
        return (data.get("resultado") or {}).get("serie") or ""
    except (json.JSONDecodeError, AttributeError, TypeError):
        return ""


def _serie_from_payload(payload_sent: str | None) -> str:
    """Extrae la Serie del payload enviado a HKA. '' si no se puede."""
    if not payload_sent:
        return ""
    try:
        data = json.loads(payload_sent)
        return (
            (data.get("documentoElectronico") or {})
            .get("Encabezado", {})
            .get("IdentificacionDocumento", {})
            .get("Serie")
        ) or ""
    except (json.JSONDecodeError, AttributeError, TypeError):
        return ""


def derive_hka_series(
    row: dict,
    success_log: dict | None,
    branch_serie_map: dict[str, str],
) -> tuple[str, str]:
    """Deriva la serie HKA de un documento Emitida.

    Returns:
        (serie, fuente) — fuente ∈ {log_response, log_payload, remarks,
        branch_map, ''} para reportar cobertura.
    """
    if success_log:
        serie = _serie_from_response(success_log.get("response_received"))
        if serie:
            return serie, "log_response"
        serie = _serie_from_payload(success_log.get("payload_sent"))
        if serie:
            return serie, "log_payload"

    serie = _serie_from_response(row.get("remarks"))
    if serie:
        return serie, "remarks"

    serie = branch_serie_map.get(row.get("branch") or "")
    if serie:
        return serie, "branch_map"

    return "", ""


def _last_log_status_map(doctype: str) -> dict[str, str]:
    """Mapa {doc_name: status} del último log por documento (1 query)."""
    rows = frappe.db.sql("""
        SELECT sales_invoice, status FROM (
            SELECT sales_invoice, status,
                   ROW_NUMBER() OVER (PARTITION BY sales_invoice ORDER BY creation DESC) AS rn
            FROM `tabVE Digital Invoice Log`
            WHERE document_type = %s
        ) t WHERE rn = 1
    """, (doctype,), as_dict=True)
    return {r.sales_invoice: r.status for r in rows}


def _last_success_log_map(doctype: str) -> dict[str, dict]:
    """Mapa {doc_name: {response_received, payload_sent}} del último log Success."""
    rows = frappe.db.sql("""
        SELECT sales_invoice, response_received, payload_sent FROM (
            SELECT sales_invoice, response_received, payload_sent,
                   ROW_NUMBER() OVER (PARTITION BY sales_invoice ORDER BY creation DESC) AS rn
            FROM `tabVE Digital Invoice Log`
            WHERE document_type = %s AND status = 'Success'
        ) t WHERE rn = 1
    """, (doctype,), as_dict=True)
    return {r.sales_invoice: r for r in rows}


def _branch_serie_map() -> dict[str, str]:
    """Mapa {branch: serie} desde VE Digital Billing Series (best-effort).

    Sin filtrar por status Active (el histórico pudo emitirse con series hoy
    agotadas), pero prefiriendo la fila Active cuando una sucursal aparece
    en más de una serie.
    """
    rows = frappe.db.sql("""
        SELECT child.branch, parent.serie, parent.status
        FROM `tabVE Digital Billing Series Branch` child
        INNER JOIN `tabVE Digital Billing Series` parent ON parent.name = child.parent
        WHERE IFNULL(parent.serie, '') != ''
        ORDER BY (parent.status = 'Active') ASC
    """, as_dict=True)
    # El ORDER BY deja las Active al final: al construir el dict, pisan a las demás
    return {r.branch: r.serie for r in rows}


def _has_columns(doctype: str) -> bool:
    """Verifica que las columnas nuevas existan físicamente (vía information_schema)."""
    table = f"tab{doctype}"
    cols = frappe.db.sql("""
        SELECT COLUMN_NAME FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
          AND COLUMN_NAME IN ('hka_status', 'hka_series')
    """, (table,))
    return len(cols) == 2


def execute(dry_run: bool = True) -> None:
    mode: str = "DRY-RUN (no escribe)" if dry_run else "EJECUCIÓN (escribe)"
    print(f"\n=== Backfill hka_status/hka_series — {mode} ===\n")

    branch_map: dict[str, str] = _branch_serie_map()
    total_scanned: int = 0
    total_written: int = 0
    serie_sources: dict[str, int] = {}

    for doctype in _TARGETS:
        if not _has_columns(doctype):
            print(f"-- {doctype}: SALTADO (faltan columnas hka_status/hka_series; correr bench migrate)\n")
            continue

        docs = frappe.get_all(
            doctype,
            filters={"docstatus": ["in", [1, 2]]},
            fields=[
                "name", "docstatus", "is_void", "bill_control",
                "branch", "remarks", "hka_status", "hka_series",
            ],
            limit_page_length=0,
        )
        log_status = _last_log_status_map(doctype)
        success_logs = _last_success_log_map(doctype)

        scanned: int = 0
        written: int = 0
        status_counts: dict[str, int] = {}

        for row in docs:
            scanned += 1
            new_status = derive_hka_status(row, log_status.get(row.name))
            status_counts[new_status] = status_counts.get(new_status, 0) + 1

            new_serie, source = "", ""
            if new_status in ("Emitida", "Anulada"):
                new_serie, source = derive_hka_series(
                    row, success_logs.get(row.name), branch_map
                )

            updates: dict = {}
            if new_status != (row.hka_status or ""):
                updates["hka_status"] = new_status
            if new_serie and new_serie != (row.hka_series or ""):
                updates["hka_series"] = new_serie

            if not updates:
                continue

            if source:
                serie_sources[source] = serie_sources.get(source, 0) + 1

            print(f"  [{doctype}] {row.name}: {row.hka_status or '(vacío)'} -> {new_status}"
                  + (f" | serie: {new_serie} ({source})" if "hka_series" in updates else ""))

            if not dry_run:
                frappe.db.set_value(doctype, row.name, updates, update_modified=False)
            written += 1

        total_scanned += scanned
        total_written += written
        counts_str = ", ".join(f"{k}: {v}" for k, v in sorted(status_counts.items()))
        print(f"-- {doctype}: {scanned} escaneados, {written} "
              f"{'a actualizar' if dry_run else 'actualizados'} | derivados: {counts_str}\n")

    if serie_sources:
        print("Fuentes de la serie:", ", ".join(f"{k}: {v}" for k, v in sorted(serie_sources.items())))

    if dry_run:
        print(f"\n=== DRY-RUN: {total_written} documentos cambiarían de {total_scanned} escaneados. "
              f"Re-ejecutar con --kwargs \"{{'dry_run': False}}\" para aplicar. ===")
    else:
        frappe.db.commit()
        print(f"\n=== COMMIT: {total_written} documentos actualizados de {total_scanned} escaneados ===")
