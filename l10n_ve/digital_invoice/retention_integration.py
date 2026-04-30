"""Módulo de integración con TFHKA para comprobantes de retención de IVA.

Contiene la lógica de envío, validación pre-envío, manejo de respuesta
y registro de logs para la emisión electrónica de comprobantes tipo 05.
"""
import json
import time
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import flt

from l10n_ve.digital_invoice.vat_whithholding_payload_builder import TFHKARetentionPayloadBuilder
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_RETENTION_BATCH_SIZE: int = 50
_RETENTION_DELAY_BETWEEN_CALLS: float = 0.5


# ---------------------------------------------------------------------------
# Validación pre-envío
# ---------------------------------------------------------------------------

def _validate_retention_integrity(doc) -> list[str]:
    """Valida la integridad del comprobante antes de enviar a HKA.

    Verifica que todos los datos requeridos por la API estén presentes
    y que los montos sean consistentes con las fórmulas de HKA.

    Args:
        doc: Documento VAT Withholding Voucher cargado.

    Returns:
        Lista de mensajes de error. Vacía si todo es válido.
    """
    errors: list[str] = []
    items: list = doc.get("vat_withholding_voucher_item", [])

    # Validar que el comprobante tenga ítems
    if not items:
        errors.append("El comprobante no tiene facturas asociadas.")

    # Validar monto total de IVA > 0
    if not flt(doc.totals_taxes_and_charges_added):
        errors.append("El monto total de IVA es 0.")

    # Validar RIF del proveedor
    supplier_tax_id: str = frappe.get_cached_value(
        "Supplier", doc.supplier, "tax_id"
    ) or ""
    if not supplier_tax_id.strip():
        errors.append(
            f"El proveedor '{doc.supplier}' no tiene RIF (Tax ID) configurado."
        )

    # Validar datos y aritmética de cada factura (mismas reglas que HKA)
    total_retenido_calc: float = 0.0
    for idx, item in enumerate(items, start=1):
        prefix: str = f"Línea {idx} ({item.purchase_invoice})"

        if not (item.bill_no or "").strip():
            errors.append(f"{prefix}: Falta el No. de Factura (bill_no).")

        if not (item.bill_control or "").strip():
            errors.append(f"{prefix}: Falta el No. de Control (bill_control).")

        if not flt(item.rate):
            errors.append(f"{prefix}: La alícuota de IVA (rate) es 0.")

        if not flt(item.withholding_rate):
            errors.append(f"{prefix}: El porcentaje de retención es 0.")

        # HKA valida [1055]: MontoTotal = BaseImponible + MontoExento + MontoIVA
        base: float = flt(item.total)
        exento: float = flt(item.total_exempt)
        iva: float = flt(item.taxes_and_charges_added)
        expected_total: float = base + exento + iva
        grand: float = flt(item.grand_total)
        if abs(expected_total - grand) > 0.05 and abs(expected_total) > 0:
            # grand_total puede no cuadrar (incluye retención), no es error del voucher
            pass

        # HKA valida [1060]: Retenido = MontoIVA × PorcentajeRetencion
        retenido_calc: float = iva * flt(item.withholding_rate) / 100
        if retenido_calc <= 0 and iva > 0 and flt(item.withholding_rate) > 0:
            errors.append(
                f"{prefix}: El monto retenido calculado es 0 "
                f"(IVA={iva:.2f} × Ret={item.withholding_rate}%)."
            )

        total_retenido_calc += retenido_calc

    # Validar consistencia de total retenido
    if items and total_retenido_calc <= 0:
        errors.append(
            "El total retenido calculado es 0. Verifique alícuotas y porcentajes."
        )

    return errors


# ---------------------------------------------------------------------------
# Logging en VE Digital Invoice Log
# ---------------------------------------------------------------------------

