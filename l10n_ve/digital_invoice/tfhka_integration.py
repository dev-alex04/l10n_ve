import json
import re

import frappe
from frappe.utils import flt, getdate, cint, today

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
        frappe.db.set_value(doc.doctype, doc.name, "bill_control", "", update_modified=True)
        frappe.db.set_value(doc.doctype, doc.name, "bill_no", "", update_modified=True)
        frappe.logger("l10n_ve").info(f"{doc.doctype} {doc.name}: Esperando asignación de HKA (Modo Tercero).")
        return

    # Incremento atómico para evitar condición de carrera en multiusuario.
    # Se usan sentencias explícitas en lugar de string formatting para evitar SQL injection.
    if is_nc:
        frappe.db.sql("""
            UPDATE `tabVE Digital Billing Series`
            SET credit_note_number_correlative = credit_note_number_correlative + 1
            WHERE name = %s
        """, (series.name,))
    else:
        frappe.db.sql("""
            UPDATE `tabVE Digital Billing Series`
            SET invoice_number_correlative = invoice_number_correlative + 1
            WHERE name = %s
        """, (series.name,))

    current_correlative: int = frappe.db.get_value(
        "VE Digital Billing Series", series.name, correlative_field
    ) or 2

    doc_number: int = current_correlative - 1
    doc_number_str: str = str(doc_number)

    frappe.db.set_value(doc.doctype, doc.name, "bill_control", "", update_modified=True)

    frappe.db.set_value(doc.doctype, doc.name, target_field, doc_number_str, update_modified=True)

    frappe.clear_document_cache("VE Digital Billing Series", series.name)
    frappe.logger("l10n_ve").info(
        f"{doc.doctype} {doc.name}: {target_field}='{doc_number_str}' asignado desde serie '{series.name}'."
    )


def _compute_tasa_fecha(doc: object) -> str:
    """
    Calcula la fecha de la tasa BCV a partir del posting_date ORIGINAL del documento
    (antes de que sea actualizado a la fecha de certificación HKA).

    - Jurídico: fecha exacta del posting_date.
    - Natural:   primer día del mes del posting_date.
    """
    fecha_base = getdate(doc.posting_date)
    if not is_juridical_customer(doc.customer):
        fecha_base = fecha_base.replace(day=1)
    return str(fecha_base)


def _validate_tasa_coherencia(doc: object, tasa_fecha: str) -> None:
    """
    Verifica que la tasa de cambio registrada en el documento coincida
    con la tasa BCV de Currency Exchange para la fecha calculada.

    Si no existe tasa registrada para esa fecha, o si la tasa del documento
    difiere de la registrada, se lanza un error bloqueando el envío a HKA.
    """
    if not flt(doc.conversion_rate):
        return

    company_currency: str = frappe.get_cached_value(
        "Company", doc.company, "default_currency"
    ) or "VEF"

    tasa_registrada: float = frappe.db.get_value(
        "Currency Exchange",
        {
            "date": tasa_fecha,
            "from_currency": doc.currency,
            "to_currency": company_currency,
        },
        "exchange_rate",
        order_by="modified desc",
    )

    fecha_display: str = getdate(tasa_fecha).strftime("%d/%m/%Y")

    if not tasa_registrada or flt(tasa_registrada) <= 0:
        frappe.throw(
            f"No existe tasa de cambio BCV registrada para el {fecha_display} "
            f"({doc.currency} → {company_currency}). "
            "Registre la tasa antes de enviar este documento a la imprenta digital.",
            title="Tasa de Cambio No Encontrada",
        )

    if flt(tasa_registrada, 4) != flt(doc.conversion_rate, 4):
        frappe.throw(
            f"La tasa del documento ({flt(doc.conversion_rate, 4)}) no coincide con la "
            f"tasa BCV registrada para el {fecha_display} ({flt(tasa_registrada, 4)}). "
            "Corrija la tasa antes de enviar este documento a la imprenta digital.",
            title="Tasa de Cambio Incorrecta",
        )


def _update_fiscal_dates(doc: object, fecha_hka: str) -> None:
    """
    Actualiza posting_date y due_date al día de certificación ante HKA.
    Así los registros en Frappe coinciden con la Fecha de Emisión
    que HKA asigna en el documento impreso.
    """
    cambios: dict = {}
    if str(doc.posting_date or "") != fecha_hka:
        cambios["posting_date"] = fecha_hka
    if str(doc.due_date or "") != fecha_hka:
        cambios["due_date"] = fecha_hka
    if cambios:
        frappe.db.set_value(doc.doctype, doc.name, cambios, update_modified=True)
        doc.reload()


