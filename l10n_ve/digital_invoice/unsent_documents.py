# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Clasificador de documentos que debieron enviarse a HKA y no salieron.

Devuelve, para el mes en curso, una fila por documento con el motivo y qué hacer.
Lo consume el aviso diario (``l10n_ve.tasks``) y sirve igual desde ``bench execute``
para diagnosticar sin mandar correo.

Dos criterios distintos según la familia, porque **el umbral de tiempo solo tiene
sentido donde hay cron**:

- Facturas de venta y comprobantes de retención: el cron los intenta cada 5 minutos,
  así que un documento enviable que sigue sin salir después de ``grace_minutes``
  perdió seis ciclos y eso es una señal. Los que fallaron se reportan siempre.
- Notas de crédito y débito: **no tienen envío automático** (existió y se revirtió,
  PR #494 → #495), así que no existe el estado "en vuelo": cualquiera sin emitir
  espera a que alguien la mande a mano, sin importar la hora.

El reloj entra por parámetro (``reference_datetime``) y no se lee acá adentro: así
los tests fijan la hora y el resultado es reproducible.
"""

from __future__ import annotations

import datetime

import frappe
from frappe.utils import get_first_day, getdate

from l10n_ve.digital_invoice.tfhka_integration import _RANGE_EXHAUSTED_KEYWORDS

#: Minutos que se le conceden al cron antes de considerar que un documento se trabó.
#: El cron corre cada 5 minutos, así que 30 son seis ciclos perdidos.
DEFAULT_GRACE_MINUTES = 30

#: Motivo → (etiqueta, qué hacer). El texto sale tal cual en el correo.
REASONS: dict[str, tuple[str, str]] = {
    "rate_mismatch": (
        "Tasa incoherente",
        "Corrija la tasa del documento o la fila de Currency Exchange de esa fecha.",
    ),
    "range_exhausted": (
        "Rango de numeración agotado en HKA",
        "Solicite la ampliación del rango a HKA. Mientras tanto la serie no emite nada.",
    ),
    "series_halted": (
        "Serie detenida: otro documento agotó el rango",
        "Se resuelve solo al ampliar el rango con HKA; este documento no tiene falla propia.",
    ),
    "hka_rejected": (
        "HKA rechazó el documento",
        "Revise el detalle y corrija el dato observado antes de reintentar.",
    ),
    "technical_error": (
        "Error técnico en el envío",
        "Requiere revisión de Sistemas: el envío falló antes de llegar a HKA.",
    ),
    "no_branch": (
        "Sin sucursal",
        "Asigne la sucursal al documento; sin ella el cron no lo toma.",
    ),
    "no_active_series": (
        "Sucursal sin serie digital activa",
        "Configure o active la serie de facturación digital de esa sucursal.",
    ),
    "stalled": (
        "Enviable y sin salir",
        "El cron tuvo varias oportunidades y no lo envió. Revise el log del documento.",
    ),
    "manual_pending": (
        "Sin emitir (no hay envío automático)",
        "Las notas se emiten a mano desde el propio documento.",
    ),
}


def _reason(code: str) -> tuple[str, str]:
    return REASONS.get(code, (code, ""))


def _classify_log_notes(notes: str | None) -> str:
    """Traduce el texto del último log a un motivo.

    El orden importa: un traceback puede mencionar cualquier cosa, así que se
    descarta primero. Los volcados crudos nunca se muestran al usuario; para eso
    está el motivo 'technical_error'.
    """
    text: str = (notes or "").strip()
    if not text:
        return "hka_rejected"

    lowered: str = text.lower()

    if "traceback" in lowered:
        return "technical_error"
    if any(k in lowered for k in _RANGE_EXHAUSTED_KEYWORDS):
        return "range_exhausted"
    if "tasa" in lowered:
        return "rate_mismatch"
    return "hka_rejected"


def _safe_detail(notes: str | None, reason_code: str) -> str:
    """Detalle mostrable. De un traceback no se muestra nada: no es para contabilidad."""
    if reason_code == "technical_error":
        return ""
    return " ".join((notes or "").split())[:300]


def _active_series_branches() -> set[str]:
    rows = frappe.db.sql(
        """
        SELECT DISTINCT b.branch
        FROM `tabVE Digital Billing Series` s
        JOIN `tabVE Digital Billing Series Branch` b ON b.parent = s.name
        WHERE s.status = 'Active'
        """,
        as_dict=True,
    )
    return {r.branch for r in rows if r.branch}


def _last_logs(doctype: str, names: list[str]) -> dict[str, dict]:
    """Último log por documento. Sin esto no se puede dar un motivo por documento.

    Ojo: hay logs con ``sales_invoice`` NULL —resúmenes de lote del cron, ~24% del
    total— que nombran los documentos en prosa. No sirven acá y quedan fuera por el
    propio filtro de nombres.
    """
    if not names:
        return {}

    rows = frappe.db.sql(
        """
        SELECT sales_invoice, status, notes, creation
        FROM (
            SELECT sales_invoice, status, notes, creation,
                   ROW_NUMBER() OVER (PARTITION BY sales_invoice ORDER BY creation DESC) rn
            FROM `tabVE Digital Invoice Log`
            WHERE document_type = %(doctype)s AND sales_invoice IN %(names)s
        ) x WHERE rn = 1
        """,
        {"doctype": doctype, "names": names},
        as_dict=True,
    )
    return {r.sales_invoice: r for r in rows}


def _is_stalled(row: dict, last_log: dict | None, deadline: datetime.datetime) -> bool:
    """¿El documento ya era enviable antes del corte y sigue sin salir?

    El ancla es el movimiento más reciente: el último intento del cron si lo hubo, y
    si no el ``modified`` del documento —que es cuando pasó a ser enviable, típicamente
    al cobrarse—. Nada lo toca después, así que el valor no se refresca solo.
    """
    marcas = [row.get("modified")]
    if last_log:
        marcas.append(last_log.get("creation"))

    ultima = max((m for m in marcas if m), default=None)
    if not ultima:
        return True

    return ultima < deadline


def get_unsent_documents(
    reference_datetime: datetime.datetime,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> dict:
    """Documentos del mes en curso que debieron enviarse a HKA y no salieron.

    Args:
        reference_datetime: momento de referencia (la hora del aviso). Define el mes
            y el corte de gracia. Se inyecta para que los tests fijen el reloj.
        grace_minutes: minutos de tolerancia antes de considerar trabado un documento.

    Returns:
        dict con ``rows`` (lista de filas), ``period`` y ``auto_send_enabled``. La
        lista vacía significa que no hay nada que reportar — el llamador no envía.
    """
    settings: dict = (
        frappe.db.get_singles_dict("TFHKA Settings") or {}
    )
    cutoff_date = settings.get("cutoff_date")

    desde = get_first_day(reference_datetime.date())
    hasta = reference_datetime.date()
    deadline = reference_datetime - datetime.timedelta(minutes=grace_minutes)

    rows: list[dict] = []
    rows.extend(_collect_sales_invoices(desde, hasta, deadline, cutoff_date))
    rows.extend(_collect_sales_notes(desde, hasta, cutoff_date))
    rows.extend(_collect_vouchers(desde, hasta, deadline, cutoff_date))

    rows.sort(key=lambda r: (r["date"], r["doctype"], r["name"]))

    return {
        "rows": rows,
        "period": {"from": desde, "to": hasta, "as_of": reference_datetime},
        "auto_send_enabled": bool(settings.get("enable_auto_send")),
    }


def _collect_sales_invoices(desde, hasta, deadline, cutoff_date) -> list[dict]:
    """Facturas: las que fallaron siempre; las enviables, solo si perdieron el plazo."""
    docs = frappe.db.sql(
        """
        SELECT si.name, si.posting_date AS date, si.customer_name AS party,
               si.grand_total AS amount, si.currency, si.branch, si.status,
               si.bill_control, si.modified
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.is_return = 0 AND si.is_debit_note = 0
          AND si.posting_date BETWEEN %(desde)s AND %(hasta)s
          AND (si.bill_control IS NULL OR si.bill_control = '')
        """,
        {"desde": desde, "hasta": hasta},
        as_dict=True,
    )
    if not docs:
        return []

    logs = _last_logs("Sales Invoice", [d.name for d in docs])
    branches = _active_series_branches()

    # Sucursales cuya serie quedó frenada por rango agotado: el circuit breaker corta
    # la serie entera, así que los demás documentos de esa sucursal no llegan ni a
    # intentarse y su "Pendiente" no es culpa suya.
    halted: set[str] = {
        d.branch
        for d in docs
        if d.branch
        and (log := logs.get(d.name))
        and log.status != "Success"
        and _classify_log_notes(log.notes) == "range_exhausted"
    }

    out: list[dict] = []
    for d in docs:
        log = logs.get(d.name)
        if log and log.status == "Success":
            continue

        if log and log.status != "Success":
            code = _classify_log_notes(log.notes)
            out.append(_row("Sales Invoice", d, code, _safe_detail(log.notes, code)))
            continue

        # Sin intento previo: solo interesa si YA debía haber salido.
        if cutoff_date and getdate(d.date) < getdate(cutoff_date):
            continue
        if d.status != "Paid":
            continue  # esperando cobro: es el diseño emitir-al-pagar, no una falla
        if not d.branch:
            out.append(_row("Sales Invoice", d, "no_branch", ""))
            continue
        if d.branch not in branches:
            out.append(_row("Sales Invoice", d, "no_active_series", ""))
            continue
        if not _is_stalled(d, log, deadline):
            continue  # recién se volvió enviable: está legítimamente en vuelo

        code = "series_halted" if d.branch in halted else "stalled"
        out.append(_row("Sales Invoice", d, code, ""))

    return out


def _collect_sales_notes(desde, hasta, cutoff_date) -> list[dict]:
    """Notas de crédito y débito: sin cron, así que no hay plazo que esperar."""
    out: list[dict] = []

    for doctype in ("VE Sales Credit Note", "VE Sales Debit Note"):
        docs = frappe.db.sql(
            f"""
            SELECT nc.name, nc.posting_date AS date, nc.customer_name AS party,
                   nc.grand_total AS amount, nc.currency, nc.branch, nc.modified
            FROM `tab{doctype}` nc
            WHERE nc.docstatus = 1
              AND nc.posting_date BETWEEN %(desde)s AND %(hasta)s
              AND (nc.bill_control IS NULL OR nc.bill_control = '')
            """,
            {"desde": desde, "hasta": hasta},
            as_dict=True,
        )
        if not docs:
            continue

        logs = _last_logs(doctype, [d.name for d in docs])

        for d in docs:
            if cutoff_date and getdate(d.date) < getdate(cutoff_date):
                continue
            log = logs.get(d.name)
            if log and log.status == "Success":
                continue
            if log:
                code = _classify_log_notes(log.notes)
                out.append(_row(doctype, d, code, _safe_detail(log.notes, code)))
            else:
                out.append(_row(doctype, d, "manual_pending", ""))

    return out


def _collect_vouchers(desde, hasta, deadline, cutoff_date) -> list[dict]:
    """Comprobantes de retención: mismo criterio que las facturas (tienen cron)."""
    familias = (
        ("VAT Withholding Voucher", "issue_date"),
        ("ISLR Withholding Voucher", "posting_date"),
    )
    out: list[dict] = []

    for doctype, date_field in familias:
        docs = frappe.db.sql(
            f"""
            SELECT v.name, v.{date_field} AS date, v.supplier_name AS party,
                   v.branch, v.modified, v.digital_invoice_status AS own_status
            FROM `tab{doctype}` v
            WHERE v.docstatus = 1
              AND v.{date_field} BETWEEN %(desde)s AND %(hasta)s
              AND (v.bill_control IS NULL OR v.bill_control = '')
              AND (v.digital_invoice_status IS NULL
                   OR v.digital_invoice_status IN ('', 'Pending', 'Error'))
            """,
            {"desde": desde, "hasta": hasta},
            as_dict=True,
        )
        if not docs:
            continue

        logs = _last_logs(doctype, [d.name for d in docs])

        for d in docs:
            if cutoff_date and getdate(d.date) < getdate(cutoff_date):
                continue
            log = logs.get(d.name)
            if log and log.status == "Success":
                continue
            if log:
                code = _classify_log_notes(log.notes)
                out.append(_row(doctype, d, code, _safe_detail(log.notes, code)))
            elif _is_stalled(d, log, deadline):
                out.append(_row(doctype, d, "stalled", ""))

    return out


def _row(doctype: str, doc: dict, reason_code: str, detail: str) -> dict:
    label, action = _reason(reason_code)
    return {
        "doctype": doctype,
        "name": doc.get("name"),
        "date": doc.get("date"),
        "party": doc.get("party") or "",
        "amount": doc.get("amount"),
        "currency": doc.get("currency") or "",
        "branch": doc.get("branch") or "",
        "reason_code": reason_code,
        "reason": label,
        "action": action,
        "detail": detail,
    }