def _log_retention_request(
    endpoint: str,
    voucher_name: str,
    payload: dict,
    response: dict,
    status: str,
    notes: str = "",
    document_type: str = "VAT Withholding Voucher",
) -> None:
    """Registra la solicitud/respuesta en VE Digital Invoice Log.

    Args:
        endpoint: Nombre del endpoint o acción (ej: 'Emision', 'HKA Cron Retenciones').
        voucher_name: Nombre del comprobante de retención.
        payload: Payload enviado a HKA.
        response: Respuesta recibida de HKA.
        status: 'Success' o 'Error'.
        notes: Notas adicionales descriptivas.
        document_type: Tipo de documento ('VAT Withholding Voucher' o 'ISLR Withholding Voucher').
    """
    try:
        log = frappe.new_doc("VE Digital Invoice Log")
        log.document_type = document_type
        log.sales_invoice = voucher_name
        log.endpoint = endpoint
        log.status = status
        log.payload_sent = json.dumps(payload, ensure_ascii=False, indent=1) if payload else ""
        log.response_received = json.dumps(response, ensure_ascii=False, indent=1) if response else ""
        log.notes = notes[:2000] if notes else ""
        log.insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(
            title=f"Error al registrar log de retención {voucher_name}",
            message=f"Endpoint: {endpoint}\nStatus: {status}\nError: {e}",
        )
        frappe.logger("tfhka").error(
            f"Error al registrar log de retención {voucher_name}: {e}"
        )


def _hka_retention_log(description: str, status: str = "Info") -> None:
    """Registra un evento del cron de retenciones en VE Digital Invoice Log."""
    _log_retention_request(
        endpoint="HKA Cron Retenciones",
        voucher_name="",
        payload={},
        response={},
        status=status,
        notes=description,
    )


# ---------------------------------------------------------------------------
# Procesamiento individual de comprobante
# ---------------------------------------------------------------------------

def process_retention_voucher(
    voucher_name: str,
    raise_on_error: bool = False,
) -> bool:
    """Envía un comprobante de retención IVA a TFHKA.

    Construye el payload tipo 05, lo envía vía TFHKAClient.emitir_documento()
    y actualiza el estado del documento según la respuesta.

    Args:
        voucher_name: Nombre del comprobante VAT Withholding Voucher.
        raise_on_error: Si True, lanza excepción en caso de error.

    Returns:
        True si la emisión fue exitosa, False en caso contrario.
    """
    doc = frappe.get_doc("VAT Withholding Voucher", voucher_name)

    # Validar integridad antes de enviar
    validation_errors: list[str] = _validate_retention_integrity(doc)
    if validation_errors:
        error_msg: str = "Validación pre-envío fallida:\n" + "\n".join(validation_errors)
        _log_retention_request(
            endpoint="Emision",
            voucher_name=voucher_name,
            payload={},
            response={"error": True, "validation_errors": validation_errors},
            status="Error",
            notes=error_msg,
        )
        doc.db_set("digital_invoice_status", "Error")
        frappe.db.commit()
        if raise_on_error:
            frappe.throw(error_msg)
        return False

    # Construir payload
    builder = TFHKARetentionPayloadBuilder(doc)
    payload: dict = builder.build_payload()

    # Enviar a HKA
    try:
        client = TFHKAClient()
        response: dict = client.emitir_documento(payload)
    except Exception as e:
        error_msg = f"Error de conexión con TFHKA: {str(e)}"
        _log_retention_request(
            endpoint="Emision",
            voucher_name=voucher_name,
            payload=payload,
            response={"error": True, "message": str(e)},
            status="Error",
            notes=error_msg,
        )
        doc.db_set("digital_invoice_status", "Error")
        frappe.db.commit()
        if raise_on_error:
            frappe.throw(error_msg)
        return False

    # Procesar respuesta
    return _handle_retention_response(doc, payload, response, raise_on_error)


