# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Derivación canónica del estado fiscal HKA (hka_status / hka_series).

Única fuente de verdad de la semántica ESTRICTA: el estado solo afirma lo
que HKA registró de verdad. Consumida por el reporte VE HKA Invoices Status
y por los backfills de las apps de cliente (p. ej.
domina_galanet.patches.backfill_hka_status).

Un documento tiene EVIDENCIA HKA si cumple al menos una de:
    - último VE Digital Invoice Log con status Success,
    - remarks con respuesta HKA parseable (codigo 200/201),
    - bill_control con formato HKA (NN-NNNNNNNN).

Derivación (precedencia):
    1. is_void = 1 y evidencia HKA           -> Anulada
    2. evidencia HKA                         -> Emitida
    3. último log Error y docstatus = 1      -> Error
    4. sin evidencia, docstatus = 1, sin
       número fiscal previo y posting_date
       >= cutoff (TFHKA Settings.cutoff_date,
       la misma fuente que el cron de envío) -> Pendiente (accionable)
    5. resto (legacy pre-HKA, cancelados sin
       emisión, void local sin rastro HKA)   -> '' (vacío: HKA no lo conoce)

La serie (hka_series) solo se deriva de fuentes verificadas del propio
documento — NUNCA se infiere del mapping sucursal->serie (el histórico
demostró que diverge):
    1. response_received del último log Success -> resultado.serie
    2. payload_sent del último log Success      -> encabezado.identificacionDocumento.serie
    3. remarks del documento (JSON de HKA)      -> resultado.serie
"""

import json
import re

import frappe
from frappe.utils import getdate

HKA_CONTROL_RE = re.compile(r"^\d{2}-\d{8}$")
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
    if HKA_CONTROL_RE.match(str(row.get("bill_control") or "").strip()):
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


def resolve_display_status(
    row: dict,
    last_log_status: str | None,
    success_log: dict | None,
    cutoff: "object",
) -> str:
    """Estado a mostrar: el campo persistido, salvo que la evidencia lo contradiga.

    ``hka_status`` lo mantiene el flujo en vivo y es lo primero que se mira, pero **no
    es evidencia**: está vacío en miles de documentos certificados y hay caminos de
    fallo que no lo actualizan (el guard de tasa lanza ``ValidationError`` y hasta
    2026-08 se re-lanzaba sin marcar nada). Confiar solo en el campo hace que el
    reporte subcuente: el 2026-08-09 mostraba 1 error de agosto habiendo 16.

    La regla: si el ÚLTIMO intento falló y el documento no está certificado, es
    ``Error`` aunque el campo diga otra cosa. Certificado = tiene ``bill_control`` o
    su último log es Success. Cuando no hay campo ni contradicción, se deriva.

    Args:
        row: dict con hka_status, bill_control, is_void, remarks, docstatus, posting_date.
        last_log_status: status del último VE Digital Invoice Log ('Success' | 'Error' | '' | None).
        success_log: último log Success del documento (o None).
        cutoff: fecha de corte HKA (datetime.date).
    """
    last_attempt_failed: bool = bool(last_log_status) and last_log_status != "Success"
    is_certified: bool = bool(row.get("bill_control")) or last_log_status == "Success"

    if last_attempt_failed and not is_certified:
        return "Error"

    return (
        row.get("hka_status")
        or derive_hka_status(row, last_log_status, success_log, cutoff)
        or ""
    )


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


def last_log_status_map(doctype: str) -> dict[str, str]:
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


def last_success_log_map(doctype: str) -> dict[str, dict]:
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