def _sync_gl_entries_date(voucher_no: str, new_date: str, doctype: str = "Sales Invoice") -> None:
    """
    Sincroniza las fechas de los asientos contables (GL Entries),
    cronograma de pagos (Payment Schedule) e historial de pagos
    (Payment Ledger Entry) con la fecha de certificación HKA.
    Soporta tanto Sales Invoice como VE Sales Credit Note.
    """
    try:
        frappe.db.sql("""
            UPDATE `tabGL Entry`
            SET posting_date = %s
            WHERE voucher_type = %s
              AND voucher_no   = %s
        """, (new_date, doctype, voucher_no))

        frappe.db.sql("""
            UPDATE `tabPayment Schedule`
            SET due_date = %s
            WHERE parent     = %s
              AND parenttype = %s
        """, (new_date, voucher_no, doctype))

        frappe.db.sql("""
            UPDATE `tabPayment Ledger Entry`
            SET posting_date = %s,
                due_date     = %s
            WHERE voucher_type = %s
              AND voucher_no   = %s
        """, (new_date, new_date, doctype, voucher_no))

    except Exception as e:
        tb: str = frappe.get_traceback(with_context=True) or str(e)
        frappe.logger("l10n_ve").error(
            f"Error sincronizando asientos contables de {voucher_no}: {str(e)}"
        )
        _log_request(
            "GL Sync",
            voucher_no,
            {},
            {"error": True, "message": str(e)},
            "Error",
            notes=tb,
            doctype=doctype,
        )


def _ensure_bill_no(doc: object, series_doc: object) -> None:
    """Asigna bill_no desde la serie digital siempre que se presione el botón.
    Si la factura ya tenía un número previo (del flujo legacy u otra fuente),
    es sobreescrito por el correlativo de la serie HKA.
    """
    assign_bill_no_from_digital_series(doc, series_doc)
    doc.reload()


