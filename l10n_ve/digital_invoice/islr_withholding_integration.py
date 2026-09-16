"""Módulo de integración con TFHKA para comprobantes de retención de ISLR.

Contiene la lógica de envío, validación pre-envío, manejo de respuesta
y registro de logs para la emisión electrónica de comprobantes tipo 06.

Reutiliza el patrón y las funciones de logging de retention_integration.py.
"""
import json
import time

import frappe
from frappe import _
from frappe.utils import flt, nowdate, add_months

from l10n_ve.digital_invoice.islr_payload_builder import TFHKAISLRPayloadBuilder
from l10n_ve.digital_invoice.retention_integration import (
    _log_retention_request,
    _handle_retention_response,
    _validate_digital_series,
)
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient
from l10n_ve.digital_invoice.tfhka_integration import company_uses_hk


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_ISLR_DOCTYPE: str = "ISLR Withholding Voucher"
_ISLR_CHILD_TABLE: str = "islr_withholding_voucher_item"
_ISLR_BATCH_SIZE: int = 50
_ISLR_DELAY_BETWEEN_CALLS: float = 0.5


# ---------------------------------------------------------------------------
# Validación pre-envío
# ---------------------------------------------------------------------------

def _validate_islr_integrity(doc) -> list[str]:
    """Valida la integridad del comprobante ISLR antes de enviar a HKA.

    Args:
        doc: Documento ISLR Withholding Voucher cargado.

    Returns:
        Lista de mensajes de error. Vacía si todo es válido.
    """
    errors: list[str] = []
    items: list = doc.get(_ISLR_CHILD_TABLE, [])

    # Serie digital fail-closed (mismo incidente que retención IVA:
    # el builder traga el error de serie y emitiría con serie vacía)
    errors.extend(_validate_digital_series(doc))

    if not items:
        errors.append("El comprobante no tiene facturas asociadas.")

    if not flt(doc.totals_islr_amount):
        errors.append("El monto total de ISLR retenido es 0.")

    # Validar RIF del proveedor
    supplier_tax_id: str = frappe.get_cached_value(
        "Supplier", doc.supplier, "tax_id"
    ) or ""
    if not supplier_tax_id.strip():
        errors.append(
            f"El proveedor '{doc.supplier_name}' no tiene RIF (Tax ID) configurado."
        )

    # Validar datos de cada línea
    for idx, item in enumerate(items, start=1):
        prefix: str = f"Línea {idx} ({item.purchase_invoice})"

        if not (item.doc_no or "").strip():
            errors.append(f"{prefix}: Falta el No. de Factura (doc_no).")

        if not (item.bill_control or "").strip():
            errors.append(f"{prefix}: Falta el No. de Control (bill_control).")

        if not flt(item.rate):
            errors.append(f"{prefix}: La alícuota de ISLR (rate) es 0.")

        if not (item.code or "").strip():
            errors.append(f"{prefix}: Falta el código de concepto ISLR.")

        if not flt(item.islr_base_amount):
            errors.append(f"{prefix}: La base imponible ISLR es 0.")

    return errors


# ---------------------------------------------------------------------------
# Procesamiento individual
# ---------------------------------------------------------------------------

