# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Backfill histórico de hka_status y hka_series en documentos de venta.

Deriva el estado fiscal HKA de cada documento (Sales Invoice, VE Sales
Credit Note, VE Sales Debit Note con docstatus 1 o 2) con semántica
ESTRICTA: el campo solo afirma lo que HKA registró de verdad.

Un documento tiene EVIDENCIA HKA si cumple al menos una de:
    - último VE Digital Invoice Log con status Success,
    - remarks con respuesta HKA parseable (codigo 200/201),
    - bill_control con formato HKA (NN-NNNNNNNN).

Derivación (precedencia):
    1. is_void = 1 y evidencia HKA           -> Anulada
    2. evidencia HKA                         -> Emitida
    3. último log Error y docstatus = 1      -> Error
    4. sin evidencia, docstatus = 1 y
       posting_date >= cutoff (TFHKA Settings.cutoff_date,
       la misma fuente que el cron de envío) -> Pendiente (accionable)
    5. resto (legacy pre-HKA, cancelados sin
       emisión, void local sin rastro HKA)   -> '' (vacío: HKA no lo conoce)

La serie (hka_series) solo se rellena con fuentes verificadas del propio
documento — NUNCA se infiere del mapping sucursal->serie (el histórico
demostró que diverge):
    1. response_received del último log Success -> resultado.serie
    2. payload_sent del último log Success      -> encabezado.identificacionDocumento.serie
    3. remarks del documento (JSON de HKA)      -> resultado.serie

Escribe con frappe.db.set_value (sin hooks, no toca GL) solo cuando el
valor derivado difiere del actual (idempotente, re-ejecutable), con commit
por lotes de 500 para no sostener locks largos.

Recomendación operativa: ejecutar con el scheduler pausado (o fuera de la
ventana de facturación) para evitar carreras con el cron de emisión.

Uso:
    # simula (no escribe)
    bench --site [sitio] execute l10n_ve.scripts.backfill_hka_status.execute
    # ejecuta
    bench --site [sitio] execute l10n_ve.scripts.backfill_hka_status.execute --kwargs "{'dry_run': False}"
"""

import json
import re

import frappe
from frappe.utils import getdate

_TARGETS: tuple[str, ...] = (
    "Sales Invoice",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
)

_HKA_CONTROL_RE = re.compile(r"^\d{2}-\d{8}$")
_COMMIT_BATCH: int = 500
_DEFAULT_CUTOFF: str = "2026-04-01"


def _hka_response_ok(raw_json: str | None) -> bool:
    """True si el texto es una respuesta HKA exitosa (codigo 200/201)."""
    if not raw_json:
        return False
    try:
        data = json.loads(raw_json)
        return str(data.get("codigo", "")) in ("200", "201")
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return False


def has_hka_evidence(row: dict, success_log: dict | None) -> bool:
    """True si el documento tiene rastro verificable de emisión en HKA."""
    if success_log:
        return True
    if _HKA_CONTROL_RE.match(str(row.get("bill_control") or "").strip()):
        return True
    return _hka_response_ok(row.get("remarks"))


def derive_hka_status(
    row: dict,
    last_log_status: str | None,
    success_log: dict | None,
    cutoff: "object",
) -> str:
    """Deriva el estado HKA de un documento (semántica estricta).

    Args:
        row: dict con is_void, bill_control, remarks, docstatus, posting_date.
        last_log_status: status del último VE Digital Invoice Log ('Success' |
            'Error' | '' | None).
        success_log: último log Success del documento (o None).
        cutoff: fecha de corte HKA (datetime.date).
    """
    evidence = has_hka_evidence(row, success_log)

    if row.get("is_void"):
        # Void local sin rastro HKA (void_document legacy) NO es una
        # anulación fiscal ante HKA: queda vacío.
        return "Anulada" if evidence else ""

    if evidence:
        return "Emitida"

    if last_log_status == "Error" and row.get("docstatus") == 1:
        return "Error"

    if (
        row.get("docstatus") == 1
        and not row.get("bill_control")
        and row.get("posting_date")
        and getdate(row["posting_date"]) >= cutoff
    ):
        # Pendiente = accionable: activo, sin NINGÚN número fiscal previo
        # (un control legacy del talonario anterior no está "por emitir")
        # y dentro de la era HKA.
        return "Pendiente"

    return ""


def _serie_from_response(response_received: str | None) -> str:
    """Extrae resultado.serie del JSON de respuesta HKA. '' si no se puede."""
    if not response_received:
        return ""
    try:
        data = json.loads(response_received)
        return (data.get("resultado") or {}).get("serie") or ""
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return ""


def _serie_from_payload(payload_sent: str | None) -> str:
    """Extrae la serie del payload enviado a HKA. '' si no se puede.

    Los logs reales guardan el payload en camelCase
    (documentoElectronico.encabezado.identificacionDocumento.serie); se
    prueba también la variante PascalCase por robustez.
    """
    if not payload_sent:
        return ""
    try:
        data = json.loads(payload_sent)
        doc_e = data.get("documentoElectronico") or {}
        for enc_key, ident_key, serie_key in (
            ("encabezado", "identificacionDocumento", "serie"),
            ("Encabezado", "IdentificacionDocumento", "Serie"),
        ):
            serie = (
                (doc_e.get(enc_key) or {}).get(ident_key, {}).get(serie_key)
            )
            if serie:
                return serie
        return ""
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return ""


def derive_hka_series(row: dict, success_log: dict | None) -> tuple[str, str]:
    """Deriva la serie HKA desde fuentes verificadas del propio documento.

    Returns:
        (serie, fuente) — fuente ∈ {log_response, log_payload, remarks, ''}.
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

    return "", ""


