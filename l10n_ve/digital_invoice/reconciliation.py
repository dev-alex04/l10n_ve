"""
Reconciliación de datos fiscales HKA.

Detecta y corrige facturas/NC/ND que fueron procesadas exitosamente
por HKA (código 200 en remarks) pero cuyos campos bill_no y/o
bill_control quedaron vacíos por un error de persistencia.

Registrado como tarea horaria en hooks.py:
    scheduler_events.cron["0 * * * *"]
"""
import json
from typing import Optional

import frappe


# DocTypes que pasan por HKA
_DOCTYPES_HKA: list[str] = [
    "Sales Invoice",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
]


def reconcile_hka_fiscal_fields() -> None:
    """Busca documentos con respuesta HKA exitosa pero bill_no/bill_control vacíos.

    Para cada caso, extrae los valores de la respuesta JSON almacenada
    en remarks y los persiste en los campos correspondientes.
    """
    total_fixed: int = 0

    for doctype in _DOCTYPES_HKA:
        fixed: int = _reconcile_doctype(doctype)
        total_fixed += fixed

    if total_fixed > 0:
        frappe.db.commit()
        frappe.logger("l10n_ve").warning(
            f"[HKA Reconciliación] Se corrigieron {total_fixed} documentos "
            f"con bill_no/bill_control vacíos."
        )


def _reconcile_doctype(doctype: str) -> int:
    """Reconcilia un DocType específico. Retorna cantidad de documentos corregidos."""

    table: str = f"tab{doctype}"

    orphans: list[dict] = frappe.db.sql(f"""
        SELECT
            doc.name,
            doc.remarks,
            doc.bill_no,
            doc.bill_control
        FROM `{table}` doc
        WHERE doc.docstatus = 1
          AND LOCATE('"codigo": "200"', doc.remarks) > 0
          AND (doc.bill_no IS NULL OR doc.bill_no = ''
               OR doc.bill_control IS NULL OR doc.bill_control = '')
        LIMIT 100
    """, as_dict=True)

    if not orphans:
        return 0

    fixed: int = 0

    for doc in orphans:
        resultado: Optional[dict] = _extract_resultado(doc["remarks"])
        if not resultado:
            continue

        numero_documento: str = resultado.get("numeroDocumento") or ""
        numero_control: str = resultado.get("numeroControl") or ""

        if not numero_documento and not numero_control:
            continue

        updates: dict = {}
        if not doc["bill_no"] and numero_documento:
            updates["bill_no"] = numero_documento
        if not doc["bill_control"] and numero_control:
            updates["bill_control"] = numero_control

        if updates:
            # Respuesta HKA exitosa en remarks → el doc está emitido
            updates["hka_status"] = "Emitida"
            if resultado.get("serie"):
                updates["hka_series"] = resultado["serie"]

            frappe.db.set_value(
                doctype, doc["name"], updates,
                update_modified=False,
            )
            fixed += 1
            frappe.logger("l10n_ve").info(
                f"[HKA Reconciliación] {doctype} {doc['name']}: "
                f"bill_no='{updates.get('bill_no', '')}', "
                f"bill_control='{updates.get('bill_control', '')}'"
            )

    return fixed


def _extract_resultado(remarks: str) -> Optional[dict]:
    """Extrae el dict 'resultado' del JSON almacenado en remarks."""
    if not remarks:
        return None
    try:
        data: dict = json.loads(remarks)
        return data.get("resultado")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