def process_islr_voucher(
    voucher_name: str,
    raise_on_error: bool = False,
) -> bool:
    """Envía un comprobante de retención ISLR a TFHKA.

    Args:
        voucher_name: Nombre del ISLR Withholding Voucher.
        raise_on_error: Si True, lanza excepción en caso de error.

    Returns:
        True si la emisión fue exitosa.
    """
    doc = frappe.get_doc(_ISLR_DOCTYPE, voucher_name)

    # Guarda condicional: si la empresa no emite con HKA --el sitio lo tiene apagado, o la
    # empresa no tiene ninguna serie digital activa-- se omite el envío sin error. Mira la
    # EMPRESA, no la sucursal: una sucursal sin serie es configuración rota y tiene que caer
    # en la validación de integridad de abajo, que deja estado Error y log.
    if not company_uses_hk(doc.empresa):
        if doc.digital_invoice_status != "Not Applicable":
            doc.db_set("digital_invoice_status", "Not Applicable")
        frappe.logger("tfhka").info(
            f"Omite envío a HKA/HK para comprobante ISLR {voucher_name}: la empresa '{doc.empresa}' no emite con HKA."
        )
        return True

    # Validar integridad
    validation_errors: list[str] = _validate_islr_integrity(doc)
    if validation_errors:
        error_msg: str = "Validación pre-envío fallida:\n" + "\n".join(validation_errors)
        _log_retention_request(
            endpoint="Emision ISLR",
            voucher_name=voucher_name,
            payload={},
            response={"error": True, "validation_errors": validation_errors},
            status="Error",
            notes=error_msg,
            document_type=_ISLR_DOCTYPE,
        )
        doc.db_set("digital_invoice_status", "Error")
        frappe.db.commit()
        if raise_on_error:
            frappe.throw(error_msg)
        return False

    # Construir payload
    builder = TFHKAISLRPayloadBuilder(doc)
    payload: dict = builder.build_payload()

    # Enviar a HKA
    try:
        client = TFHKAClient()
        response: dict = client.emitir_documento(payload)
    except Exception:
        error_msg = f"Error de conexión con TFHKA: {frappe.get_traceback()}"
        _log_retention_request(
            endpoint="Emision ISLR",
            voucher_name=voucher_name,
            payload=payload,
            response={"error": True, "message": frappe.get_traceback()},
            status="Error",
            notes=error_msg,
            document_type=_ISLR_DOCTYPE,
        )
        doc.db_set("digital_invoice_status", "Error")
        frappe.db.commit()
        if raise_on_error:
            frappe.throw(error_msg)
        return False

    return _handle_retention_response(doc, payload, response, raise_on_error, document_type=_ISLR_DOCTYPE)


# ---------------------------------------------------------------------------
# Whitelist: envío manual desde botón JS
# ---------------------------------------------------------------------------

@frappe.whitelist()
def send_islr_voucher_manually(voucher_name: str) -> str:
    """Reenvío manual de comprobante de retención ISLR a TFHKA."""
    frappe.has_permission(_ISLR_DOCTYPE, "submit", doc=voucher_name, throw=True)
    success: bool = process_islr_voucher(voucher_name, raise_on_error=True)
    return _("Comprobante enviado exitosamente.") if success else _("Error al enviar.")


# ---------------------------------------------------------------------------
# Cron: envío masivo de comprobantes ISLR pendientes
# ---------------------------------------------------------------------------

def send_pending_islr_vouchers(tfhka_settings: dict) -> None:
    """Procesa comprobantes de retención ISLR pendientes de envío a HKA.

    Args:
        tfhka_settings: Configuración de TFHKA con cutoff_date.
    """
    cutoff_date: str = tfhka_settings.get(
        "cutoff_date", add_months(nowdate(), -3)
    )

    pending: list[str] = _get_pending_islr_vouchers(cutoff_date)
    if not pending:
        return

    _log_retention_request(
        endpoint="HKA Cron Retenciones ISLR",
        voucher_name="",
        payload={},
        response={},
        status="Success",
        notes=f"Retenciones ISLR: {len(pending)} comprobante(s) pendiente(s).",
        document_type=_ISLR_DOCTYPE,
    )

    success_count: int = 0
    error_count: int = 0
    success_vouchers: list[str] = []
    error_vouchers: list[str] = []

    for voucher_name in pending:
        try:
            result: bool = process_islr_voucher(voucher_name)

            if result:
                success_count += 1
                success_vouchers.append(voucher_name)
            else:
                error_count += 1
                error_vouchers.append(voucher_name)

            frappe.db.commit()
        except Exception as e:
            error_count += 1
            error_vouchers.append(voucher_name)
            frappe.db.rollback()
            _log_retention_request(
                endpoint="HKA Cron Retenciones ISLR",
                voucher_name=voucher_name,
                payload={},
                response={"error": True, "message": str(e)},
                status="Error",
                notes=f"Excepción al enviar {voucher_name}: {str(e)}",
                document_type=_ISLR_DOCTYPE,
            )

        time.sleep(_ISLR_DELAY_BETWEEN_CALLS)

    # Resumen del lote
    if success_count or error_count:
        lines: list[str] = [
            f"Retenciones ISLR completado: {success_count} exitosas, {error_count} con error.",
        ]
        if success_vouchers:
            lines.append(f"Exitosas: {', '.join(success_vouchers)}")
        if error_vouchers:
            lines.append(f"Con error: {', '.join(error_vouchers)}")

        _log_retention_request(
            endpoint="HKA Cron Retenciones ISLR",
            voucher_name="",
            payload={},
            response={},
            status="Success" if error_count == 0 else "Error",
            notes="\n".join(lines),
            document_type=_ISLR_DOCTYPE,
        )


