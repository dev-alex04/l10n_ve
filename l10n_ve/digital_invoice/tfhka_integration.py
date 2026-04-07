import json

import frappe
from frappe.utils import flt, getdate, cint

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient
from l10n_ve.utils.utils import is_juridical_customer

SUPPORTED_DOCTYPES = ("Sales Invoice", "VE Sales Credit Note")

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
    Asigna el número de documento desde el correlativo de la serie digital.
    Para Sales Invoice usa invoice_number_correlative → bill_no.
    Para VE Sales Credit Note usa credit_note_number_correlative → bill_no.
    Se invoca exclusivamente desde el botón de envío a HKA.
    """
    is_nc: bool = doc.doctype == "VE Sales Credit Note"
    correlative_field: str = "credit_note_number_correlative" if is_nc else "invoice_number_correlative"
    target_field: str = "bill_no"

    if getattr(series, "operation_mode", "Internal") == "Third Party":
        doc.db_set("bill_control", "", update_modified=False)
        doc.db_set("bill_no", "", update_modified=False)
        frappe.logger("l10n_ve").info(f"{doc.doctype} {doc.name}: Esperando asignación de HKA (Modo Tercero).")
        return

    # Incremento atómico para evitar condición de carrera en multiusuario.
    frappe.db.sql("""
        UPDATE `tabVE Digital Billing Series`
        SET {field} = {field} + 1
        WHERE name = %s
    """.format(field=correlative_field), (series.name,))

    current_correlative: int = frappe.db.get_value(
        "VE Digital Billing Series", series.name, correlative_field
    ) or 2

    doc_number: int = current_correlative - 1
    doc_number_str: str = str(doc_number)

    doc.db_set("bill_control", "", update_modified=False)

    doc.db_set(target_field, doc_number_str, update_modified=False)

    frappe.clear_document_cache("VE Digital Billing Series", series.name)
    frappe.logger("l10n_ve").info(
        f"{doc.doctype} {doc.name}: {target_field}='{doc_number_str}' asignado desde serie '{series.name}'."
    )






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
) -> bool:
    """Procesa la respuesta de HKA: persiste datos y registra log."""
    is_success = (
        response
        and not response.get("error")
        and str(response.get("codigo", "")) in ("200", "201")
    )
    target_field: str = "bill_no"

    if is_success:
        resultado = response.get("resultado") or {}
        control = resultado.get("numeroControl")
        numero_documento = resultado.get("numeroDocumento")

        if getattr(series_doc, "operation_mode", "Internal") == "Third Party":
            if numero_documento:
                doc.db_set(target_field, numero_documento, update_modified=False)

        if control:
            doc.db_set("bill_control", control, update_modified=False)
            if series_doc:
                update_billing_series_after_response(series_doc, control)

        # Auditoría: verificar si HKA confirmó un número distinto al asignado localmente
        local_number = frappe.db.get_value(doc.doctype, doc.name, target_field)
        if numero_documento and numero_documento != local_number:
            frappe.logger("l10n_ve").warning(
                f"{doc.doctype} {doc.name}: HKA confirmó numeroDocumento='{numero_documento}' "
                f"distinto al {target_field} asignado localmente ('{local_number}')."
            )

        doc.db_set(
            "remarks",
            json.dumps(response, indent=2, ensure_ascii=False),
            update_modified=False
        )
        _log_request("Emision", doc.name, payload, response, "Success", doctype=doc.doctype)
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
                 notes="\n".join(notes_parts), doctype=doc.doctype)
    frappe.db.commit()
    return False


@frappe.whitelist()
def process_invoice(doc_name: str, doctype: str = "Sales Invoice") -> bool:
    """
    Envía una factura o nota de crédito a TFHKA de forma síncrona.
    Soporta: Sales Invoice, VE Sales Credit Note.
    Retorna True si el envío fue exitoso, False en caso de error.
    """
    if doctype not in SUPPORTED_DOCTYPES:
        frappe.throw(
            f"DocType '{doctype}' no es compatible con la facturación digital.",
            title="DocType No Soportado"
        )

    is_nc: bool = doctype == "VE Sales Credit Note"

    try:
        doc = frappe.get_doc(doctype, doc_name)

        if str(doc.due_date or "") != str(doc.posting_date or ""):
            doc.db_set("due_date", doc.posting_date, update_modified=False)

        branch = doc.get("branch") or ""
        series_doc, branch_code = get_active_billing_series(
            company=doc.company, branch=branch
        )

        _ensure_bill_no(doc, series_doc)

        payload, builder = _build_invoice_payload(doc, series_doc, branch_code)

        # Para NC no se valida zona/nodo (no tiene suscripción asociada)
        if not is_nc:
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
            doc, doc_name, payload, response, series_doc
        )

    except frappe.ValidationError:
        raise
    except Exception as e:
        tb: str = frappe.get_traceback(with_context=True) or str(e)
        frappe.logger("l10n_ve").error(f"Error procesando {doctype} {doc_name}: {tb}")
        _log_request(
            "Emision",
            doc_name,
            payload if "payload" in locals() else {},
            {"error": True, "message": str(e)},
            "Error",
            notes=tb,
            doctype=doctype,
        )
        frappe.db.commit()
        return False


def _log_request(
    endpoint: str,
    invoice_name: str,
    payload: dict,
    response: dict,
    status: str,
    notes: str = "",
    doctype: str = "Sales Invoice",
) -> None:
    """Registra el log de la solicitud."""
    log_data: dict = {
        "document_type": doctype,
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
    """Método invocado mediante botón JS para reenvío manual de Sales Invoice."""
    frappe.has_permission("Sales Invoice", "submit", doc=invoice_name, throw=True)
    success = process_invoice(invoice_name, doctype="Sales Invoice")
    return "Sent" if success else "Error"


@frappe.whitelist()
def get_invoice_preview_data(invoice_name: str) -> dict:
    """
    Devuelve todos los datos para la vista previa del modal de facturación digital.
    Es 100% read-only: no asigna números, no modifica la DB, no envía a HKA.
    Los números de documento y control son proyectados (último + 1).
    """
    from l10n_ve.digital_invoice.payload_builder import clean_address as _clean_address

    frappe.has_permission("Sales Invoice", "submit", doc=invoice_name, throw=True)

    doc = frappe.get_doc("Sales Invoice", invoice_name)
    branch: str = doc.get("branch") or ""
    series_doc, branch_code = get_active_billing_series(
        company=doc.company, branch=branch
    )

    company = frappe.get_cached_doc("Company", doc.company)
    customer = frappe.get_cached_doc("Customer", doc.customer)

    if getattr(series_doc, "operation_mode", "Internal") == "Third Party":
        bill_no_preview = "Asignado por HKA"
    else:
        bill_no_preview = str(series_doc.invoice_number_correlative or 1)

    last_ctrl: int = series_doc.last_control_number or (series_doc.range_from - 1)
    prefix: str = series_doc.prefix or "00"
    control_no_preview: str = f"{prefix}-{str(last_ctrl + 1).zfill(8)}"

    range_from_str: str = f"{prefix}-{str(series_doc.range_from).zfill(8)}"
    range_to_str: str = f"{prefix}-{str(series_doc.range_to).zfill(8)}"

    fecha_posting = getdate(doc.posting_date)
    fecha_emision: str = fecha_posting.strftime("%d/%m/%Y")
    hora_emision: str = str(doc.posting_time or "")[:8] or "00:00:00"
    fecha_vencimiento: str = getdate(doc.due_date).strftime("%d/%m/%Y") if doc.due_date else fecha_emision

    company_address: str = ""
    try:
        address_name = frappe.db.get_value(
            "Dynamic Link",
            {"link_doctype": "Company", "link_name": doc.company, "parenttype": "Address"},
            "parent"
        )
        if address_name:
            addr = frappe.get_cached_doc("Address", address_name)
            company_address = _clean_address(addr.address_display or "")
    except Exception:
        pass

    customer_address: str = _clean_address(doc.address_display) if doc.address_display else ""

    tc: float = flt(doc.conversion_rate) if doc.conversion_rate else 1.0
    if is_juridical_customer(doc.customer):
        fecha_bcv = getdate(doc.posting_date)
    else:
        fecha_bcv = getdate(doc.posting_date).replace(day=1)

    zona: str = customer.territory or ""
    nodo: str = ""
    subscription_name: str = doc.get("subscription") or ""
    if subscription_name:
        service_row = next(
            (r for r in (customer.get("internet_services") or [])
             if r.subscription == subscription_name),
            None
        )
        if service_row and service_row.router:
            nodo = frappe.db.get_value(
                "ISP Node Routers", {"router": service_row.router}, "parent"
            ) or ""

    meses = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO",
             "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    fecha_contab = getdate(doc.posting_date)
    periodo: str = f"{meses[fecha_contab.month]} {fecha_contab.year}"
    if subscription_name:
        try:
            sub = frappe.get_cached_doc("Subscription", subscription_name)
            if sub.current_invoice_start and sub.current_invoice_end:
                inicio = getdate(sub.current_invoice_start).strftime("%d/%m/%Y")
                fin = getdate(sub.current_invoice_end).strftime("%d/%m/%Y")
                periodo = f"Desde {inicio} hasta {fin}"
        except Exception:
            pass

    iva_rate: float = 16.0
    has_iva: bool = flt(doc.base_total_taxes_and_charges) > 0
    for tax in doc.get("taxes", []):
        al = (tax.get("account_head") or "").lower()
        dl = (tax.get("description") or "").lower()
        if ("iva" in al or "iva" in dl) and flt(tax.rate) > 0:
            iva_rate = flt(tax.rate)
            break

    items_data = []
    for item in doc.items:
        is_exempt = bool(item.get("is_exempt", 0) or item.get("vat_exempt", 0) or not has_iva)
        item_amount = flt(item.amount)
        valor_iva = 0.0 if is_exempt else round(item_amount * (iva_rate / 100), 2)
        items_data.append({
            "code": item.item_code or "",
            "description": item.item_name or "",
            "qty": str(cint(item.qty)) if item.qty == cint(item.qty) else str(item.qty),
            "rate_usd": "{:.2f}".format(flt(item.rate)),
            "iva_rate": "{:.0f}".format(0.0 if is_exempt else iva_rate),
            "is_exempt": is_exempt,
            "valor_iva_usd": "{:.2f}".format(valor_iva),
            "total_item_usd": "{:.2f}".format(item_amount + valor_iva),
        })

    def fmt(v: float) -> str:
        return "{:,.2f}".format(v)

    # Totales fiscales para HKA (igual que payload_builder):
    # IVA bruto completo, sin descontar retenciones de IVA ni ISLR.
    subtotal_usd: float = flt(doc.total)
    iva_usd: float = 0.0
    if has_iva:
        for item in doc.items:
            is_exempt_item = bool(item.get("is_exempt", 0) or item.get("vat_exempt", 0))
            if not is_exempt_item:
                iva_usd += round(flt(item.amount) * (iva_rate / 100), 2)
    total_usd: float = subtotal_usd + iva_usd

    return {
        "total_usd": fmt(total_usd),
        "total_bs": fmt(round(total_usd * tc, 2)),
        "currency": doc.currency,
        "bill_no_preview": bill_no_preview,
        "control_no_preview": control_no_preview,
        "fecha_emision": fecha_emision,
        "hora_emision": hora_emision,
        "fecha_vencimiento": fecha_vencimiento,
        "fecha_asignacion": fecha_emision,
        "serie_tfhka": getattr(series_doc, "serie", ""),
        "branch_code": branch_code,
        "range_from": range_from_str,
        "range_to": range_to_str,
        "company_name": company.company_name,
        "company_tax_id": company.tax_id or "",
        "company_address": company_address,
        "company_phone": company.phone_no or "",
        "company_website": company.website or "",
        "customer_name": customer.customer_name,
        "customer_tax_id": customer.tax_id or "",
        "customer_address": customer_address,
        "customer_phone": doc.contact_mobile or "",
        "customer_email": doc.contact_email or "",
        "id_servicio": customer.tax_id or "",
        "zona": zona,
        "nodo": nodo,
        "periodo": periodo,
        "tasa_bcv": "{:.4f}".format(tc),
        "tasa_fecha": fecha_bcv.strftime("%d/%m/%Y"),
        "items": items_data,
        "subtotal_usd": fmt(subtotal_usd),
        "iva_usd": fmt(iva_usd),
        "subtotal_bs": fmt(round(subtotal_usd * tc, 2)),
        "iva_bs": fmt(round(iva_usd * tc, 2)),
        "invoice_name": invoice_name,
    }
