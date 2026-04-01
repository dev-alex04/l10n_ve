import json

import frappe
from frappe.utils import today

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient


def get_active_billing_series(
    company: str, branch: str
) -> tuple[object, str]:
    """
    Retorna (series_doc, branch_code) buscando la sucursal de la factura
    en la tabla hija 'VE Digital Billing Series Branch'.

    - La sucursal es obligatoria: si la factura no tiene branch → throw.
    - Si la sucursal no está en ninguna serie activa de la empresa → throw.

    El branch_code se obtiene directamente de la fila de la tabla hija.
    """
    if not branch:
        frappe.throw(
            "La factura no tiene una sucursal asignada. "
            "Asigne una sucursal antes de enviar a la imprenta digital.",
            title="Sucursal Requerida"
        )

    row = frappe.db.sql("""
        SELECT
            child.parent       AS series_name,
            child.branch_code  AS branch_code
        FROM `tabVE Digital Billing Series Branch` child
        INNER JOIN `tabVE Digital Billing Series` serie
            ON serie.name = child.parent
        WHERE child.branch  = %s
          AND serie.company = %s
          AND serie.status  = 'Active'
        LIMIT 1
    """, (branch, company), as_dict=True)

    if not row:
        frappe.throw(
            f"La sucursal '{branch}' no está configurada en ninguna "
            f"Serie de Facturación Digital activa para '{company}'.",
            title="Serie de Facturación No Encontrada"
        )

    series_doc = frappe.get_doc("VE Digital Billing Series", row[0]["series_name"])
    branch_code: str = row[0]["branch_code"] or ""
    return series_doc, branch_code


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


def assign_bill_no_from_digital_series(doc: object, series: object) -> None:
    """
    Asigna el número de factura (bill_no) desde invoice_number_correlative
    de la serie digital. Se invoca exclusivamente desde el botón de envío a HKA.

    - bill_no siempre se sobreescribe (incluye números previos del flujo legacy).
    - bill_control se limpia para que HKA asigne el número de control correcto.
    - El invoice_number_correlative es independiente del número de control HKA.
    """
    bill_no: int = series.invoice_number_correlative or 1
    bill_no_str: str = str(bill_no)

    # Limpiar bill_control previo para que no quede desincronizado con el nuevo bill_no
    doc.db_set("bill_control", "", update_modified=False)
    doc.db_set("bill_no", bill_no_str, update_modified=False)

    frappe.db.set_value(
        "VE Digital Billing Series",
        series.name,
        "invoice_number_correlative",
        bill_no + 1
    )

    frappe.clear_document_cache("VE Digital Billing Series", series.name)
    frappe.logger("l10n_ve").info(
        f"Factura {doc.name}: bill_no='{bill_no_str}' asignado desde serie '{series.name}'."
    )


def _update_fiscal_dates(doc: object, fecha_fiscal: str) -> None:
    """Actualiza posting_date y due_date a la fecha de envío si difieren."""
    if str(doc.posting_date) != fecha_fiscal or str(doc.due_date) != fecha_fiscal:
        doc.db_set("posting_date", fecha_fiscal, update_modified=False)
        doc.db_set("due_date", fecha_fiscal, update_modified=False)
        doc.reload()


def _ensure_bill_no(doc: object, series_doc: object) -> None:
    """Asigna bill_no desde la serie digital siempre que se presione el botón.
    Si la factura ya tenía un número previo (del flujo legacy u otra fuente),
    es sobreescrito por el correlativo de la serie HKA.
    """
    assign_bill_no_from_digital_series(doc, series_doc)
    doc.reload()


def _build_invoice_payload(
    doc: object, series_doc: object, branch_code: str
) -> tuple[dict, TFHKAPayloadBuilder]:
    """Construye el payload para HKA."""
    builder = TFHKAPayloadBuilder(
        doc, series_doc=series_doc, branch_code=branch_code
    )
    payload = builder.build_payload()
    return payload, builder


def _handle_hka_response(
    doc: object,
    invoice_name: str,
    payload: dict,
    response: dict,
    series_doc: object,
    fecha_fiscal: str,
) -> bool:
    """Procesa la respuesta de HKA: persiste datos, actualiza GL, registra log."""
    is_success = (
        response
        and not response.get("error")
        and str(response.get("codigo", "")) in ("200", "201")
    )

    if is_success:
        resultado = response.get("resultado") or {}
        control = resultado.get("numeroControl")
        numero_documento = resultado.get("numeroDocumento")

        if control:
            doc.db_set("bill_control", control, update_modified=False)
            if series_doc:
                update_billing_series_after_response(series_doc, control)

        # Auditoría: registrar si HKA confirmó un numeroDocumento diferente al bill_no asignado
        if numero_documento and numero_documento != frappe.db.get_value(
            "Sales Invoice", doc.name, "bill_no"
        ):
            frappe.logger("l10n_ve").warning(
                f"Factura {doc.name}: HKA confirmó numeroDocumento='{numero_documento}' "
                f"distinto al bill_no asignado localmente."
            )

        doc.db_set(
            "remarks",
            json.dumps(response, indent=2, ensure_ascii=False),
            update_modified=False
        )
        _sync_gl_entries_date(doc.name, fecha_fiscal)
        _log_request("Emision", doc.name, payload, response, "Success")
        frappe.db.commit()
        return True

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


def process_invoice(invoice_name: str) -> bool:
    """
    Envía una factura a TFHKA de forma síncrona.
    Retorna True si el envío fue exitoso, False en caso de error.
    """
    try:
        doc = frappe.get_doc("Sales Invoice", invoice_name)
        fecha_fiscal: str = today()

        _update_fiscal_dates(doc, fecha_fiscal)

        branch = doc.get("branch") or ""
        series_doc, branch_code = get_active_billing_series(
            company=doc.company, branch=branch
        )

        _ensure_bill_no(doc, series_doc)

        payload, builder = _build_invoice_payload(doc, series_doc, branch_code)

        if not builder.zona or not builder.nodo:
            missing = []
            if not builder.zona:
                missing.append("Zona (territory del cliente)")
            if not builder.nodo:
                missing.append("Nodo (router/nodo del servicio)")
            notes = (
                f"No se pudo resolver: {', '.join(missing)}. "
                f"Cliente: {doc.customer}, Suscripción: {doc.get('subscription') or '-'}"
            )
            _log_request("Emision", doc.name, payload,
                         {"error": True, "message": notes}, "Error", notes=notes)
            frappe.db.commit()
            return False

        client = TFHKAClient()
        response = client.emitir_documento(payload)
        return _handle_hka_response(
            doc, invoice_name, payload, response, series_doc, fecha_fiscal
        )

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