def _get_pending_islr_vouchers(cutoff_date: str) -> list[str]:
    """Obtiene comprobantes ISLR aprobados y pendientes de envío a HKA."""
    results = frappe.db.sql("""
        SELECT iwv.name
        FROM `tabISLR Withholding Voucher` iwv
        LEFT JOIN `tabVE Digital Invoice Log` log
            ON log.sales_invoice = iwv.name
            AND log.status = 'Success'
            AND log.document_type = 'ISLR Withholding Voucher'
        WHERE iwv.docstatus = 1
          AND iwv.posting_date >= %s
          AND (iwv.digital_invoice_status IS NULL
               OR iwv.digital_invoice_status IN ('', 'Pending', 'Error'))
          AND log.name IS NULL
        ORDER BY iwv.posting_date, iwv.name
        LIMIT %s
    """, (cutoff_date, _ISLR_BATCH_SIZE), as_list=True)

    return [r[0] for r in results]


# ---------------------------------------------------------------------------
# Anulación de comprobante ISLR en HKA
# ---------------------------------------------------------------------------

@frappe.whitelist()
def void_islr_voucher(
    voucher_name: str,
    reason: str,
    void_date: str,
    void_time: str,
) -> dict:
    """Anula un Comprobante de Retención ISLR en TFHKA y cancela en Frappe."""
    from datetime import datetime

    doc = frappe.get_doc(_ISLR_DOCTYPE, voucher_name)
    frappe.has_permission(_ISLR_DOCTYPE, ptype="cancel", doc=doc, throw=True)

    if doc.docstatus != 1:
        frappe.throw(_("Solo se pueden anular comprobantes aprobados."))

    if doc.digital_invoice_status != "Sent":
        frappe.throw(
            _("Solo se pueden anular comprobantes que fueron emitidos a HKA (estado: Sent).")
        )

    if not doc.hka_response:
        frappe.throw(_("El comprobante no tiene respuesta de HKA almacenada."))

    try:
        hka_data: dict = json.loads(doc.hka_response)
    except (json.JSONDecodeError, TypeError):
        frappe.throw(_("Los datos de respuesta HKA no son válidos."))

    resultado: dict = hka_data.get("resultado") or {}
    numero_documento: str = resultado.get("numeroDocumento", "")
    serie: str = resultado.get("serie", "")

    if not numero_documento:
        frappe.throw(
            _("No se encontró el número de documento HKA en la respuesta almacenada.")
        )

    # Convertir hora 24h a 12h para TFHKA
    try:
        time_obj = datetime.strptime(void_time, "%H:%M:%S")
        formatted_time: str = time_obj.strftime("%I:%M:%S %p").lower()
    except ValueError:
        formatted_time = void_time

    payload: dict = {
        "serie": serie,
        "tipoDocumento": "06",
        "numeroDocumento": numero_documento,
        "motivoAnulacion": reason,
        "fechaAnulacion": void_date,
        "horaAnulacion": formatted_time,
    }

    client = TFHKAClient()
    client.authenticate()
    result: dict = client.void_document(payload)

    if result.get("error") or not result.get("_http_ok"):
        error_message: str = (
            result.get("mensaje") or result.get("message") or "Error desconocido"
        )
        frappe.throw(
            _(
                "HKA rechazó la anulación del comprobante. Código: {0} | Respuesta: {1}"
            ).format(result.get("codigo", "—"), error_message),
            title=_("Error al Anular en HKA"),
        )

    # HKA confirmó → cancelar en Frappe
    doc.db_set("digital_invoice_status", "Voided", update_modified=False)
    frappe.flags.hka_void_confirmed = True
    try:
        doc.cancel()
    finally:
        frappe.flags.pop("hka_void_confirmed", None)
    doc.add_comment(
        "Comment",
        _("Comprobante anulado ante HKA. Motivo: {0}").format(reason),
    )

    return {
        "status": "success",
        "message": _("Comprobante anulado correctamente en HKA y en el sistema."),
    }