def _handle_retention_response(
    doc,
    payload: dict,
    response: dict,
    raise_on_error: bool = False,
    document_type: str = "VAT Withholding Voucher",
) -> bool:
    """Procesa la respuesta de HKA para un comprobante de retención.

    Actualiza el estado del documento y registra el log correspondiente.

    Args:
        doc: Documento de retención (VAT o ISLR Withholding Voucher).
        payload: Payload que se envió.
        response: Respuesta de la API.
        raise_on_error: Si True, lanza excepción en caso de error.
        document_type: Tipo de documento para el log.

    Returns:
        True si la emisión fue exitosa.
    """
    response_code: str = str(response.get("codigo", "")) if response else ""
    is_success: bool = (
        response
        and not response.get("error")
        and response_code in ("200", "201")
    )

    if is_success:
        # Extraer datos asignados por HKA
        resultado: dict = response.get("resultado") or {}
        hka_doc_number: str = resultado.get("numeroDocumento", "")
        hka_control: str = resultado.get("numeroControl", "")

        # Persistir todos los campos en una sola operación (1 UPDATE)
        update_values: dict = {
            "digital_invoice_status": "Sent",
            "hka_response": json.dumps(response, ensure_ascii=False, indent=2),
        }
        if hka_doc_number:
            update_values["voucher_number"] = hka_doc_number
        if hka_control:
            update_values["bill_control"] = hka_control

        doc.db_set(update_values)

        _log_retention_request(
            endpoint="Emision",
            voucher_name=doc.name,
            payload=payload,
            response=response,
            status="Success",
            notes=f"Comprobante {doc.name} emitido exitosamente. N° HKA: {hka_doc_number}",
            document_type=document_type,
        )

        return True

    # Error
    error_detail: str = response.get("mensaje", str(response)) if response else "Sin respuesta"
    notes: str = f"Error al emitir comprobante {doc.voucher_number}: {error_detail}"

    doc.db_set("digital_invoice_status", "Error")
    _log_retention_request(
        endpoint="Emision",
        voucher_name=doc.name,
        payload=payload,
        response=response or {},
        status="Error",
        notes=notes,
        document_type=document_type,
    )

    frappe.db.commit()
    if raise_on_error:
        frappe.throw(notes)
    return False


# ---------------------------------------------------------------------------
# Whitelist para reenvío manual desde botón JS
# ---------------------------------------------------------------------------

@frappe.whitelist()
def send_retention_voucher_manually(voucher_name: str) -> str:
    """Reenvío manual de comprobante de retención IVA a TFHKA.

    Invocado desde el botón 'Enviar a HKA' en el formulario cuando
    el estado es 'Error'.

    Args:
        voucher_name: Nombre del comprobante.

    Returns:
        Mensaje descriptivo del resultado.
    """
    frappe.has_permission("VAT Withholding Voucher", "submit", doc=voucher_name, throw=True)
    success: bool = process_retention_voucher(voucher_name, raise_on_error=True)
    return _("Comprobante enviado exitosamente.") if success else _("Error al enviar.")


# ---------------------------------------------------------------------------
# Cron: envío masivo de comprobantes pendientes
# ---------------------------------------------------------------------------