def _last_log_status_map(doctype: str) -> dict[str, str]:
    """Mapa {doc_name: status} del último log por documento (1 query)."""
    rows = frappe.db.sql("""
        SELECT sales_invoice, status FROM (
            SELECT sales_invoice, status,
                   ROW_NUMBER() OVER (
                       PARTITION BY sales_invoice
                       ORDER BY creation DESC, name DESC
                   ) AS rn
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
                   ROW_NUMBER() OVER (
                       PARTITION BY sales_invoice
                       ORDER BY creation DESC, name DESC
                   ) AS rn
            FROM `tabVE Digital Invoice Log`
            WHERE document_type = %s AND status = 'Success'
        ) t WHERE rn = 1
    """, (doctype,), as_dict=True)
    return {r.sales_invoice: r for r in rows}


def get_hka_cutoff() -> "object":
    """Fecha de corte HKA — misma fuente que el cron de envío."""
    cutoff = None
    try:
        cutoff = frappe.get_cached_value("TFHKA Settings", "TFHKA Settings", "cutoff_date")
    except Exception:
        pass
    return getdate(cutoff or _DEFAULT_CUTOFF)


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
    cutoff = get_hka_cutoff()
    print(f"\n=== Backfill hka_status/hka_series — {mode} | cutoff HKA: {cutoff} ===\n")

    total_scanned: int = 0
    total_written: int = 0
    pending_in_batch: int = 0
    serie_sources: dict[str, int] = {}

    for doctype in _TARGETS:
        if not _has_columns(doctype):
            print(f"-- {doctype}: SALTADO (faltan columnas hka_status/hka_series; correr bench migrate)\n")
            continue

        docs = frappe.get_all(
            doctype,
            filters={"docstatus": ["in", [1, 2]]},
            fields=[
                "name", "docstatus", "is_void", "bill_control", "posting_date",
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
            success_log = success_logs.get(row.name)
            new_status = derive_hka_status(row, log_status.get(row.name), success_log, cutoff)
            status_counts[new_status or "(vacío)"] = status_counts.get(new_status or "(vacío)", 0) + 1

            new_serie, source = "", ""
            if new_status in ("Emitida", "Anulada"):
                new_serie, source = derive_hka_series(row, success_log)

            updates: dict = {}
            if new_status != (row.hka_status or ""):
                updates["hka_status"] = new_status
            if new_serie and new_serie != (row.hka_series or ""):
                updates["hka_series"] = new_serie

            if not updates:
                continue

            if "hka_series" in updates and source:
                serie_sources[source] = serie_sources.get(source, 0) + 1

            print(f"  [{doctype}] {row.name}: {row.hka_status or '(vacío)'} -> {new_status or '(vacío)'}"
                  + (f" | serie: {new_serie} ({source})" if "hka_series" in updates else ""))

            if not dry_run:
                frappe.db.set_value(doctype, row.name, updates, update_modified=False)
                pending_in_batch += 1
                if pending_in_batch >= _COMMIT_BATCH:
                    frappe.db.commit()
                    pending_in_batch = 0
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
