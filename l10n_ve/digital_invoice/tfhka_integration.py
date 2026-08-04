import json
import re
import time

import frappe
from frappe.utils import flt, getdate, cint, today

from l10n_ve.digital_invoice.emission_rerate import (
    _blocking_condition,
    rerate_juridical_before_submit,
    target_rate_before_submit,
    _get_target_rate,
    rerate_to_emission_rate,
    validate_note_rate,
)
from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder, resolve_zone_from_address
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient
from l10n_ve.utils.utils import is_juridical_customer, resolve_exchange_rate_date

SUPPORTED_DOCTYPES = ("Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note")

_RANGE_EXHAUSTED_KEYWORDS = ("rango de numeración", "rango de numeracion")


class HKARangeExhausted(Exception):
    """Error fatal de serie: HKA no tiene rango de numeración disponible."""
    pass


class HKAAmountMismatchError(frappe.ValidationError):
    """Los montos del payload no coinciden con los de la factura."""
    pass

def get_active_billing_series(
    company: str, branch: str
) -> tuple[object, str]:
    """
    Retorna (series_doc, branch_code) buscando la sucursal de la factura
    en la tabla hija 'VE Digital Billing Series Branch'.

    - Si la sucursal no está en ninguna serie activa de la empresa → throw.
    - Si la factura no tiene sucursal, busca la primera serie activa de la empresa.

    El branch_code se obtiene directamente de la fila de la tabla hija.
    """
    if not branch or branch.upper() == "N/A":
        return None, ""

    row = frappe.db.sql("""
        SELECT
            child.parent       AS series_name,
            child.branch_code  AS branch_code
        FROM `tabVE Digital Billing Series Branch` child
        INNER JOIN `tabVE Digital Billing Series` serie
            ON serie.name = child.parent
        WHERE child.branch = %s
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


def has_active_digital_series(company: str, branch: str | None) -> bool:
    """Retorna True si la sucursal tiene una serie digital activa (no lanza).

    Variante segura de get_active_billing_series para detección en submit:
    con TFHKA deshabilitado, o sucursal no configurada retorna False.
    """
    try:
        enabled = frappe.get_cached_value("TFHKA Settings", "TFHKA Settings", "enabled")
    except Exception:
        return False

    if not enabled:
        return False

    if not branch or branch.upper() == "N/A":
        return False

    row = frappe.db.sql("""
        SELECT child.parent
        FROM `tabVE Digital Billing Series Branch` child
        INNER JOIN `tabVE Digital Billing Series` serie
            ON serie.name = child.parent
        WHERE child.branch  = %s
          AND serie.company = %s
          AND serie.status  = 'Active'
        LIMIT 1
    """, (branch, company), as_dict=True)

    return bool(row)


def _set_hka_status(doctype: str, name: str, status: str, serie: str | None = None) -> None:
    """Persiste el estado fiscal HKA del documento (y la serie si se provee).

    Escritura directa vía db.set_value (documentos submitted, mismo patrón que
    el resto del flujo). update_modified=False: es metadato de integración,
    no una edición del documento.
    """
    values: dict = {"hka_status": status}
    if serie:
        values["hka_series"] = serie
    frappe.db.set_value(doctype, name, values, update_modified=False)




def assign_bill_no_from_digital_series(doc: object, series: object) -> None:
    """
    Asigna el número de documento desde el correlativo de la serie digital.
    Para Sales Invoice usa invoice_number_correlative → bill_no.
    Para VE Sales Credit Note usa credit_note_number_correlative → bill_no.
    Para VE Sales Debit Note usa debit_note_number_correlative → bill_no.
    Se invoca exclusivamente desde el botón de envío a HKA.
    """
    is_nc: bool = doc.doctype == "VE Sales Credit Note"
    is_nd: bool = doc.doctype == "VE Sales Debit Note"

    if is_nc:
        correlative_field: str = "credit_note_number_correlative"
    elif is_nd:
        correlative_field: str = "debit_note_number_correlative"
    else:
        correlative_field: str = "invoice_number_correlative"

    target_field: str = "bill_no"

    if getattr(series, "operation_mode", "Internal") == "Third Party":
        frappe.db.set_value(doc.doctype, doc.name, "bill_control", "", update_modified=True)
        frappe.db.set_value(doc.doctype, doc.name, "bill_no", "", update_modified=True)
        frappe.logger("l10n_ve").info(f"{doc.doctype} {doc.name}: Esperando asignación de HKA (Modo Tercero).")
        return

    # Incremento atómico para evitar condición de carrera en multiusuario.
    if is_nc:
        frappe.db.sql("""
            UPDATE `tabVE Digital Billing Series`
            SET credit_note_number_correlative = credit_note_number_correlative + 1
            WHERE name = %s
        """, (series.name,))
    elif is_nd:
        frappe.db.sql("""
            UPDATE `tabVE Digital Billing Series`
            SET debit_note_number_correlative = debit_note_number_correlative + 1
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
    Calcula la fecha de la tasa BCV que debe mostrar el documento impreso.

    Para los dos tipos se usa la fecha REAL de la tasa que porta el documento
    (lookup inverso en Currency Exchange sobre conversion_rate). No puede
    inferirse del posting_date: la tasa se actualiza al aprobar la factura
    (rerate_juridical_before_submit), que puede ocurrir en un mes posterior al
    de generada.

    El natural usaba el primer día del mes del posting_date, y eso se rompió
    cuando la tasa pasó a anclarse en el mes EN CURSO y no en el de la factura:
    una de julio emitida en agosto porta la tasa del 1° de agosto, y el
    posting_date todavía dice julio hasta que la certificación lo mueve. Imprimir
    "de fecha valor 01/07" sobre una tasa del 01/08 es justo la incoherencia que
    _validate_tasa_coherencia existe para frenar.

    Fallback: posting_date si ninguna fila coincide.

    Se calcula ANTES de que posting_date sea actualizado a la fecha de
    certificación HKA.
    """
    fecha_base = getdate(doc.posting_date)
    rate_date = resolve_exchange_rate_date(flt(doc.conversion_rate), doc.currency)
    if rate_date:
        return rate_date

    if not is_juridical_customer(doc.customer):
        return str(fecha_base.replace(day=1))
    return str(fecha_base)


def _validate_tasa_coherencia(doc: object, tasa_fecha: str) -> None:
    """
    Verifica que la tasa de cambio registrada en el documento coincida
    con la tasa BCV de Currency Exchange para la fecha que se va a IMPRIMIR
    en el texto "de fecha valor DD/MM/YYYY" del documento fiscal.

    Si no existe tasa registrada para esa fecha, o si la tasa del documento
    difiere de la registrada, se lanza un error bloqueando el envío a HKA:
    mejor bloquear que certificar un par tasa/fecha inconsistente ante SENIAT.
    """
    if not flt(doc.conversion_rate):
        return

    company_currency: str = frappe.get_cached_value(
        "Company", doc.company, "default_currency"
    ) or "VEF"

    # Documento en la moneda de la empresa (tasa 1.0): no hay cruce de moneda
    # que validar y Currency Exchange no registra filas VEF→VEF.
    if doc.currency == company_currency:
        return

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



_AMOUNT_TOLERANCE: float = 0.02


def _validate_invoice_integrity(doc: object) -> list[str]:
    """Valida consistencia interna de los campos base_* de la factura.

    Retorna lista de errores encontrados (vacía = OK).
    """
    errors: list[str] = []
    base_net_total: float = flt(doc.base_net_total)

    if not base_net_total:
        errors.append(
            f"base_net_total está vacío o es cero ({base_net_total})"
        )
        return errors

    items_base_sum: float = sum(
        flt(item.base_net_amount) for item in doc.items
    )
    diff_items: float = abs(items_base_sum - base_net_total)
    if diff_items > _AMOUNT_TOLERANCE:
        errors.append(
            f"Σ items.base_net_amount = {items_base_sum:.2f} ≠ "
            f"base_net_total = {base_net_total:.2f} "
            f"(diferencia: {diff_items:.2f} VEF)"
        )

    for tax in doc.get("taxes", []):
        if tax.get("charge_type") != "VAT" or flt(tax.rate) <= 0:
            continue
        if not flt(tax.base_tax_amount):
            errors.append(
                f"IVA '{tax.description}': base_tax_amount está vacío o es cero"
            )

    return errors


def _compare_totales_section(
    payload_totales: dict,
    expected: dict[str, float],
    currency_label: str,
) -> list[str]:
    """Compara un dict de totales del payload contra valores esperados.

    Retorna lista de errores con prefijo [currency_label].
    Valida tanto campo-a-campo como aritmética interna.
    """
    errors: list[str] = []

    for field, expected_val in expected.items():
        payload_val: float = flt(payload_totales.get(field, 0))
        diff: float = abs(payload_val - expected_val)
        if diff > _AMOUNT_TOLERANCE:
            errors.append(
                f"[{currency_label}] {field}: payload={payload_val:.2f}, "
                f"factura={expected_val:.2f} "
                f"(Δ {diff:.2f})"
            )

    # Aritmética interna del payload
    gravado: float = flt(payload_totales.get("montoGravadoTotal", 0))
    exento: float = flt(payload_totales.get("montoExentoTotal", 0))
    subtotal: float = flt(payload_totales.get("subtotal", 0))
    iva: float = flt(payload_totales.get("totalIVA", 0))
    total: float = flt(payload_totales.get("montoTotalConIVA", 0))

    if abs((gravado + exento) - subtotal) > _AMOUNT_TOLERANCE:
        errors.append(
            f"[{currency_label}] Aritmética: Gravado({gravado:.2f}) + "
            f"Exento({exento:.2f}) = {gravado + exento:.2f} "
            f"≠ Subtotal({subtotal:.2f})"
        )
    if abs((subtotal + iva) - total) > _AMOUNT_TOLERANCE:
        errors.append(
            f"[{currency_label}] Aritmética: Subtotal({subtotal:.2f}) + "
            f"IVA({iva:.2f}) = {subtotal + iva:.2f} "
            f"≠ Total({total:.2f})"
        )

    return errors


def _build_expected_ves(doc: object) -> tuple[dict[str, float], float]:
    """Construye los valores esperados VES desde la factura.

    Retorna (expected_dict, total_igtf).
    """
    tc: float = flt(doc.conversion_rate) if doc.conversion_rate else 1.0

    base_tax_ves: float = sum(
        flt(tax.base_tax_amount)
        for tax in doc.get("taxes", [])
        if tax.get("charge_type") == "VAT" and flt(tax.rate) > 0
    )
    exempt_ves: float = flt(doc.get("total_exempt", 0.0)) * tc
    base_net: float = flt(doc.base_net_total)
    total_igtf: float = flt(doc.get("total_igtf", 0.0))

    expected: dict[str, float] = {
        "montoGravadoTotal": base_net - exempt_ves,
        "montoExentoTotal": exempt_ves,
        "subtotal": base_net,
        "totalIVA": base_tax_ves,
        "montoTotalConIVA": base_net + base_tax_ves,
        "totalAPagar": base_net + base_tax_ves + total_igtf,
    }

    return expected, total_igtf


def _build_expected_usd(doc: object) -> dict[str, float]:
    """Construye los valores esperados USD desde la factura."""
    tax_usd: float = sum(
        flt(tax.tax_amount)
        for tax in doc.get("taxes", [])
        if tax.get("charge_type") == "VAT" and flt(tax.rate) > 0
    )
    exempt_usd: float = flt(doc.get("total_exempt", 0.0))
    net_total: float = flt(doc.net_total)

    return {
        "montoGravadoTotal": net_total - exempt_usd,
        "montoExentoTotal": exempt_usd,
        "subtotal": net_total,
        "totalIVA": tax_usd,
        "montoTotalConIVA": net_total + tax_usd,
    }


def _extract_payload_section(payload: dict, section: str) -> dict:
    """Extrae una sección de totales del payload HKA."""
    return (
        payload
        .get("documentoElectronico", {})
        .get("encabezado", {})
        .get(section, {})
    ) or {}


def _validate_payload_vs_invoice(payload: dict, doc: object) -> list[str]:
    """Valida que TODOS los montos del payload coincidan con la factura.

    Compara cada campo monetario del payload contra los valores
    almacenados en la factura para ambas monedas (VES y USD) e IGTF.
    """
    errors: list[str] = []

    # VES
    totales_ves: dict = _extract_payload_section(payload, "totales")
    expected_ves, total_igtf = _build_expected_ves(doc)
    errors.extend(_compare_totales_section(totales_ves, expected_ves, "VES"))

    # USD (solo si existe TotalesOtraMoneda)
    totales_usd: dict = _extract_payload_section(payload, "totalesOtraMoneda")
    if totales_usd:
        expected_usd: dict[str, float] = _build_expected_usd(doc)
        errors.extend(_compare_totales_section(totales_usd, expected_usd, "USD"))

    # IGTF
    if total_igtf > 0:
        payload_igtf: float = flt(totales_ves.get("totalIGTF", 0))
        diff_igtf: float = abs(payload_igtf - total_igtf)
        if diff_igtf > _AMOUNT_TOLERANCE:
            errors.append(
                f"[IGTF] totalIGTF: payload={payload_igtf:.2f}, "
                f"factura={total_igtf:.2f} "
                f"(Δ {diff_igtf:.2f})"
            )

    return errors


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


def _sync_gl_entries_date(
    voucher_no: str,
    new_date: str,
    doctype: str = "Sales Invoice",
    bill_no: str = "",
    bill_control: str = "",
) -> None:
    """
    Sincroniza las fechas de los asientos contables (GL Entries),
    cronograma de pagos (Payment Schedule) e historial de pagos
    (Payment Ledger Entry) con la fecha de certificación HKA.

    Adicionalmente, si HKA retorna bill_no y/o bill_control, los propaga
    a los GL Entries del comprobante para que aparezcan en el Libro Mayor.

    Soporta tanto Sales Invoice como VE Sales Credit Note.
    """
    try:
        frappe.db.sql("""
            UPDATE `tabGL Entry`
            SET posting_date = %s
            WHERE voucher_type = %s
              AND voucher_no   = %s
        """, (new_date, doctype, voucher_no))

        # Propagar número de factura y control al GL Entry una vez que
        # HKA los confirma. Solo actualiza los campos que vienen con datos.
        if bill_no or bill_control:
            gl_set_fields: list[str] = []
            gl_params: list = []

            if bill_no:
                gl_set_fields.append("bill_no = %s")
                gl_params.append(bill_no)
            if bill_control:
                gl_set_fields.append("bill_control = %s")
                gl_params.append(bill_control)

            gl_params.extend([doctype, voucher_no])

            frappe.db.sql(
                f"""
                UPDATE `tabGL Entry`
                SET {', '.join(gl_set_fields)}
                WHERE voucher_type = %s
                  AND voucher_no   = %s
                  AND is_cancelled = 0
                """,
                gl_params,
            )
            frappe.logger("l10n_ve").info(
                f"GL Entry [{voucher_no}]: bill_no='{bill_no}', "
                f"bill_control='{bill_control}' sincronizados desde HKA."
            )

        # Refrescar la descripción venezolana del Mayor ahora que el número
        # fiscal ya está confirmado por HKA (idempotente; no rompe si falla).
        from l10n_ve.overrides.gl_remarks import refresh_gl_remarks

        refresh_gl_remarks(doctype, voucher_no)

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
        _sync_gl_entries_date(
            doc.name,
            fecha_hka,
            doc.doctype,
            bill_no=frappe.db.get_value(doc.doctype, doc.name, "bill_no") or "",
            bill_control=control or "",
        )

        frappe.db.set_value(
            doc.doctype, doc.name, "remarks",
            json.dumps(response, indent=2, ensure_ascii=False),
            update_modified=True
        )

        # Verificación post-guardado: asegurar que bill_no y bill_control
        # quedaron persistidos. Previene el bug donde remarks se guarda
        # pero los campos fiscales quedan vacíos.
        saved_fields: dict = frappe.db.get_value(
            doc.doctype, doc.name,
            ["bill_no", "bill_control"],
            as_dict=True,
        ) or {}
        post_fixes: dict = {}
        if not saved_fields.get("bill_no") and numero_documento:
            post_fixes["bill_no"] = numero_documento
        if not saved_fields.get("bill_control") and control:
            post_fixes["bill_control"] = control
        if post_fixes:
            frappe.db.set_value(
                doc.doctype, doc.name, post_fixes,
                update_modified=True,
            )
            frappe.logger("l10n_ve").warning(
                f"{doc.doctype} {doc.name}: Corrección post-guardado "
                f"de campos fiscales: {post_fixes}"
            )

        _set_hka_status(
            doc.doctype, doc.name, "Emitida",
            serie=getattr(series_doc, "serie", "") or "",
        )
        _log_request("Emision", doc.name, payload, response, "Success", doctype=doc.doctype)

        # Trigger retention reminder once invoice has been successfully emitted by HKA
        try:
            from l10n_ve.tasks import trigger_retention_reminder_on_invoice_emission
            trigger_retention_reminder_on_invoice_emission(doc)
        except Exception as e:
            frappe.logger("l10n_ve").error(
                f"Error al intentar enviar aviso de retención inmediato tras emisión HKA para {doc.name}: {str(e)}"
            )

        return True

    # Respuesta nula (timeout, error de red, etc.): response.get() fallaría con AttributeError
    if not response:
        _set_hka_status(doc.doctype, doc.name, "Error")
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

    all_text: str = " ".join(str(v) for v in validaciones).lower() + " " + mensaje.lower()
    is_range_exhausted: bool = any(kw in all_text for kw in _RANGE_EXHAUSTED_KEYWORDS)

    _set_hka_status(doc.doctype, doc.name, "Error")
    _log_request("Emision", doc.name, payload, response, "Error",
                 notes="\n".join(notes_parts), doctype=doc.doctype)

    if is_range_exhausted:
        raise HKARangeExhausted(
            f"Serie agotada: HKA no tiene rango de numeración disponible "
            f"(detectado en factura {invoice_name})."
        )

    return False


# --- Mutex de envío a HKA -------------------------------------------------------
# La exclusión mutua entre el cron y el botón manual salía del lock de fila
# (SELECT ... FOR UPDATE de rerate_to_emission_rate), que quedaba tomado durante TODO
# el viaje de red a HKA. Eso bloqueaba a cualquiera que tocara esa factura —o la serie,
# por el correlativo de _ensure_bill_no— y a los ~50 s le devolvía "servidor demasiado
# ocupado" (lock wait timeout 1205). Se separan las dos responsabilidades: la exclusión
# mutua pasa a este mutex en Redis (no bloquea a nadie) y los locks de fila se sueltan
# con un commit ANTES del I/O.
#
# El mutex es MÁS estricto que el lock de fila anterior: el segundo actor NO espera y
# reintenta, se salta el documento. Es lo correcto acá porque _ensure_bill_no NO es
# idempotente (consume un correlativo fiscal nuevo en cada intento), así que reintentar
# en paralelo arriesga doble emisión en HKA.
_HKA_SEND_LOCK_TTL: int = 300  # s. El envío real dura segundos; esto es solo un techo
                               # para que un worker muerto no deje el documento trabado.


def _acquire_hka_send_lock(doctype: str, doc_name: str) -> bool:
    """Toma el mutex de envío del documento. True si lo obtuvo.

    Fail-open: si Redis no responde se procede igual (el mutex nunca debe impedir
    una emisión; el peor caso es volver al comportamiento previo).
    """
    try:
        cache = frappe.cache()
        return bool(
            cache.set(
                cache.make_key(f"hka_send:{doctype}:{doc_name}"),
                "1",
                nx=True,
                ex=_HKA_SEND_LOCK_TTL,
            )
        )
    except Exception:
        return True


def _release_hka_send_lock(doctype: str, doc_name: str) -> None:
    """Libera el mutex de envío. Fail-open."""
    try:
        frappe.cache().delete_value(f"hka_send:{doctype}:{doc_name}")
    except Exception:
        pass


@frappe.whitelist()
def process_invoice(
    doc_name: str,
    doctype: str = "Sales Invoice",
    raise_on_error: bool = False,
    force: bool = False,
) -> bool:
    """
    Envía una factura, nota de crédito o nota de débito a TFHKA de forma síncrona.
    Soporta: Sales Invoice, VE Sales Credit Note, VE Sales Debit Note.
    Retorna True si el envío fue exitoso, False en caso de error.

    Si raise_on_error=True (invocación desde botón), lanza excepción
    cuando los montos no cuadran. Si False (cron), solo registra log.
    """
    if doctype not in SUPPORTED_DOCTYPES:
        frappe.throw(
            f"DocType '{doctype}' no es compatible con la facturación digital.",
            title="DocType No Soportado"
        )

    raise_on_error = cint(raise_on_error)
    force = cint(force)
    is_nc: bool = doctype == "VE Sales Credit Note"
    is_nd: bool = doctype == "VE Sales Debit Note"
    skip_si_validations: bool = is_nc or is_nd

    # Exclusión mutua cron vs botón manual (ver _acquire_hka_send_lock). Si otro actor
    # ya está enviando este documento se omite: reintentarlo en paralelo consumiría otro
    # correlativo fiscal y podría emitirlo dos veces en HKA.
    if not _acquire_hka_send_lock(doctype, doc_name):
        _hka_log(
            f"Envío omitido: {doctype} {doc_name} ya está siendo enviado por otro proceso.",
            "Warning",
        )
        return False

    try:
        doc = frappe.get_doc(doctype, doc_name)

        # Tasa del documento. Corre ANTES de calcular tasa_fecha para que el
        # lookup inverso, la coherencia y el payload salgan con la tasa
        # correcta. En modo force se respeta la tasa que porta el documento.
        # - Sales Invoice: se retasa en caliente a la tasa BCV de la fecha de
        #   emisión (Ley IVA Art. 25 / Providencia SNAT/2011/0071, jurídicos).
        # - NC/ND: no se retasan. La NC hereda la tasa de la factura afectada
        #   (24-jul-2026) para no introducir diferencial contra su CxC, y el
        #   guard solo verifica que siga siendo esa. La ND la trae por defecto
        #   pero es editable.
        if not force:
            if skip_si_validations:
                validate_note_rate(doc)
            else:
                rerate_to_emission_rate(doc)

        # Calcular la fecha real de la tasa BCV ANTES de actualizar posting_date.
        # En modo forzado, usar la fecha exacta del posting_date para que
        # el texto del PDF refleje la fecha real de la tasa del documento.
        if force:
            tasa_fecha: str = str(getdate(doc.posting_date))
        else:
            tasa_fecha: str = _compute_tasa_fecha(doc)

        # Verificar que la tasa del documento coincida con la BCV registrada
        # para la fecha que se va a imprimir (fail-closed).
        # - Natural: tasa_fecha = 1° del mes → detecta tasa desalineada.
        # - Jurídico: tasa_fecha se resolvió DESDE la tasa (lookup inverso),
        #   así que el flujo sano pasa trivialmente; si no hubo fila
        #   coincidente cayó al posting_date y esto bloquea la emisión de
        #   una tasa que no existe en Currency Exchange.
        # Aplica también a NC/ND: su par tasa/fecha debe existir en Currency
        # Exchange igual que el de la factura. Como la nota hereda la tasa de
        # la factura afectada, el lookup inverso resuelve la fecha de ESA
        # tasa, que es la que se imprime en el documento fiscal.
        if not force:
            _validate_tasa_coherencia(doc, tasa_fecha)

        fecha_hka: str = today()
        _update_fiscal_dates(doc, fecha_hka)

        branch = doc.get("branch") or ""
        series_doc, branch_code = get_active_billing_series(
            company=doc.company, branch=branch
        )

        _ensure_bill_no(doc, series_doc)

        payload, builder = _build_invoice_payload(doc, series_doc, branch_code, tasa_fecha)

        # --- VALIDACIÓN PRE-ENVÍO: integridad factura + payload vs factura ---
        all_errors: list[str] = []
        all_errors.extend(_validate_invoice_integrity(doc))
        all_errors.extend(_validate_payload_vs_invoice(payload, doc))

        if all_errors:
            msg: str = (
                f"Validación fiscal fallida para {doctype} {doc_name}:\n"
                + "\n".join(f"  • {e}" for e in all_errors)
            )
            frappe.logger("l10n_ve").error(msg)
            _set_hka_status(doctype, doc_name, "Error")
            _log_request(
                "Validación Pre-Envío HKA", doc_name, payload,
                {"error": True, "message": msg}, "Error",
                notes=msg, doctype=doctype,
            )
            frappe.db.commit()
            if raise_on_error:
                frappe.throw(
                    msg, exc=HKAAmountMismatchError,
                    title="Discrepancia de Montos Fiscales",
                )
            return False

        # Para NC y ND no se valida la zona (no tienen suscripción asociada)
        if not skip_si_validations:
            if not builder.zona:
                notes = (
                    f"No se pudo resolver: Zona (territory del cliente). "
                    f"Cliente: {doc.customer_name}, Suscripción: {doc.get('subscription') or '-'}"
                )
                _set_hka_status(doc.doctype, doc.name, "Error")
                _log_request("Emision", doc.name, payload,
                             {"error": True, "message": notes}, "Error", notes=notes)
                frappe.db.commit()
                return False

        client = TFHKAClient()

        # commit-antes-del-IO: soltar los locks de fila ANTES del viaje de red a HKA.
        # Hasta acá la transacción retiene el lock de la FACTURA (SELECT ... FOR UPDATE
        # de rerate_to_emission_rate) y el de la SERIE (correlativo de _ensure_bill_no).
        # Mantenerlos durante la llamada a HKA (timeouts de 15-60 s) bloquea a todo el
        # que toque esa factura o esa serie, que recibe "servidor demasiado ocupado"
        # (lock wait timeout 1205) — visto en producción el 2026-07-29 con un envío que
        # tardó 51 s. La exclusión mutua la sostiene ahora el mutex de Redis, no el lock
        # de fila. La durabilidad ante un fallo no cambia: los caminos de error de abajo
        # ya commitean igual. En tests no se commitea (rompería el rollback del caso).
        if not frappe.flags.in_test:
            frappe.db.commit()

        response = client.emitir_documento(payload)
        return _handle_hka_response(
            doc, doc_name, payload, response, series_doc
        )

    except (frappe.ValidationError, HKAAmountMismatchError):
        raise
    except HKARangeExhausted:
        # Persistir el hka_status=Error y el log escritos en
        # _handle_hka_response: sin este commit, el rollback del throw en el
        # request (camino manual raise_on_error) los borraría.
        frappe.db.commit()
        raise

    except Exception as e:
        tb: str = frappe.get_traceback(with_context=True) or str(e)
        frappe.logger("l10n_ve").error(f"Error procesando {doctype} {doc_name}: {tb}")
        try:
            # No pisar una emisión ya confirmada: si el doc ya tiene
            # bill_control, HKA lo emitió y este fallo fue post-emisión
            # (p. ej. deadlock en _sync_gl_entries_date o _log_request).
            if not frappe.db.get_value(doctype, doc_name, "bill_control"):
                _set_hka_status(doctype, doc_name, "Error")
        except Exception:
            # No enmascarar el error original si el doc no existe o la
            # escritura falla; el log de abajo es el registro primario.
            pass
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

    finally:
        # Se libera SIEMPRE (éxito, error o excepción propagada). Si el proceso muere
        # antes de llegar acá, el TTL del mutex lo destraba solo.
        _release_hka_send_lock(doctype, doc_name)


def _log_request(
    endpoint: str,
    invoice_name: str,
    payload: dict,
    response: dict,
    status: str,
    notes: str = "",
    doctype: str = "Sales Invoice",
) -> None:
    """Registra el log de la solicitud.

    Para errores, aplica deduplicación: si ya existe un log de error
    reciente (últimas 24h) para la misma factura, no crea duplicado.
    """
    if status == "Error" and invoice_name:
        already_exists: bool = frappe.db.exists(
            "VE Digital Invoice Log",
            {
                "sales_invoice": invoice_name,
                "status": "Error",
                "creation": [">=", frappe.utils.add_days(
                    frappe.utils.nowdate(), -1
                )],
            },
        )
        if already_exists:
            return

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



def _approve_before_manual_send(invoice_name: str, force: bool = False) -> None:
    """Aprueba la factura si esta en borrador, antes del envio manual a HKA.

    El boton es una de las DOS unicas vias de envio (la otra es el cron), y ambas
    esperan la factura ya aprobada. Como la aprobacion manual desde el formulario esta
    bloqueada para sucursales con serie digital activa, sin este paso una factura fiscal
    en borrador que nadie cobre quedaria sin forma de emitirse.

    Juridico: se retasa a la tasa del dia y se aprueba (Ley IVA Art. 25).
    Natural:  se aprueba tal cual, conserva la tasa congelada del 1 del mes.

    En modo forzado no se retasa: `force` existe para reenviar respetando la tasa que
    porta el documento.
    """
    doc = frappe.get_doc("Sales Invoice", invoice_name)
    if cint(doc.docstatus) != 0:
        return

    if force:
        # El hook before_validate retasa en CUALQUIER submit; sin este flag el modo
        # forzado retasaba igual y el boton no servia para lo que existe.
        doc.flags.skip_emission_rerate = True
    else:
        rerate_juridical_before_submit(doc)

    doc.flags.ignore_permissions = True
    doc.save()
    doc.submit()

@frappe.whitelist()
def send_invoice_manually(invoice_name: str, force: bool = False) -> str:
    """Método invocado mediante botón JS para reenvío manual de Sales Invoice."""
    force = cint(force)

    if force and frappe.session.user != "Administrator":
        frappe.throw(
            "Solo el Administrador puede forzar el envío a HKA.",
            title="Permiso Denegado",
        )

    frappe.has_permission("Sales Invoice", "submit", doc=invoice_name, throw=True)
    _approve_before_manual_send(invoice_name, force=force)

    success = process_invoice(
        invoice_name, doctype="Sales Invoice", raise_on_error=True, force=force
    )
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
    rerate_aviso: str = ""

    # La emision retasa al juridico a la tasa BCV del dia ANTES de calcular la fecha
    # (process_invoice -> rerate_to_emission_rate). La previa debe mostrar ESA tasa:
    # leer la almacenada dejaba en pantalla la tasa vieja —la que quedo al aplicar el
    # pago— y el usuario veia una fecha que nunca se iba a emitir.
    # Se reusa la decision real (mismo gate y mismos bloqueos). Ambas funciones son de
    # solo lectura, asi que la previa sigue sin tocar la base de datos.
    if is_juridical_customer(doc.customer):
        if cint(doc.docstatus) == 0:
            # BORRADOR: al aprobar corre el retasado pre-submit, que no tiene bloqueos
            # --no hay mayor que reparar--. Se consulta la misma decision, en su version
            # de solo lectura, para que la previa no pueda divergir del retasado real.
            target_rate = target_rate_before_submit(doc)
            if target_rate is not None:
                tc = flt(target_rate)
                rerate_aviso = (
                    f"Al aprobarla se retasara a la tasa de hoy "
                    f"({tc:.4f} Bs por 1 {doc.currency}); los montos en Bs se recalculan."
                )
        else:
            target_rate = _get_target_rate(doc)
            if target_rate is not None:
                motivo = _blocking_condition(doc)
                if motivo:
                    rerate_aviso = (
                        f"No se retasara a la tasa de hoy porque la factura {motivo}. "
                        f"Se emitira con la tasa que porta el documento."
                    )
                else:
                    tc = flt(target_rate)

        # Fecha real de la tasa que se va a emitir (misma regla que _compute_tasa_fecha).
        fecha_bcv = getdate(resolve_exchange_rate_date(tc, doc.currency) or doc.posting_date)
    else:
        fecha_bcv = getdate(doc.posting_date).replace(day=1)

    zona: str = customer.territory or resolve_zone_from_address(
        doc.customer, doc.get("customer_address")
    ) or ""
    nodo: str = ""

    months = ["", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO",
              "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
    posting_date = getdate(doc.posting_date)
    notes: str = " ".join(str(doc.get("notes") or "").replace('"', "").split())

    # Espeja el payload real (dict_pdf en payload_builder):
    period_default: str = f"{months[posting_date.month]} {posting_date.year}"
    note: str = notes or period_default

    from calendar import monthrange
    last_day = monthrange(posting_date.year, posting_date.month)[1]
    start_date_str = posting_date.replace(day=1).strftime("%d/%m/%Y")
    end_date_str = posting_date.replace(day=last_day).strftime("%d/%m/%Y")
    period: str = f"Desde {start_date_str} hasta {end_date_str}"

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
        "periodo": period,
        "nota": note,
        "tasa_bcv": "{:.4f}".format(tc),
        "tasa_fecha": fecha_bcv.strftime("%d/%m/%Y"),
        "rerate_aviso": rerate_aviso,
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


def send_pending_documents_to_hka() -> None:
    """Cron unificado: envía facturas de venta + retenciones IVA + retenciones ISLR.

    Paso 1: Facturas de venta pendientes (lógica existente).
    Paso 2: Comprobantes de retención IVA pendientes.
    Paso 3: Comprobantes de retención ISLR pendientes.

    Respeta el flag 'enabled', 'enable_auto_send' y 'cutoff_date' de TFHKA Settings.
    """
    tfhka_settings: dict | None = _get_tfhka_settings()
    if not tfhka_settings:
        return

    if not tfhka_settings.get("enable_auto_send"):
        return

    # Paso 1: Facturas de venta
    _send_pending_invoices(tfhka_settings)

    # Paso 2: Retenciones de IVA
    from l10n_ve.digital_invoice.retention_integration import send_pending_retention_vouchers
    send_pending_retention_vouchers(tfhka_settings)

    # Paso 3: Retenciones de ISLR
    from l10n_ve.digital_invoice.islr_withholding_integration import send_pending_islr_vouchers
    send_pending_islr_vouchers(tfhka_settings)


# Alias de compatibilidad para evitar romper referencias externas
send_pending_invoices_to_hka = send_pending_documents_to_hka


def _send_pending_invoices(tfhka_settings: dict) -> None:
    """Envía facturas de venta pagadas pendientes a HKA.

    Recorre cada serie de facturación digital activa y procesa por sucursal.

    Comportamiento según modo de operación:
      - Internal:    STOP on error (proteger correlativo local de saltos).
      - Third Party: CONTINUE on error (HKA controla la numeración).
    """
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
        branches: list[str] = series["branches"]
        if not branches:
            continue

        pending: list[str] = _get_pending_hka_invoices(
            branches=branches,
            cutoff_date=cutoff_date,
        )
        pending = _drop_invoices_with_stale_rate(pending)
        if not pending:
            continue

        _hka_log(
            f"Serie {series['name']} ({series['operation_mode']}): "
            f"{len(pending)} facturas pendientes en {len(branches)} sucursal(es).",
            "Success",
        )

        s, e, ok_list, err_list = _process_series_invoices(series, pending)
        total_success += s
        total_errors += e
        success_invoices.extend(ok_list)
        error_invoices.extend(err_list)

    _log_batch_summary(total_success, total_errors, success_invoices, error_invoices)
    _repair_partial_hka_invoices()


def _process_series_invoices(
    series: dict,
    pending: list[str],
) -> tuple[int, int, list[str], list[str]]:
    """Procesa las facturas pendientes de una serie específica.

    Retorna (exitosas, errores, lista_exitosas, lista_errores).

    Circuit breaker: si HKA responde "sin rango de numeración",
    detiene toda la serie inmediatamente.
    """
    stop_on_error: bool = series["operation_mode"] == "Internal"
    series_name: str = series["name"]

    success_count: int = 0
    error_count: int = 0
    success_invoices: list[str] = []
    error_invoices: list[str] = []

    for invoice_name in pending:
        try:
            result: bool = process_invoice(invoice_name)

            if result:
                success_count += 1
                success_invoices.append(invoice_name)
                frappe.db.commit()
            else:
                error_count += 1
                error_invoices.append(invoice_name)
                frappe.db.commit()
                if stop_on_error:
                    _hka_log(
                        f"STOP en serie {series_name} (Internal): "
                        f"factura {invoice_name} falló.",
                        "Error",
                    )
                    break

        except HKARangeExhausted as e:
            error_count += 1
            error_invoices.append(invoice_name)
            frappe.db.commit()
            _hka_log(
                f"CIRCUIT BREAKER - Serie {series_name} detenida: {str(e)} "
                f"({len(pending)} facturas pendientes sin procesar).",
                "Error",
            )
            break

        except Exception as e:
            error_count += 1
            error_invoices.append(invoice_name)
            frappe.db.rollback()
            _log_request(
                "HKA Cron",
                invoice_name,
                {},
                {"error": True, "message": str(e)},
                "Error",
                notes=f"Error enviando {invoice_name}: {str(e)}",
            )
            if stop_on_error:
                _hka_log(
                    f"STOP en serie {series_name} (Internal): "
                    f"excepción en {invoice_name}.",
                    "Error",
                )
                break

        time.sleep(_TFHKA_DELAY_BETWEEN_CALLS)

    return success_count, error_count, success_invoices, error_invoices


def _log_batch_summary(
    total_success: int,
    total_errors: int,
    success_invoices: list[str],
    error_invoices: list[str],
) -> None:
    """Registra el resumen final del lote de envío a HKA."""
    if not total_success and not total_errors:
        return

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
            # El doc quedó con datos fiscales completos → HKA sí lo emitió
            updates["hka_status"] = "Emitida"
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


def _drop_invoices_with_stale_rate(pending: list[str]) -> list[str]:
    """Saca de la tanda las facturas cuya tasa no corresponde a su fecha de emision.

    Una factura mal emitida NO se deshace: hay que anularla con nota de credito y
    reemitirla ante el SENIAT. Por eso el chequeo es fail-closed --si la tasa no cuadra
    con la posting_date, no sale-- y vive antes del envio, no despues.

    Se excluyen de la tanda en vez de fallarlas dentro del bucle a proposito: en las
    series `Internal` el `stop_on_error` frena la serie completa, y una sola factura con
    la tasa desincronizada dejaria sin certificar a todas las demas.

    El motivo se registra en VE Digital Invoice Log, no solo en el log del cron, para que
    salga en el reporte "Estado de Facturas VE HKA": la factura aparece como Error con la
    explicacion en la columna Detalles, en vez de quedar en Pendiente sin decir por que.

    Se registra UNA vez por factura: el cron corre cada 5 minutos y volveria a anotarla
    en cada pasada.
    """
    from l10n_ve.digital_invoice.emission_rerate import stale_rate_reason

    sanas: list[str] = []
    for invoice_name in pending:
        doc = frappe.get_doc("Sales Invoice", invoice_name)
        motivo: str | None = stale_rate_reason(doc)
        if not motivo:
            sanas.append(invoice_name)
            continue

        ya_anotada: bool = bool(frappe.db.exists("VE Digital Invoice Log", {
            "sales_invoice": invoice_name,
            "document_type": "Sales Invoice",
            "status": "Error",
            "notes": ("like", "%no corresponde a su fecha de emisi%"),
        }))
        if not ya_anotada:
            _log_request(
                "HKA Cron",
                invoice_name,
                {},
                {"error": True, "message": motivo},
                "Error",
                notes=motivo,
            )
            frappe.db.commit()

    return sanas


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


@frappe.whitelist()
def bulk_download_pdf(from_date: str, to_date: str, customer: str = None) -> dict:
	"""
	Genera y descarga el ZIP de forma síncrona para compatibilidad y entornos
	sin workers/WebSockets activos.
	"""
	import zipfile
	import io
	import base64
	from l10n_ve.digital_invoice.tfhka_client import get_fiscal_invoice_pdf
	from frappe.utils.file_manager import save_file

	filters = {
		"docstatus": 1,
		"posting_date": ["between", [from_date, to_date]],
	}
	if customer:
		filters["customer"] = customer

	invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks", "bill_no"])

	valid_invoices = []
	for inv in invoices:
		if inv.remarks and '"numeroDocumento"' in inv.remarks:
			valid_invoices.append(inv)

	if not valid_invoices:
		frappe.throw(frappe._("No se encontraron facturas aprobadas por HKA en el rango seleccionado."))

	# Límite de seguridad síncrona para prevenir timeouts del servidor
	MAX_LIMIT = 50
	if len(valid_invoices) > MAX_LIMIT:
		frappe.throw(
			frappe._(
				"El rango seleccionado contiene {0} facturas certificadas por HKA. "
				"Por seguridad y para evitar bloqueos con el servidor de HKA, "
				"el límite máximo para la descarga masiva es de {1} facturas. "
				"Por favor, seleccione un rango de fechas más corto o filtre por un cliente."
			).format(len(valid_invoices), MAX_LIMIT)
		)

	MAX_SIZE_BYTES = int(4.5 * 1024 * 1024)  # 4.5 MB
	files = []
	errors = []
	downloaded_count = 0

	zip_buffer = io.BytesIO()
	zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
	current_zip_count = 0
	part_number = 1

	for idx, inv in enumerate(valid_invoices):
		try:
			res = get_fiscal_invoice_pdf(inv.name, "Sales Invoice")
			pdf_base64 = res.get("base64")

			# Determinar el tamaño aproximado de los datos del PDF
			if not pdf_base64 and (inv.remarks and "Simulado" in inv.remarks):
				pdf_len = 500000
			elif pdf_base64:
				pdf_len = (len(pdf_base64) * 3) // 4
			else:
				pdf_len = 0

			# Si al sumarlo al ZIP supera los 4.5 MB
			if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
				# Cerrar y guardar el ZIP actual
				zip_file.close()
				zip_buffer.seek(0)
				cust_suffix = f"_{customer}" if customer else ""
				file_name = f"Facturas_HKA_{from_date}_a_{to_date}{cust_suffix}_Parte{part_number}.zip"
				file_doc = save_file(
					fname=file_name,
					content=zip_buffer.getvalue(),
					dt=None,
					dn=None,
					is_private=1
				)
				files.append(file_doc.file_url)

				# Inicializar nuevo ZIP
				zip_buffer = io.BytesIO()
				zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
				current_zip_count = 0
				part_number += 1

			# MOCK: Si es una factura simulada para testing
			if not pdf_base64 and (inv.remarks and "Simulado" in inv.remarks):
				import os
				pdf_data = b"%PDF-1.4\n" + os.urandom(500000) + b"\n%%EOF"
				doc_no = inv.bill_no or "999999"
				filename = f"Factura_{inv.name}_{doc_no}_MOCK.pdf"
				zip_file.writestr(filename, pdf_data)
				downloaded_count += 1
				current_zip_count += 1
				continue

			if pdf_base64:
				pdf_data = base64.b64decode(pdf_base64)
				doc_no = res.get("numero_documento") or inv.bill_no or inv.name
				filename = f"Factura_{inv.name}_{doc_no}.pdf"
				zip_file.writestr(filename, pdf_data)
				downloaded_count += 1
				current_zip_count += 1
			else:
				err_msg = res.get("error") if res else "Error desconocido al descargar PDF."
				errors.append(f"{inv.name}: {err_msg}")
		except Exception as e:
			errors.append(f"{inv.name}: {str(e)}")
			frappe.logger("l10n_ve").error(
				f"Error en descarga masiva de PDF para {inv.name}: {frappe.get_traceback()}"
			)

	# Guardar el último ZIP
	if current_zip_count > 0:
		zip_file.close()
		zip_buffer.seek(0)
		cust_suffix = f"_{customer}" if customer else ""
		part_suffix = f"_Parte{part_number}" if part_number > 1 else ""
		file_name = f"Facturas_HKA_{from_date}_a_{to_date}{cust_suffix}{part_suffix}.zip"
		file_doc = save_file(
			fname=file_name,
			content=zip_buffer.getvalue(),
			dt=None,
			dn=None,
			is_private=1
		)
		files.append(file_doc.file_url)
	else:
		zip_file.close()

	if downloaded_count == 0:
		frappe.throw(
			frappe._("No se pudo descargar ningún PDF de HKA. Errores: {0}").format(", ".join(errors[:3]))
		)

	return {
		"files": files,
		"count": downloaded_count,
		"total_attempted": len(valid_invoices),
		"errors": errors
	}


@frappe.whitelist()
def enqueue_bulk_download_pdf(from_date: str, to_date: str, customer: str = None) -> dict:
	"""
	Encola el trabajo en segundo plano para la descarga masiva de PDFs.
	Retorna de inmediato al cliente.
	"""
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(frappe._("No tiene permiso para leer Facturas de Venta."), frappe.PermissionError)

	filters = {
		"docstatus": 1,
		"posting_date": ["between", [from_date, to_date]],
	}
	if customer:
		filters["customer"] = customer

	# Obtener facturas en el rango para validación rápida
	invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks"])
	valid_count = sum(1 for inv in invoices if inv.remarks and '"numeroDocumento"' in inv.remarks)

	if valid_count == 0:
		frappe.throw(frappe._("No se encontraron facturas aprobadas por HKA en el rango seleccionado."))

	# Guardar estado inicial en la caché
	cache_key = f"bulk_download_status_{frappe.session.user}"
	frappe.cache().set_value(cache_key, {"status": "running"})

	# Encolar el proceso
	frappe.enqueue(
		"l10n_ve.digital_invoice.tfhka_integration.bulk_download_pdf_job",
		queue="default",
		timeout=600,
		from_date=from_date,
		to_date=to_date,
		customer=customer,
		request_user=frappe.session.user
	)

	return {
		"status": "enqueued",
		"message": frappe._("El proceso se ha iniciado en segundo plano. Te notificaremos cuando esté listo.")
	}


@frappe.whitelist()
def get_bulk_download_status() -> dict:
	cache_key = f"bulk_download_status_{frappe.session.user}"
	return frappe.cache().get_value(cache_key) or {"status": "none"}


@frappe.whitelist()
def clear_bulk_download_status() -> None:
	cache_key = f"bulk_download_status_{frappe.session.user}"
	frappe.cache().delete_value(cache_key)


def bulk_download_pdf_job(from_date: str, to_date: str, customer: str = None, request_user: str = None) -> None:
	"""
	Trabajo en segundo plano para generar el ZIP de facturas.
	"""
	if request_user:
		frappe.set_user(request_user)

	import zipfile
	import io
	import base64
	from l10n_ve.digital_invoice.tfhka_client import get_fiscal_invoice_pdf
	from frappe.utils.file_manager import save_file

	filters = {
		"docstatus": 1,
		"posting_date": ["between", [from_date, to_date]],
	}
	if customer:
		filters["customer"] = customer

	invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks", "bill_no"])

	valid_invoices = []
	for inv in invoices:
		if inv.remarks and '"numeroDocumento"' in inv.remarks:
			valid_invoices.append(inv)

	if not valid_invoices:
		return

	MAX_SIZE_BYTES = int(4.5 * 1024 * 1024)  # 4.5 MB
	files = []
	errors = []
	downloaded_count = 0

	zip_buffer = io.BytesIO()
	zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
	current_zip_count = 0
	part_number = 1

	for idx, inv in enumerate(valid_invoices):
		try:
			res = get_fiscal_invoice_pdf(inv.name, "Sales Invoice")
			pdf_base64 = res.get("base64")

			# Determinar el tamaño aproximado de los datos del PDF antes de meterlo
			if not pdf_base64 and (inv.remarks and "Simulado" in inv.remarks):
				pdf_len = 500000
			elif pdf_base64:
				pdf_len = (len(pdf_base64) * 3) // 4
			else:
				pdf_len = 0

			# Si al sumarlo al ZIP supera los 4.5 MB
			if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
				# Cerrar y guardar el ZIP actual
				zip_file.close()
				zip_buffer.seek(0)
				cust_suffix = f"_{customer}" if customer else ""
				file_name = f"Facturas_HKA_{from_date}_a_{to_date}{cust_suffix}_Parte{part_number}.zip"
				file_doc = save_file(
					fname=file_name,
					content=zip_buffer.getvalue(),
					dt=None,
					dn=None,
					is_private=1
				)
				files.append(file_doc.file_url)

				# Inicializar nuevo ZIP
				zip_buffer = io.BytesIO()
				zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
				current_zip_count = 0
				part_number += 1

			# MOCK: Si es una factura simulada para testing
			if not pdf_base64 and (inv.remarks and "Simulado" in inv.remarks):
				import os
				pdf_data = b"%PDF-1.4\n" + os.urandom(500000) + b"\n%%EOF"
				doc_no = inv.bill_no or "999999"
				filename = f"Factura_{inv.name}_{doc_no}_MOCK.pdf"
				zip_file.writestr(filename, pdf_data)
				downloaded_count += 1
				current_zip_count += 1
				continue

			if pdf_base64:
				pdf_data = base64.b64decode(pdf_base64)
				doc_no = res.get("numero_documento") or inv.bill_no or inv.name
				filename = f"Factura_{inv.name}_{doc_no}.pdf"
				zip_file.writestr(filename, pdf_data)
				downloaded_count += 1
				current_zip_count += 1
			else:
				err_msg = res.get("error") if res else "Error desconocido al descargar PDF."
				errors.append(f"{inv.name}: {err_msg}")
		except Exception as e:
			errors.append(f"{inv.name}: {str(e)}")
			frappe.logger("l10n_ve").error(
				f"Error en descarga masiva de PDF para {inv.name}: {frappe.get_traceback()}"
			)

	# Guardar el último ZIP
	if current_zip_count > 0:
		zip_file.close()
		zip_buffer.seek(0)
		cust_suffix = f"_{customer}" if customer else ""
		part_suffix = f"_Parte{part_number}" if part_number > 1 else ""
		file_name = f"Facturas_HKA_{from_date}_a_{to_date}{cust_suffix}{part_suffix}.zip"
		file_doc = save_file(
			fname=file_name,
			content=zip_buffer.getvalue(),
			dt=None,
			dn=None,
			is_private=1
		)
		files.append(file_doc.file_url)
	else:
		zip_file.close()

	# Guardar estado final en la caché
	cache_key = f"bulk_download_status_{request_user}"
	frappe.cache().set_value(cache_key, {
		"status": "completed",
		"files": files,
		"count": downloaded_count,
		"total_attempted": len(valid_invoices),
		"errors": errors
	})

	# Crear una notificación del sistema (Notification Log) en la campana
	if files:
		try:
			from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
			part_txt = f" en {len(files)} partes" if len(files) > 1 else ""
			msg = f"Tu descarga masiva de facturas HKA está lista ({downloaded_count} facturas{part_txt})."
			
			links_html = []
			for idx, url in enumerate(files, 1):
				links_html.append(f"<a href='{url}' target='_blank'>Descargar Parte {idx}</a>")
			links_str = " | ".join(links_html)

			enqueue_create_notification(
				users=[request_user],
				doc={
					"subject": msg,
					"email_content": f"Los archivos ZIP están listos para descargar:<br>{links_str}",
					"type": "Alert",
					"document_type": "Sales Invoice"
				}
			)
		except Exception as e:
			frappe.logger("l10n_ve").error(f"Error al crear log de notificación: {str(e)}")


@frappe.whitelist()
def download_zip_file(file_url: str):
	"""
	Permite a los usuarios descargar los archivos ZIP generados por la descarga masiva
	evitando problemas de permisos del DocType File y forzando la descarga nativa.
	"""
	if not file_url or not ("Facturas_HKA_" in file_url and file_url.endswith(".zip")):
		raise frappe.PermissionError("Archivo no válido.")

	file_name = file_url.split("/")[-1]
	file_doc = frappe.get_value("File", {"file_url": file_url}, "name")
	if not file_doc:
		raise frappe.ValidationError("El archivo no existe.")

	file = frappe.get_doc("File", file_doc)
	
	# BOLA check: check if user owns the file, or is Admin, or has read permission on the attached document
	is_authorized = False
	if frappe.session.user == "Administrator" or file.owner == frappe.session.user:
		is_authorized = True
	elif file.attached_to_doctype and file.attached_to_name:
		if frappe.has_permission(file.attached_to_doctype, "read", doc=file.attached_to_name):
			is_authorized = True
			
	if not is_authorized:
		frappe.throw(frappe._("No tiene permisos para descargar este archivo."), frappe.PermissionError)
	
	frappe.local.response.filename = file.file_name
	frappe.local.response.filecontent = file.get_content()
	frappe.local.response.type = "download"



