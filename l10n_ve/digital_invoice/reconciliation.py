"""
Reconciliación de datos fiscales HKA. Dos tareas programadas en hooks.py:

- ``reconcile_hka_fiscal_fields`` (horaria, a los :17): detecta y corrige facturas/NC/ND
  que HKA procesó con éxito (código 200 en remarks) pero cuyos campos bill_no y/o
  bill_control quedaron vacíos por un error de persistencia. Rellena el DOCUMENTO.
- ``fill_missing_gl_bill_fields`` (nocturna, 02:47): copia el número de factura y de
  control del documento a las líneas del mayor que no los tengan. Rellena el MAYOR.
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


#: Comprobantes cuyo número fiscal viaja al mayor. Son los mismos del parche de junio
#: (`patches/accounts/backfill_gl_entry_bill_fields.py`), que rellenó el histórico una vez.
_GL_BILL_SOURCES: tuple[str, ...] = (
    "Sales Invoice",
    "Purchase Invoice",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
    "VE Purchase Credit Note",
    "VE Purchase Debit Note",
)

#: Cuántos comprobantes se actualizan por sentencia.
_GL_BILL_BATCH: int = 500


def fill_missing_gl_bill_fields() -> list[str]:
    """Red nocturna: copia al mayor el número de factura y de control que le falten.

    El número llega al mayor en el momento de emitir: `_sync_gl_entries_date` lo copia
    cuando HKA responde. Esa copia puede no llegar sin dejar rastro --pasó con
    ACC-SINV-2026-21357, emitida el 4-ago: una sola entre más de 17 mil--, y entonces el
    Libro Mayor muestra la línea sin número ni control aunque el documento los tenga. El
    análisis del Débito Fiscal, que contabilidad hace desde ese reporte, queda cojo.

    Es el complemento de `reconcile_hka_fiscal_fields`: aquella rellena el DOCUMENTO desde
    la respuesta de HKA; esta rellena el MAYOR desde el documento.

    Solo rellena lo vacío, nunca pisa un número que ya esté en el mayor: si hay uno
    distinto, es una divergencia que tiene que verse, no taparse. No hace commit: lo hace
    el planificador al terminar la tarea.

    Returns:
        Los comprobantes que hubo que rellenar, como «Tipo Nombre». Vacío si no faltaba
        nada, que es lo esperable.
    """
    filled: list[str] = []
    for doctype in _GL_BILL_SOURCES:
        vouchers: list[str] = _vouchers_missing_gl_bill_fields(doctype)
        for start in range(0, len(vouchers), _GL_BILL_BATCH):
            _copy_bill_fields_to_gl(doctype, vouchers[start : start + _GL_BILL_BATCH])
        filled.extend(f"{doctype} {name}" for name in vouchers)

    if filled:
        # Que esto aparezca quiere decir que la copia al emitir falló: sirve para buscar
        # la causa. Un warning en el log de la aplicación no lo mira nadie.
        frappe.log_error(
            title="Número fiscal faltante en el mayor",
            message=(
                f"La copia del número fiscal al emitir no llegó al mayor en {len(filled)} "
                "comprobante(s). Se rellenó desde el documento:\n\n" + "\n".join(filled)
            ),
        )
    return filled


def _vouchers_missing_gl_bill_fields(doctype: str) -> list[str]:
    """Comprobantes aprobados con número o control, y alguna línea del mayor sin él.

    Es una lectura sin bloqueo, aparte de la escritura: la búsqueda recorre el mayor
    entero del tipo, y hacerla dentro del UPDATE bloquearía esas filas mientras dura
    --unos segundos-- frente a los documentos que se estén aprobando a esa hora.
    """
    # El tipo sale de _GL_BILL_SOURCES, no de un dato del usuario.
    # nosemgrep
    return frappe.db.sql(
        f"""
        SELECT DISTINCT gle.voucher_no
        FROM `tabGL Entry` gle
        JOIN `tab{doctype}` doc ON doc.name = gle.voucher_no
        WHERE gle.voucher_type = %(doctype)s
          AND gle.is_cancelled = 0
          AND doc.docstatus = 1
          AND (
                (COALESCE(doc.bill_no, '') != '' AND COALESCE(gle.bill_no, '') = '')
             OR (COALESCE(doc.bill_control, '') != '' AND COALESCE(gle.bill_control, '') = '')
          )
        ORDER BY gle.voucher_no
        """,
        {"doctype": doctype},
        pluck=True,
    )


def _copy_bill_fields_to_gl(doctype: str, vouchers: list[str]) -> None:
    """Copia número y control del documento a sus líneas del mayor, solo donde falten."""
    # El tipo sale de _GL_BILL_SOURCES, no de un dato del usuario.
    # nosemgrep
    frappe.db.sql(
        f"""
        UPDATE `tabGL Entry` gle
        JOIN `tab{doctype}` doc ON doc.name = gle.voucher_no
        SET gle.bill_no = IF(COALESCE(gle.bill_no, '') = '', doc.bill_no, gle.bill_no),
            gle.bill_control = IF(
                COALESCE(gle.bill_control, '') = '', doc.bill_control, gle.bill_control
            )
        WHERE gle.voucher_type = %(doctype)s
          AND gle.voucher_no IN %(vouchers)s
          AND gle.is_cancelled = 0
        """,
        {"doctype": doctype, "vouchers": tuple(vouchers)},
    )