def _build_invoice_payload(
    doc: object, series_doc: object, branch_code: str, tasa_fecha: str = ""
) -> tuple[dict, TFHKAPayloadBuilder]:
    """Construye el payload para HKA."""
    builder = TFHKAPayloadBuilder(
        doc, series_doc=series_doc, branch_code=branch_code, tasa_fecha=tasa_fecha or None
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
                frappe.db.set_value(
                    doc.doctype, doc.name, target_field,
                    numero_documento, update_modified=True
                )

        if control:
            frappe.db.set_value(
                doc.doctype, doc.name, "bill_control",
                control, update_modified=True
            )

        # Auditoría: verificar si HKA confirmó un número distinto al asignado localmente
        local_number = frappe.db.get_value(doc.doctype, doc.name, target_field)
        if numero_documento and numero_documento != local_number:
            frappe.logger("l10n_ve").warning(
                f"{doc.doctype} {doc.name}: HKA confirmó numeroDocumento='{numero_documento}' "
                f"distinto al {target_field} asignado localmente ('{local_number}')."
            )

        fecha_hka: str = today()
        _sync_gl_entries_date(doc.name, fecha_hka, doc.doctype)

        frappe.db.set_value(
            doc.doctype, doc.name, "remarks",
            json.dumps(response, indent=2, ensure_ascii=False),
            update_modified=True
        )
        _log_request("Emision", doc.name, payload, response, "Success", doctype=doc.doctype)
        return True

    # Respuesta nula (timeout, error de red, etc.): response.get() fallaría con AttributeError
    if not response:
        _log_request("Emision", doc.name, payload, {}, "Error",
                     notes="La API HKA no devolvió respuesta (timeout o error de conexión).",
                     doctype=doc.doctype)
        return False

    validaciones = response.get("validaciones") or []
    mensaje = response.get("mensaje") or response.get("message") or ""
    notes_parts = []
    if mensaje:
        notes_parts.append(f"Mensaje: {mensaje}")
    if validaciones:
        notes_parts.append("Validaciones: " + "; ".join(str(v) for v in validaciones))
    _log_request("Emision", doc.name, payload, response, "Error",
                 notes="\n".join(notes_parts), doctype=doc.doctype)
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

        # Calcular la fecha real de la tasa BCV ANTES de actualizar posting_date.
        # Funciona para facturas nuevas y para las ya existentes acumuladas.
        tasa_fecha: str = _compute_tasa_fecha(doc)

        # Verificar que la tasa del documento coincida con la BCV registrada.
        # Lanza error si no existe tasa o si hay desajuste, antes de tocar nada.
        # La NC se omite: su tasa es heredada de la factura original y puede
        # corresponder a una fecha distinta sin ser un error.
        if not is_nc:
            _validate_tasa_coherencia(doc, tasa_fecha)

        fecha_hka: str = today()
        _update_fiscal_dates(doc, fecha_hka)

        branch = doc.get("branch") or ""
        series_doc, branch_code = get_active_billing_series(
            company=doc.company, branch=branch
        )

        _ensure_bill_no(doc, series_doc)

        payload, builder = _build_invoice_payload(doc, series_doc, branch_code, tasa_fecha)

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


# ---------------------------------------------------------------------------
# Scheduler: envío automático de facturas pendientes a HKA
# ---------------------------------------------------------------------------

_TFHKA_BATCH_SIZE: int = 100
_TFHKA_DELAY_BETWEEN_CALLS: float = 0.5


def _hka_log(description: str, status: str = "Info") -> None:
    """Registra un evento del cron HKA en VE Digital Invoice Log."""
    _create_log_entry({
        "document_type": "Sales Invoice",
        "endpoint": "HKA Cron",
        "status": status,
        "notes": description,
    })


def send_pending_invoices_to_hka() -> None:
    """Envía facturas pagadas pendientes a HKA (scheduler cada 5 min).

    Recorre cada serie de facturación digital activa y procesa por sucursal.

    Comportamiento según modo de operación:
      - Internal:    STOP on error (proteger correlativo local de saltos).
      - Third Party: CONTINUE on error (HKA controla la numeración).

    Respeta el flag 'enabled' y 'cutoff_date' de TFHKA Settings.
    """
    import time

    tfhka_settings: dict | None = _get_tfhka_settings()
    if not tfhka_settings:
        return

    if not tfhka_settings.get("enable_auto_send"):
        return

    from datetime import datetime
    actual_date: int = datetime.now().hour
    if not (5 <= actual_date < 21):
        return

    cutoff_date: str = tfhka_settings["cutoff_date"]
    active_series: list[dict] = _get_active_billing_series()

    if not active_series:
        return

    _sanitize_customer_master_data()

    total_success: int = 0
    total_errors: int = 0
    success_invoices: list[str] = []
    error_invoices: list[str] = []

    for series in active_series:
        stop_on_error: bool = series["operation_mode"] == "Internal"
        branches: list[str] = series["branches"]

        if not branches:
            continue

        pending: list[str] = _get_pending_hka_invoices(
            branches=branches,
            cutoff_date=cutoff_date,
        )

        if not pending:
            continue

        _hka_log(
            f"Serie {series['name']} ({series['operation_mode']}): "
            f"{len(pending)} facturas pendientes en {len(branches)} sucursal(es).",
            "Success",
        )

        series_stopped: bool = False
        for invoice_name in pending:

            try:

                result: bool = process_invoice(invoice_name)

                if result:
                    total_success += 1
                    success_invoices.append(invoice_name)
                    frappe.db.commit()

                else:

                    total_errors += 1
                    error_invoices.append(invoice_name)
                    frappe.db.commit()
                    if stop_on_error:
                        _hka_log(
                            f"STOP en serie {series['name']} (Internal): "
                            f"factura {invoice_name} falló.",
                            "Error",
                        )
                        series_stopped = True
                        break

            except Exception as e:

                total_errors += 1
                error_invoices.append(invoice_name)
                frappe.db.rollback()
                _hka_log(
                    f"Error enviando {invoice_name}: {str(e)}",
                    "Error",
                )

                if stop_on_error:
                    _hka_log(
                        f"STOP en serie {series['name']} (Internal): "
                        f"excepción en {invoice_name}.",
                        "Error",
                    )
                    series_stopped = True
                    break

            time.sleep(_TFHKA_DELAY_BETWEEN_CALLS)

        if series_stopped:
            continue

    if total_success or total_errors:
        lines: list[str] = [
            f"Completado: {total_success} exitosas, {total_errors} con error.",
        ]
        if success_invoices:
            lines.append(f"Exitosas: {', '.join(success_invoices)}")
        if error_invoices:
            lines.append(f"Con error: {', '.join(error_invoices)}")

        _hka_log(
            "\n".join(lines),
            "Success" if total_errors == 0 else "Error",
        )

    _repair_partial_hka_invoices()


def _sanitize_customer_master_data() -> None:
    """Limpia caracteres de control (tabs, saltos de línea) en nombres de clientes.

    Se ejecuta antes del envío a HKA para prevenir errores de validación
    en el campo RazonSocial.
    """
    dirty_customers: list[dict] = frappe.db.sql("""
        SELECT name, customer_name
        FROM `tabCustomer`
        WHERE customer_name LIKE '%%\t%%'
           OR customer_name LIKE '%%\n%%'
           OR customer_name LIKE '%%\r%%'
    """, as_dict=True)

    if not dirty_customers:
        return

    for customer in dirty_customers:
        clean_name: str = " ".join(customer.customer_name.split()).strip()
        if clean_name != customer.customer_name:
            frappe.db.set_value(
                "Customer", customer.name,
                "customer_name", clean_name,
                update_modified=False,
            )

    frappe.db.commit()
    frappe.logger("l10n_ve").info(
        f"Sanitización de datos maestros: {len(dirty_customers)} cliente(s) limpiado(s)."
    )


def _repair_partial_hka_invoices() -> None:
    """Repara facturas con datos HKA incompletos (bill_no sin bill_control o viceversa).

    Busca en los logs de error el response de HKA (código 200) para extraer
    los valores faltantes. Esto cubre casos de timeout/deadlock donde HKA
    procesó la factura pero la escritura local fue interrumpida.
    """

    partial_invoices: list[dict] = frappe.db.sql("""
        SELECT name, bill_no, bill_control
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND (
            (bill_no != '' AND bill_no IS NOT NULL AND (bill_control = '' OR bill_control IS NULL))
            OR
            (bill_control != '' AND bill_control IS NOT NULL AND (bill_no = '' OR bill_no IS NULL))
          )
    """, as_dict=True)

    if not partial_invoices:
        return

    repaired: int = 0
    for inv in partial_invoices:
        error_log: str = frappe.db.get_value(
            "VE Digital Invoice Log",
            {
                "sales_invoice": inv.name,
                "status": "Error",
                "document_type": "Sales Invoice",
            },
            "notes",
            order_by="creation desc"
        ) or ""

        if "'codigo': '200'" not in error_log:
            continue

        updates: dict = {}

        if not inv.bill_control:
            match = re.search(r"'numeroControl':\s*'([^']+)'", error_log)
            if match:
                updates["bill_control"] = match.group(1)

        if not inv.bill_no:
            match = re.search(r"'numeroDocumento':\s*'([^']+)'", error_log)
            if match:
                updates["bill_no"] = match.group(1)

        if updates:
            frappe.db.set_value("Sales Invoice", inv.name, updates, update_modified=True)
            _log_request(
                "Reparacion", inv.name, {},
                {"reparado": updates}, "Success",
                notes=f"Datos HKA recuperados del log de error: {updates}",
            )
            repaired += 1

    if repaired:
        frappe.db.commit()
        frappe.logger("tfhka").info(
            f"Reparación automática: {repaired} factura(s) con datos HKA incompletos corregidas"
        )


def _get_tfhka_settings() -> dict | None:
    """Obtiene la configuración de TFHKA. Retorna None si está deshabilitado."""
    try:
        settings: dict = frappe.get_cached_value(
            "TFHKA Settings", "TFHKA Settings",
            ["enabled", "enable_auto_send", "cutoff_date"],
            as_dict=True,
        ) or {}

        if not settings.get("enabled"):
            return None

        return {
            "cutoff_date": str(settings.get("cutoff_date") or "2026-04-01"),
            "enable_auto_send": bool(settings.get("enable_auto_send")),
        }
    except Exception:
        return None


def _get_active_billing_series() -> list[dict]:
    """Obtiene las series activas con sus sucursales y modo de operación."""
    series_list: list[dict] = frappe.get_all(
        "VE Digital Billing Series",
        filters={"status": "Active"},
        fields=["name", "operation_mode", "company"],
    )

    result: list[dict] = []
    for series in series_list:
        branches: list[str] = [
            row.branch for row in frappe.get_all(
                "VE Digital Billing Series Branch",
                filters={"parent": series["name"]},
                fields=["branch"],
            ) if row.branch
        ]
        result.append({
            "name": series["name"],
            "operation_mode": series["operation_mode"],
            "company": series["company"],
            "branches": branches,
        })

    return result


def _get_pending_hka_invoices(
    branches: list[str],
    cutoff_date: str = "2026-04-01",
) -> list[str]:
    """Obtiene facturas pagadas pendientes de envío a HKA para sucursales específicas."""
    if not branches:
        return []

    placeholders: str = ", ".join(["%s"] * len(branches))
    params: list = branches + [cutoff_date, _TFHKA_BATCH_SIZE]

    results = frappe.db.sql(f"""
        SELECT si.name
        FROM `tabSales Invoice` si
        LEFT JOIN `tabVE Digital Invoice Log` log
            ON log.sales_invoice = si.name
            AND log.status = 'Success'
            AND log.document_type = 'Sales Invoice'
        WHERE si.branch IN ({placeholders})
          AND si.posting_date >= %s
          AND si.docstatus = 1
          AND si.status = 'Paid'
          AND si.is_return = 0
          AND si.is_debit_note = 0
          AND (si.bill_control IS NULL OR si.bill_control = '')
          AND log.name IS NULL
        ORDER BY si.posting_date, si.name
        LIMIT %s
    """, params, as_list=True)

    return [r[0] for r in results]