def send_pending_retention_vouchers(tfhka_settings: dict) -> None:
    """Procesa comprobantes de retención IVA pendientes de envío a HKA.

    Se ejecuta como paso adicional del cron unificado, después del envío
    de facturas de venta.

    Args:
        tfhka_settings: Configuración de TFHKA con cutoff_date.
    """
    cutoff_date: str = tfhka_settings.get("cutoff_date", "2026-04-01")

    pending: list[str] = _get_pending_retention_vouchers(cutoff_date)
    if not pending:
        return

    _hka_retention_log(
        f"Retenciones IVA: {len(pending)} comprobante(s) pendiente(s).",
        "Success",
    )

    success_count: int = 0
    error_count: int = 0
    success_vouchers: list[str] = []
    error_vouchers: list[str] = []

    for voucher_name in pending:
        try:
            result: bool = process_retention_voucher(voucher_name)

            if result:
                success_count += 1
                success_vouchers.append(voucher_name)
                frappe.db.commit()
            else:
                error_count += 1
                error_vouchers.append(voucher_name)
                frappe.db.commit()

        except Exception as e:
            error_count += 1
            error_vouchers.append(voucher_name)
            frappe.db.rollback()
            _log_retention_request(
                endpoint="HKA Cron Retenciones",
                voucher_name=voucher_name,
                payload={},
                response={"error": True, "message": str(e)},
                status="Error",
                notes=f"Excepción al enviar {voucher_name}: {str(e)}",
            )

        time.sleep(_RETENTION_DELAY_BETWEEN_CALLS)

    # Resumen del lote
    if success_count or error_count:
        lines: list[str] = [
            f"Retenciones IVA completado: {success_count} exitosas, {error_count} con error.",
        ]
        if success_vouchers:
            lines.append(f"Exitosas: {', '.join(success_vouchers)}")
        if error_vouchers:
            lines.append(f"Con error: {', '.join(error_vouchers)}")

        _hka_retention_log(
            "\n".join(lines),
            "Success" if error_count == 0 else "Error",
        )


def _get_pending_retention_vouchers(cutoff_date: str) -> list[str]:
    """Obtiene comprobantes de retención aprobados y pendientes de envío a HKA.

    Criterios:
    - docstatus = 1 (aprobado)
    - issue_date >= cutoff_date
    - digital_invoice_status vacío, Pending o Error
    - Sin log exitoso previo

    Args:
        cutoff_date: Fecha mínima de emisión para filtrar.

    Returns:
        Lista de nombres de comprobantes pendientes.
    """
    results = frappe.db.sql("""
        SELECT vwv.name
        FROM `tabVAT Withholding Voucher` vwv
        LEFT JOIN `tabVE Digital Invoice Log` log
            ON log.sales_invoice = vwv.name
            AND log.status = 'Success'
            AND log.document_type = 'VAT Withholding Voucher'
        WHERE vwv.docstatus = 1
          AND vwv.issue_date >= %s
          AND (vwv.digital_invoice_status IS NULL
               OR vwv.digital_invoice_status IN ('', 'Pending', 'Error'))
          AND log.name IS NULL
        ORDER BY vwv.issue_date, vwv.name
        LIMIT %s
    """, (cutoff_date, _RETENTION_BATCH_SIZE), as_list=True)

    return [r[0] for r in results]


# ---------------------------------------------------------------------------
# Anulación de comprobante en HKA
# ---------------------------------------------------------------------------

@frappe.whitelist()
def void_retention_voucher(
    voucher_name: str,
    reason: str,
    void_date: str,
    void_time: str,
) -> dict:
    """Anula un Comprobante de Retención IVA en TFHKA y cancela en Frappe.

    Flujo:
    1. Valida permisos y estado del documento.
    2. Extrae serie y número de documento de hka_response.
    3. Envía anulación a HKA (tipo 05).
    4. Si HKA confirma, cancela el documento en Frappe.

    Args:
        voucher_name: Nombre del VAT Withholding Voucher.
        reason:       Motivo de anulación (texto libre).
        void_date:    Fecha en formato DD/MM/YYYY.
        void_time:    Hora en HH:MM:SS (24h); se convierte a 12h.

    Returns:
        dict con status y message si fue exitoso.
    """

    doc = frappe.get_doc("VAT Withholding Voucher", voucher_name)
    frappe.has_permission("VAT Withholding Voucher", ptype="cancel", doc=doc, throw=True)

    if doc.docstatus != 1:
        frappe.throw(_("Solo se pueden anular comprobantes aprobados."))

    if doc.digital_invoice_status != "Sent":
        frappe.throw(
            _("Solo se pueden anular comprobantes que fueron emitidos a HKA (estado: Sent).")
        )

    # Extraer número de documento y serie desde hka_response (fuente definitiva)
    # hka_response contiene el número asignado por HKA, que puede diferir del
    # voucher_number en documentos pre-migración
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
        "tipoDocumento": "05",
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

