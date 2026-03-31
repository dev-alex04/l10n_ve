import json
from typing import Optional

import frappe
from frappe.utils import today

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient


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

        # Establecer posting_date y due_date a la fecha actual
        # para que coincidan con la Fecha de Asignación de HKA
        fecha_actual: str = today()
        if str(doc.posting_date) != fecha_actual or str(doc.due_date) != fecha_actual:
            doc.db_set("posting_date", fecha_actual, update_modified=False)
            doc.db_set("due_date", fecha_actual, update_modified=False)
            doc.reload()

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

            # Guardar la respuesta JSON en el campo remarks
            doc.db_set("remarks", json.dumps(response, indent=2, ensure_ascii=False), update_modified=False)

            # Actualizar GL Entries para que reflejen la fecha actual
            _sync_gl_entries_date(doc.name, fecha_actual)

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
            _log_request("Emision", doc.name, payload, response, "Error",
                         notes="\n".join(notes_parts))
            frappe.db.commit()
            return False

    except Exception as e:
        tb: str = frappe.get_traceback(with_context=True) or str(e)
        frappe.logger("l10n_ve").error(f"Error procesando FT Digital {invoice_name}: {tb}")
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


def _sync_gl_entries_date(voucher_no: str, new_date: str) -> None:
    """Actualiza las fechas de GL Entries, Payment Schedule y Payment Ledger Entry."""
    try:
        frappe.db.sql("""
            UPDATE `tabGL Entry`
            SET posting_date = %s
            WHERE voucher_type = 'Sales Invoice'
            AND voucher_no = %s
        """, (new_date, voucher_no))

        frappe.db.sql("""
            UPDATE `tabPayment Schedule`
            SET due_date = %s
            WHERE parent = %s
            AND parenttype = 'Sales Invoice'
        """, (new_date, voucher_no))

        frappe.db.sql("""
            UPDATE `tabPayment Ledger Entry`
            SET posting_date = %s, due_date = %s
            WHERE voucher_type = 'Sales Invoice'
            AND voucher_no = %s
        """, (new_date, new_date, voucher_no))
    except Exception as e:
        frappe.logger("l10n_ve").error(
            f"Error actualizando registros contables para {voucher_no}: {str(e)}"
        )


def _log_request(
    endpoint: str,
    invoice_name: str,
    payload: dict,
    response: dict,
    status: str,
    notes: str = ""
) -> None:
    """Registra el log de la solicitud."""
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
    success = process_invoice(invoice_name)
    return "Sent" if success else "Error"

