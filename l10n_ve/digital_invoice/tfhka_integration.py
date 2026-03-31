from typing import Optional

import frappe
from frappe import _
from frappe.utils import getdate

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient


def _get_cutoff_date():
    """Retorna la fecha de corte configurada en TFHKA Settings."""
    return getdate(
        frappe.get_cached_value("TFHKA Settings", "TFHKA Settings", "cutoff_date")
    )


def get_active_billing_series(company: str, branch: str = "") -> Optional[object]:
    """
    Retorna el registro activo de VE Digital Billing Series.
    Búsqueda en orden de prioridad:
      1. Por empresa + sucursal (si la factura tiene sucursal)
      2. Por empresa sin sucursal (serie a nivel empresa, fallback)
    """
    filters_branch = {"company": company, "branch": branch, "status": "Active"}
    filters_company = {"company": company, "branch": ["is", "not set"], "status": "Active"}

    if branch:
        series_name = frappe.db.get_value("VE Digital Billing Series", filters_branch, "name")
        if series_name:
            return frappe.get_doc("VE Digital Billing Series", series_name)

    series_name = frappe.db.get_value("VE Digital Billing Series", filters_company, "name")
    if series_name:
        return frappe.get_doc("VE Digital Billing Series", series_name)

    return None


def update_billing_series_after_response(series_doc: object, control_number_str: str) -> None:
    """
    Actualiza el registro de la serie tras recibir el número de control de TFHKA.
    Si el número alcanzó el Range To, marca la serie como Exhausted.
    """
    try:
        numeric_part = control_number_str.split("-")[-1]
        if not numeric_part.isdigit():
            return
        control_int = int(numeric_part)

        series_doc.db_set("last_control_number", control_int, update_modified=False)

        if control_int >= series_doc.range_to:
            series_doc.db_set("status", "Exhausted", update_modified=False)
            frappe.logger("l10n_ve").warning(
                f"Serie TFHKA {series_doc.name} agotada. "
                f"Rango {series_doc.range_from}-{series_doc.range_to} completado."
            )

        frappe.clear_document_cache("VE Digital Billing Series", series_doc.name)

    except Exception as e:
        frappe.logger("l10n_ve").error(f"Error actualizando serie TFHKA: {str(e)}")


def process_invoice(invoice_name: str) -> bool:
    """
    Envía una factura a TFHKA de forma síncrona.
    Retorna True si el envío fue exitoso, False en caso de error.
    """
    try:
        doc = frappe.get_doc("Sales Invoice", invoice_name)

        if doc.digital_billing_status == "Sent":
            return True

        branch = doc.get("branch") or ""
        series_doc = get_active_billing_series(company=doc.company, branch=branch)

        builder = TFHKAPayloadBuilder(doc, series_doc=series_doc)
        payload = builder.build_payload()

        if not builder.zona or not builder.nodo:
            missing = []
            if not builder.zona:
                missing.append("Zona (territory del cliente)")
            if not builder.nodo:
                missing.append("Nodo (router/nodo del servicio)")
            notes = (
                f"No se pudo resolver: {', '.join(missing)}. "
                f"Cliente: {doc.customer}, Suscripción: {doc.get('subscription') or 'N/A'}"
            )
            doc.db_set("digital_billing_status", "Error", update_modified=False)
            _log_request("Emision", doc.name, payload, {"error": True, "message": notes}, "Error", notes=notes)
            frappe.db.commit()
            return False

        client = TFHKAClient()
        response = client.emitir_documento(payload)

        is_success = (
            response
            and not response.get("error")
            and str(response.get("codigo", "")) in ("200", "201")
        )

        if is_success:
            resultado = response.get("resultado") or {}
            control = resultado.get("numeroControl")

            if control:
                doc.db_set("bill_control", control, update_modified=False)
                if series_doc:
                    update_billing_series_after_response(series_doc, control)

            doc.db_set("digital_billing_status", "Sent", update_modified=False)
            _log_request("Emision", doc.name, payload, response, "Success")
            frappe.db.commit()
            return True
        else:
            validaciones = response.get("validaciones") or []
            mensaje = response.get("mensaje") or response.get("message") or ""
            notes_parts = []
            if mensaje:
                notes_parts.append(f"Mensaje: {mensaje}")
            if validaciones:
                notes_parts.append("Validaciones: " + "; ".join(str(v) for v in validaciones))
            doc.db_set("digital_billing_status", "Error", update_modified=False)
            _log_request("Emision", doc.name, payload, response, "Error",
                         notes="\n".join(notes_parts))
            frappe.db.commit()
            return False

    except Exception as e:
        tb: str = frappe.get_traceback(with_context=True) or str(e)
        frappe.logger("l10n_ve").error(f"Error procesando FT Digital {invoice_name}: {tb}")
        frappe.db.set_value(
            "Sales Invoice", invoice_name,
            "digital_billing_status", "Error",
            update_modified=False
        )
        _log_request(
            "Emision",
            invoice_name,
            payload if "payload" in locals() else {},
            {"error": True, "message": str(e)},
            "Error",
            notes=tb
        )
        frappe.db.commit()
        return False


def _log_request(
    endpoint: str,
    invoice_name: str,
    payload: dict,
    response: dict,
    status: str,
    notes: str = ""
) -> None:
    """Registra el log de la solicitud."""
    import json
    log_data: dict = {
        "endpoint": endpoint,
        "sales_invoice": invoice_name,
        "payload_sent": json.dumps(payload, ensure_ascii=False, indent=1),
        "response_received": (
            json.dumps(response, ensure_ascii=False, indent=1)
            if isinstance(response, dict) else response
        ),
        "status": status,
        "notes": notes or "",
    }
    _create_log_entry(log_data)


def _create_log_entry(log_data: dict) -> None:
    """Inserta el registro VE Digital Invoice Log en la DB."""
    log = frappe.new_doc("VE Digital Invoice Log")
    log.update(log_data)
    log.insert(ignore_permissions=True)


@frappe.whitelist()
def send_invoice_manually(invoice_name: str) -> str:
    """Método invocado mediante botón JS para reenvío manual."""
    frappe.has_permission("Sales Invoice", "submit", doc=invoice_name, throw=True)
    process_invoice(invoice_name)
    status = frappe.db.get_value("Sales Invoice", invoice_name, "digital_billing_status")
    return status


def retry_pending_digital_invoices() -> None:
    """
    Task programado (cada 5 min) que procesa facturas digitales
    pendientes o con error de forma síncrona y secuencial.
    STOP on error: si una factura falla, detiene el procesamiento.
    """
    try:
        if not frappe.get_cached_value("TFHKA Settings", "TFHKA Settings", "enabled"):
            return
    except Exception:
        return

    cutoff_date = _get_cutoff_date()
    if not cutoff_date:
        return

    invoices: list[dict] = frappe.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 1,
            "digital_billing_status": ["in", ["Pending", "Error"]],
            "posting_date": [">=", cutoff_date],
        },
        fields=["name"],
        order_by="posting_date asc, creation asc",
        limit=50,
    )

    if not invoices:
        return

    processed: int = 0
    for inv in invoices:
        success: bool = process_invoice(inv.name)
        if success:
            processed += 1
        else:
            frappe.logger("l10n_ve").warning(
                f"TFHKA batch: STOP en factura {inv.name}. "
                f"{processed} facturas enviadas exitosamente antes del error."
            )
            return

    if processed:
        frappe.logger("l10n_ve").info(
            f"TFHKA batch: {processed} facturas enviadas exitosamente"
        )
