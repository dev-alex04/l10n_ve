"""Emisión ante HKA del documento fiscal 04: Orden de Entrega y Guía de Despacho.

Sale de dos doctypes: la nota de entrega (`Delivery Note`) y el traslado de material
(`Stock Entry` de propósito *Material Transfer*). El payload lo arma
`dispatch_note_payload_builder`; acá vive el ciclo de vida:

1. **Al aprobar.** Si el 04 aplica (`dispatch_note_applies`): la nota de entrega se retasa
   con la misma regla que la factura, se validan los datos del traslado --si falta algo se
   corta ahí, no en el cron, porque después de aprobado ya no se puede corregir sin
   cancelar-- y el documento queda `Pendiente`.
2. **El envío.** Paso 4 del cron de HKA (`send_pending_dispatch_notes`) o el botón del
   formulario (`send_dispatch_note_manually`). Mismo mutex y mismo commit-antes-del-IO que
   la factura.
3. **La respuesta.** Número, control, serie y estado se escriben en UN solo UPDATE: la
   conciliación horaria de la factura existe porque esos campos se escribían por separado
   y a veces quedaban vacíos, y acá ese modo de falla no existe.
4. **Deshacerlo.** Un 04 emitido no se cancela en Frappe: se anula ante HKA
   (`void_dispatch_note`) y recién entonces se cancela el documento.

Nada de esto corre si el sitio no lo pidió: el interruptor es
`TFHKA Settings.enable_dispatch_notes`. Apagado, una nota de entrega o un traslado se
aprueban y se cancelan exactamente como antes.
"""

from __future__ import annotations

import datetime
import functools
import json
import time

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from l10n_ve.digital_invoice.dispatch_note_payload_builder import (
    DELIVERY_ORDER,
    DISPATCH_DOCUMENT_TYPE,
    DISPATCH_GUIDE,
    REASONS_NEEDING_DESCRIPTION,
    DeliveryNotePayloadBuilder,
    StockEntryDispatchPayloadBuilder,
    apply_delivery_note_tax_regime,
    delivery_note_tax_problems,
    party_address_text,
    transport_value,
)
from l10n_ve.digital_invoice.tfhka_client import TFHKAClient
from l10n_ve.digital_invoice.tfhka_integration import (
    _RANGE_EXHAUSTED_KEYWORDS,
    HKARangeExhausted,
    _acquire_hka_send_lock,
    _create_log_entry,
    _log_request,
    _release_hka_send_lock,
    _validate_invoice_integrity,
    _validate_payload_vs_invoice,
    company_uses_hk,
    get_active_billing_series,
)
from l10n_ve.utils.utils import get_ve_exchange_rate_for_customer

#: Doctypes que emiten el 04: la lista blanca de los métodos expuestos al formulario.
DISPATCH_DOCTYPES: tuple[str, ...] = ("Delivery Note", "Stock Entry")

_BATCH_SIZE: int = 50
_DELAY_BETWEEN_CALLS: float = 0.5

#: Misma tolerancia que el retasado de la factura (`emission_rerate._RATE_TOLERANCE`).
_RATE_TOLERANCE: float = 0.0001


# ---------------------------------------------------------------------------
# ¿Aplica el 04?
# ---------------------------------------------------------------------------

def dispatch_notes_enabled() -> bool:
    """El sitio emite el 04: facturación digital encendida y el interruptor del 04 también.

    Entre el despliegue del código y el migrate el campo todavía no existe, y
    `get_single_value` LANZA ante un campo desconocido. Como esto corre al aprobar cualquier
    nota de entrega, sin la guarda ninguna se podría aprobar hasta migrar.
    """
    if not frappe.get_meta("TFHKA Settings").has_field("enable_dispatch_notes"):
        return False
    return bool(
        cint(frappe.db.get_single_value("TFHKA Settings", "enabled"))
        and cint(frappe.db.get_single_value("TFHKA Settings", "enable_dispatch_notes"))
    )


def dispatch_note_applies(doc) -> bool:
    """¿Este documento se emite como 04?

    - Nota de entrega: toda, salvo las devoluciones (el 04 no tiene una forma de «devolver»).
    - Traslado de material: solo si pide la guía (`ve_issue_dispatch_note`). Un traslado
      entre almacenes del mismo local no saca mercancía a la calle.
    - Y siempre que el sitio lo tenga encendido y la empresa emita con HKA.
    """
    if doc.doctype == "Delivery Note":
        if cint(doc.get("is_return")):
            return False
    elif doc.doctype == "Stock Entry":
        if doc.get("purpose") != "Material Transfer" or not cint(doc.get("ve_issue_dispatch_note")):
            return False
    else:
        return False

    return dispatch_notes_enabled() and company_uses_hk(doc.company)


def dispatch_note_companies() -> list[str]:
    """Empresas que emiten el 04: las que tienen una serie digital activa, con el sitio encendido.

    Es el criterio de `dispatch_note_applies` (el de `company_uses_hk`) puesto en lista para el
    boot: el formulario muestra el bloque del 04, propone el tipo y ofrece «Enviar a HKA» solo
    en esas empresas. En las demás la nota de entrega es la de siempre.
    """
    if not dispatch_notes_enabled():
        return []
    companies = frappe.get_all("VE Digital Billing Series", filters={"status": "Active"}, pluck="company")
    return sorted({company for company in companies if company})


def validate_dispatch_data(doc) -> list[str]:
    """Lo que el 04 necesita del documento, antes de aprobarlo y antes de enviarlo.

    Devuelve los problemas en lenguaje de usuario; vacía si está completo. No mira montos:
    esos los valida el mismo control que la factura, con el payload armado.
    """
    errors: list[str] = []

    if not doc.get("branch"):
        errors.append("Falta la sucursal: define la serie del documento fiscal.")

    kind: str = doc.get("ve_dispatch_document_kind") or ""
    if kind not in (DELIVERY_ORDER, DISPATCH_GUIDE):
        errors.append(f"Falta el tipo de documento de despacho ({DELIVERY_ORDER} o {DISPATCH_GUIDE}).")

    reason: str = doc.get("ve_transfer_reason") or ""
    if kind == DISPATCH_GUIDE and not reason:
        errors.append("Falta el motivo del traslado: es obligatorio en la Guía de Despacho.")
    if reason in REASONS_NEEDING_DESCRIPTION and not (doc.get("ve_transfer_description") or "").strip():
        errors.append(f"El motivo «{reason}» exige describir el servicio o la causa.")

    driver: str = transport_value(doc, "driver")
    if kind == DISPATCH_GUIDE:
        if not driver:
            errors.append("Falta el conductor: la Guía de Despacho declara quién lleva la mercancía.")
        if not transport_value(doc, "vehicle_no"):
            errors.append("Falta la placa del vehículo: la Guía de Despacho declara en qué viaja.")
    if driver:
        values: dict = frappe.db.get_value(
            "Driver", driver, ["full_name", "ve_id_type", "ve_id_number"], as_dict=True
        ) or {}
        missing: list[str] = [
            label for field, label in (
                ("full_name", "nombre"),
                ("ve_id_type", "tipo de identificación"),
                ("ve_id_number", "número de identificación"),
            ) if not (values.get(field) or "").strip()
        ]
        if missing:
            errors.append(f"Al conductor {driver} le falta: {', '.join(missing)}.")

    transporter: str = transport_value(doc, "transporter")
    carrier_doctype, carrier_name = ("Supplier", transporter) if transporter else ("Company", doc.company)
    carrier_label: str = f"el transportista {transporter}" if transporter else f"la empresa {doc.company} (transporte propio)"
    if not (frappe.db.get_value(carrier_doctype, carrier_name, "tax_id") or "").strip():
        errors.append(f"Falta el RIF de {carrier_label}.")
    if not party_address_text(carrier_doctype, carrier_name):
        errors.append(f"Falta la dirección fiscal de {carrier_label}.")

    if doc.doctype == "Delivery Note":
        if not (frappe.db.get_value("Customer", doc.customer, "tax_id") or "").strip():
            errors.append(f"El cliente {doc.customer} no tiene RIF o cédula.")
        if not doc.get("contact_mobile"):
            errors.append("Falta el teléfono de contacto del cliente en la nota.")
        if not flt(doc.get("base_net_total")):
            # El caso típico es un equipo en comodato. Qué valor declarar ahí es una decisión
            # fiscal; el 04 no la toma por el usuario.
            errors.append("La nota no tiene valor (precio cero): el documento fiscal declara el valor de la mercancía.")
        errors.extend(delivery_note_tax_problems(doc))
    else:
        # Cada línea declara el valor de lo que viaja: una en cero diría que esa mercancía no vale nada.
        unvalued: list[str] = [
            item.get("item_code") or "?" for item in doc.get("items") or [] if flt(item.get("basic_rate")) <= 0
        ]
        if unvalued:
            errors.append(
                f"Ítems sin costo de valoración: {', '.join(unvalued)}. El documento fiscal declara "
                "el valor de cada uno."
            )

    return errors


# ---------------------------------------------------------------------------
# Hooks del documento
# ---------------------------------------------------------------------------

def rerate_delivery_note_on_submit(doc, method: str | None = None) -> None:
    """`before_validate` de Delivery Note: al aprobar, la nota toma la tasa de emisión.

    Es la misma regla y la misma función que la factura (`rerate_juridical_on_submit`):
    jurídico a la tasa de hoy, natural a la del 1° del mes. Solo cuando el 04 aplica: con el
    interruptor apagado ninguna nota de entrega cambia de tasa.

    La sucursal se resuelve acá y no recién en `before_submit`, porque el retasado busca la
    serie de esa sucursal. Es la misma `set_ve_branch` que ya corre en toda nota de entrega;
    solo se adelanta.
    """
    if getattr(doc, "_action", None) != "submit" or not dispatch_note_applies(doc):
        return

    from l10n_ve.digital_invoice.emission_rerate import rerate_juridical_on_submit
    from l10n_ve.helpers.helpers import set_ve_branch

    if not doc.get("branch"):
        set_ve_branch(doc, method)
    rerate_juridical_on_submit(doc, method)


def prepare_dispatch_note_on_submit(doc, method: str | None = None) -> None:
    """`before_submit`: si el 04 aplica, valida los datos del traslado y lo deja Pendiente.

    Cortar acá es lo que evita un documento aprobado que el cron no puede emitir: después de
    aprobado, el conductor o el motivo ya no se corrigen sin cancelar.

    Un documento que NO emite el 04 queda sin tipo: el filtro y la lista lo contarían como una
    orden de entrega o una guía que no es. Pasa con las devoluciones --heredan el tipo de la
    nota original--, los traslados sin guía y los sitios con el 04 apagado.
    """
    if not dispatch_note_applies(doc):
        if doc.get("ve_dispatch_document_kind"):
            doc.ve_dispatch_document_kind = None
        return

    errors: list[str] = validate_dispatch_data(doc)
    if errors:
        frappe.throw(
            _("No se puede aprobar: el documento fiscal 04 no se podría emitir.")
            + "<br><br>"
            + "<br>".join(f"• {frappe.utils.escape_html(error)}" for error in errors),
            title=_("Datos del despacho incompletos"),
        )

    # Se persiste con el propio submit, como `hka_status` de la factura en su `before_submit`.
    doc.hka_status = "Pendiente"


def block_cancel_if_emitted(doc, method: str | None = None) -> None:
    """`before_cancel`: un 04 emitido no se cancela en Frappe; se anula ante HKA.

    Lo que habilita la cancelación es el estado `Anulada`, que `void_dispatch_note` persiste
    en cuanto HKA confirma. Es el estado y no una bandera del request a propósito: si la
    cancelación falla por otro motivo (un documento vinculado, el stock), HKA ya anuló, y el
    documento tiene que poder cancelarse después sin volver a pasar por HKA.
    """
    if doc.get("hka_status") == "Anulada":
        return

    if doc.get("bill_control") or doc.get("hka_status") == "Emitida":
        frappe.throw(
            _(
                "El documento fiscal 04 de {0} ya fue emitido ante HKA (control {1}). Para "
                "deshacerlo, anúlelo ante HKA con el botón «Anular en HKA»: eso cancela también "
                "el documento."
            ).format(doc.name, doc.get("bill_control") or "—"),
            title=_("Cancelación bloqueada"),
        )

    # Pendiente o con error: se puede cancelar, salvo que se esté enviando en este momento. El
    # mutex queda tomado hasta que la cancelación se confirme o se revierta: soltarlo acá
    # dejaría un hueco en el que el cron lo toma, ve el documento todavía aprobado y lo emite
    # ante HKA mientras Frappe lo cancela. Si el proceso muere en el medio, el TTL lo suelta.
    if doc.get("hka_status") in ("Pendiente", "Error"):
        if not _acquire_hka_send_lock(doc.doctype, doc.name):
            frappe.throw(
                _("{0} se está enviando a HKA en este momento. Intente de nuevo en un minuto.").format(
                    doc.name
                ),
                title=_("Envío en curso"),
            )
        release = functools.partial(_release_hka_send_lock, doc.doctype, doc.name)
        frappe.db.after_commit.add(release)
        frappe.db.after_rollback.add(release)


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------

def _validate_delivery_note_rate(doc, emission: datetime.datetime) -> list[str]:
    """La nota de entrega en divisa debe portar la tasa de la regla el día que se emite.

    Al aprobar se retasó; esto cubre la que se reintenta días después, o la que se aprobó
    con el interruptor apagado. Una nota aprobada ya no se retasa: se cancela y se rehace.
    """
    company_currency: str = frappe.get_cached_value("Company", doc.company, "default_currency")
    if not doc.currency or doc.currency == company_currency:
        return []

    expected: float = flt(get_ve_exchange_rate_for_customer(doc.customer, str(emission.date()), doc.currency))
    if not expected:
        # Sin tasa publicada para hoy: mismo criterio que la factura, se emite con la que porta.
        return []

    if abs(expected - flt(doc.conversion_rate)) < _RATE_TOLERANCE:
        return []

    message: str = (
        f"La tasa de la nota ({flt(doc.conversion_rate)}) no es la que corresponde al cliente "
        f"el día de emisión ({expected}). Cancele la nota y vuelva a hacerla para que tome la "
        "tasa del día."
    )
    return [message]


def _ensure_dispatch_number(doc, series_doc) -> None:
    """Número del 04 en modo Interno. En Tercero lo asigna HKA y no se toca nada.

    Idempotente: si el documento ya tiene número, lo reutiliza, esté en Error o todavía en
    Pendiente. La factura solo reutiliza desde Error porque arrastra números de un flujo
    legacy; el 04 no tiene legado, así que cualquier número que tenga lo puso este flujo. El
    caso que cubre el Pendiente: el proceso murió entre tomar el número --ya commiteado,
    antes del viaje a HKA-- y marcar el fallo. Tomar otro dejaría quemado el primero, o dos
    documentos fiscales si el primero sí había llegado.
    """
    if getattr(series_doc, "operation_mode", "Internal") == "Third Party":
        return
    if str(doc.get("bill_no") or "").strip():
        return

    number: str = series_doc.take_dispatch_note_number()
    frappe.db.set_value(doc.doctype, doc.name, "bill_no", number, update_modified=False)
    doc.bill_no = number


def _build_payload(doc, series_doc, branch_code: str, emission: datetime.datetime) -> dict:
    builder_class = DeliveryNotePayloadBuilder if doc.doctype == "Delivery Note" else StockEntryDispatchPayloadBuilder
    return builder_class(doc, series_doc=series_doc, branch_code=branch_code, emission=emission).build_payload()


def _set_error(doc) -> None:
    """Deja el documento en Error sin pisar una emisión ya confirmada."""
    if not frappe.db.get_value(doc.doctype, doc.name, "bill_control"):
        frappe.db.set_value(doc.doctype, doc.name, "hka_status", "Error", update_modified=False)


def _handle_dispatch_response(doc, payload: dict, response: dict, series_doc) -> bool:
    """Procesa la respuesta de HKA. Solo el 200 es una emisión.

    El 201 es «duplicado»: HKA ya tiene un documento con ese TransaccionId. Con
    `build_transaction_id` debería ser el mismo documento reintentado, pero la regla del
    módulo es no darlo por bueno (ver AGENTS.md): queda en Error, con la respuesta en el
    log, para que alguien lo verifique en HKA antes de adoptar sus números.
    """
    code: str = str((response or {}).get("codigo", ""))

    if response and not response.get("error") and code == "200":
        resultado: dict = response.get("resultado") or {}
        number: str = resultado.get("numeroDocumento") or ""
        control: str = resultado.get("numeroControl") or ""
        updates: dict = {
            "hka_status": "Emitida",
            "hka_series": resultado.get("serie") or getattr(series_doc, "serie", "") or "",
            # La lee el panel «Documento Fiscal Digital» y la descarga del PDF, igual que en
            # los comprobantes de retención.
            "hka_response": json.dumps(response, ensure_ascii=False, indent=2),
        }
        if control:
            updates["bill_control"] = control
        is_third_party: bool = getattr(series_doc, "operation_mode", "Internal") == "Third Party"
        if is_third_party and number:
            updates["bill_no"] = number
        frappe.db.set_value(doc.doctype, doc.name, updates, update_modified=False)
        # Los números que devolvió HKA ya son un hecho fiscal: se confirman ANTES de escribir
        # el log. Si el log fallaba (p. ej. entre el deploy y el migrate, cuando el Select de
        # `VE Digital Invoice Log` todavía no tiene «Stock Entry»), la excepción revertía
        # también estos números: el documento quedaba emitido en HKA y sin control en el
        # ERP, y el reintento recibía el 201 de duplicado. Medido en HKA demo el 24-sep.
        if not frappe.flags.in_test:
            frappe.db.commit()  # nosemgrep

        notes: str = f"Documento 04 emitido. N° {number or doc.get('bill_no')}, control {control or '—'}."
        if not is_third_party and number and number != doc.get("bill_no"):
            notes += (
                f" Ojo: HKA confirmó el número {number}, distinto al asignado localmente "
                f"({doc.get('bill_no')}); el documento conserva el local."
            )
        if not control:
            notes += " HKA no devolvió número de control."
        try:
            _log_request("Emision", doc.name, payload, response, "Success", notes=notes, doctype=doc.doctype)
        except Exception:
            # La emisión ya quedó guardada; que falte el log no la deshace, pero se deja rastro.
            frappe.log_error(
                title=f"04 {doc.name} emitido (control {control or '—'}) pero sin log de HKA",
                message=frappe.get_traceback(),
            )
        return True

    if not response:
        _set_error(doc)
        _log_request(
            "Emision", doc.name, payload, {}, "Error",
            notes="La API de HKA no devolvió respuesta (timeout o error de conexión).",
            doctype=doc.doctype,
        )
        return False

    if code == "201":
        _set_error(doc)
        _log_request(
            "Emision", doc.name, payload, response, "Error",
            notes=(
                "HKA respondió 201 (documento duplicado): ya tiene un documento con este "
                "TransaccionId. Puede ser un envío anterior que sí llegó. Verifique en HKA "
                "antes de reintentar; no se adoptaron los números de la respuesta."
            ),
            doctype=doc.doctype,
        )
        return False

    validations: list = response.get("validaciones") or []
    message: str = response.get("mensaje") or response.get("message") or ""
    parts: list[str] = []
    if message:
        parts.append(f"Mensaje: {message}")
    if validations:
        parts.append("Validaciones: " + "; ".join(str(v) for v in validations))
    _set_error(doc)
    _log_request("Emision", doc.name, payload, response, "Error", notes="\n".join(parts), doctype=doc.doctype)

    all_text: str = (" ".join(str(v) for v in validations) + " " + message).lower()
    if any(keyword in all_text for keyword in _RANGE_EXHAUSTED_KEYWORDS):
        raise HKARangeExhausted(f"Serie agotada: HKA no tiene rango de numeración (detectado en {doc.name}).")
    return False


def process_dispatch_note(doctype: str, name: str, raise_on_error: bool = False) -> bool:
    """Emite el 04 de un documento. True si HKA lo emitió (o ya estaba emitido)."""
    if doctype not in DISPATCH_DOCTYPES:
        frappe.throw(_("{0} no emite el documento fiscal 04.").format(doctype))

    if not _acquire_hka_send_lock(doctype, name):
        frappe.logger("l10n_ve").info(f"04 {doctype} {name}: ya se está enviando en otro proceso; se omite.")
        return False

    payload: dict = {}
    try:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus != 1:
            frappe.throw(
                _("{0} no está aprobado: solo se emite el 04 de documentos aprobados.").format(doc.name)
            )
        if doc.get("bill_control"):
            return True  # ya emitido: el reintento no hace nada

        if not dispatch_note_applies(doc):
            frappe.throw(
                _(
                    "{0} no se emite como documento fiscal 04 (interruptor del sitio apagado, "
                    "empresa sin serie digital, devolución o traslado que no pide guía)."
                ).format(doc.name)
            )

        emission: datetime.datetime = now_datetime()
        errors: list[str] = validate_dispatch_data(doc)
        series_doc, branch_code = get_active_billing_series(company=doc.company, branch=doc.get("branch") or "")

        if doc.doctype == "Delivery Note":
            errors.extend(_validate_delivery_note_rate(doc, emission))
            apply_delivery_note_tax_regime(doc)
            errors.extend(_validate_invoice_integrity(doc))

        if not errors:
            # La integridad se valida ANTES de tomar el número: un documento que no se va a
            # enviar no quema un correlativo fiscal.
            _ensure_dispatch_number(doc, series_doc)
            payload = _build_payload(doc, series_doc, branch_code, emission)
            if doc.doctype == "Delivery Note":
                # El mismo control de montos que la factura, sobre el payload ya armado.
                errors.extend(_validate_payload_vs_invoice(payload, doc))

        if errors:
            message: str = f"Validación previa del 04 fallida para {doctype} {name}:\n" + "\n".join(
                f"  • {error}" for error in errors
            )
            _set_error(doc)
            _log_request("Validación Pre-Envío HKA", name, payload, {"error": True, "message": message},
                         "Error", notes=message, doctype=doctype)
            # El estado y el log tienen que sobrevivir al throw de abajo (camino del botón) y al
            # rollback del cron: son lo único que explica por qué no salió.
            frappe.db.commit()  # nosemgrep
            if raise_on_error:
                # El diálogo lo pinta como HTML y los errores traen datos del documento (ítems,
                # nombres): se escapan, como al aprobar.
                frappe.throw(
                    "<br>".join(frappe.utils.escape_html(line) for line in message.split("\n")),
                    title=_("Documento de despacho no enviado"),
                )
            return False

        # commit-antes-del-IO: el correlativo de la serie (modo Interno) queda tomado y
        # liberado antes del viaje de red. La exclusión mutua la sostiene el mutex.
        if not frappe.flags.in_test:
            frappe.db.commit()  # nosemgrep

        response: dict = TFHKAClient().emitir_documento(payload)
        success: bool = _handle_dispatch_response(doc, payload, response, series_doc)
        # Lo que HKA respondió ya es un hecho fiscal: se persiste antes de cualquier throw.
        frappe.db.commit()  # nosemgrep
        if not success and raise_on_error:
            frappe.throw(
                _(
                    "HKA no emitió el documento fiscal de {0}. El detalle quedó en el registro de "
                    "facturación digital (VE Digital Invoice Log)."
                ).format(name),
                title=_("Documento de despacho no emitido"),
            )
        return success

    except HKARangeExhausted:
        # El Error y el log los escribió _handle_dispatch_response; el raise los revertiría.
        frappe.db.commit()  # nosemgrep
        raise
    except frappe.ValidationError:
        # Un throw del armado: serie, datos del traslado, montos. Queda en Error y en el log,
        # para que el aviso diga el motivo. En el botón el mensaje además se muestra, así que
        # ahí no se desencola.
        _mark_failure(doctype, name, payload, _last_message(clear=not raise_on_error))
        if raise_on_error:
            raise
        return False
    except Exception as error:
        traceback: str = frappe.get_traceback(with_context=True) or str(error)
        frappe.logger("l10n_ve").error(f"04 {doctype} {name}: {traceback}")
        _mark_failure(doctype, name, payload, traceback)
        if raise_on_error:
            raise
        return False
    finally:
        _release_hka_send_lock(doctype, name)


def _mark_failure(doctype: str, name: str, payload: dict, notes: str) -> None:
    """Deja el documento en Error con su log. Si esto también falla, gana el error original."""
    try:
        _set_error(frappe._dict(doctype=doctype, name=name))
        _log_request("Emision", name, payload, {"error": True, "message": notes[:500]}, "Error",
                     notes=notes, doctype=doctype)
        # Tiene que sobrevivir al raise del botón y al rollback del cron.
        frappe.db.commit()  # nosemgrep
    except Exception:  # noqa: BLE001 - es el registro de un fallo: no puede tapar el fallo
        frappe.logger("l10n_ve").exception(f"04 {doctype} {name}: no se pudo registrar el fallo")


def _last_message(clear: bool = True) -> str:
    """El texto del último `frappe.throw`, sin el HTML del diálogo, para el log.

    Con `clear`, además se desencola: en el cron nadie lo va a ver y se acumularía.
    """
    messages: list = frappe.local.message_log or []
    if not messages:
        return ""
    last = messages[-1]
    text: str = last.get("message", "") if isinstance(last, dict) else str(last)
    if clear:
        frappe.clear_last_message()
    return frappe.utils.strip_html_tags(text).strip()


@frappe.whitelist()
def send_dispatch_note_manually(doctype: str, name: str) -> str:
    """Botón «Enviar a HKA» del formulario (documento Pendiente o en Error)."""
    if doctype not in DISPATCH_DOCTYPES:
        frappe.throw(_("{0} no emite el documento fiscal 04.").format(doctype))
    frappe.has_permission(doctype, "submit", doc=name, throw=True)
    process_dispatch_note(doctype, name, raise_on_error=True)
    return "Documento fiscal emitido ante HKA."


# ---------------------------------------------------------------------------
# Cron: paso 4 de send_pending_documents_to_hka
# ---------------------------------------------------------------------------

def send_pending_dispatch_notes(tfhka_settings: dict) -> None:
    """Envía los 04 pendientes y los que fallaron, igual que la factura reintenta los suyos.

    En modo Interno, un error frena el resto de esa serie: el número que se quedó el
    documento fallido no puede quedar como hueco detrás de los siguientes. En Tercero HKA
    numera y se sigue de largo. Un rango agotado frena la serie en los dos modos.
    """
    if not dispatch_notes_enabled():
        return

    cutoff_date: str = str(tfhka_settings.get("cutoff_date") or "2026-04-01")
    halted: set[str] = set()
    sent: list[str] = []
    failed: list[str] = []

    for doctype in DISPATCH_DOCTYPES:
        for name in _get_pending_dispatch_notes(doctype, cutoff_date):
            company, branch = frappe.db.get_value(doctype, name, ["company", "branch"]) or ("", "")
            try:
                series_doc, _branch_code = get_active_billing_series(company=company, branch=branch or "")
            except frappe.ValidationError:
                frappe.clear_last_message()
                series_doc = None
            series_name: str = getattr(series_doc, "name", "") or ""
            if series_name and series_name in halted:
                continue

            try:
                ok: bool = process_dispatch_note(doctype, name)
            except HKARangeExhausted:
                ok = False
                halted.add(series_name)
            except Exception:  # noqa: BLE001 - un documento no frena la tanda; process_* ya lo registró
                frappe.db.rollback()
                frappe.logger("l10n_ve").exception(f"04 {doctype} {name}: falla inesperada en el cron")
                ok = False

            (sent if ok else failed).append(name)
            if not ok and series_doc and getattr(series_doc, "operation_mode", "Internal") == "Internal":
                halted.add(series_name)
            time.sleep(_DELAY_BETWEEN_CALLS)

    if sent or failed:
        lines: list[str] = [f"Documentos 04: {len(sent)} emitidos, {len(failed)} con error."]
        if sent:
            lines.append(f"Emitidos: {', '.join(sent)}")
        if failed:
            lines.append(f"Con error: {', '.join(failed)}")
        if halted:
            lines.append(f"Series detenidas: {', '.join(sorted(s for s in halted if s))}")
        _create_log_entry({
            "document_type": "Delivery Note",
            "endpoint": "HKA Cron Despacho",
            "status": "Success" if not failed else "Error",
            "notes": "\n".join(lines),
        })
        # Corre en el scheduler: sin commit el resumen del lote se pierde.
        frappe.db.commit()  # nosemgrep


#: Una consulta por doctype, sin interpolar nada: los filtros propios de cada uno van escritos.
_PENDING_QUERIES: dict[str, str] = {
    "Delivery Note": """
        SELECT d.name
        FROM `tabDelivery Note` d
        WHERE d.docstatus = 1
          AND d.is_return = 0
          AND d.posting_date >= %(cutoff)s
          AND d.hka_status IN ('Pendiente', 'Error')
          AND (d.bill_control IS NULL OR d.bill_control = '')
        ORDER BY d.posting_date, d.creation
        LIMIT %(limit)s
    """,
    "Stock Entry": """
        SELECT d.name
        FROM `tabStock Entry` d
        WHERE d.docstatus = 1
          AND d.purpose = 'Material Transfer'
          AND d.ve_issue_dispatch_note = 1
          AND d.posting_date >= %(cutoff)s
          AND d.hka_status IN ('Pendiente', 'Error')
          AND (d.bill_control IS NULL OR d.bill_control = '')
        ORDER BY d.posting_date, d.creation
        LIMIT %(limit)s
    """,
}


def _get_pending_dispatch_notes(doctype: str, cutoff_date: str) -> list[str]:
    """Documentos aprobados, marcados para el 04, sin número de control todavía."""
    query: str | None = _PENDING_QUERIES.get(doctype)
    if not query:
        return []
    rows = frappe.db.sql(query, {"cutoff": cutoff_date, "limit": _BATCH_SIZE})
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Anulación ante HKA
# ---------------------------------------------------------------------------

@frappe.whitelist()
def void_dispatch_note(doctype: str, name: str, reason: str) -> dict:
    """Anula el 04 ante HKA y, si HKA lo confirma, cancela el documento en Frappe.

    HKA deshabilitó el 01-sep-2026 la anulación directa de FACTURAS; el aviso no nombra el
    04. Si HKA la rechaza, el error sale tal cual y el documento queda como estaba.
    """
    if doctype not in DISPATCH_DOCTYPES:
        frappe.throw(_("{0} no emite el documento fiscal 04.").format(doctype))

    doc = frappe.get_doc(doctype, name)
    frappe.has_permission(doctype, "cancel", doc=doc, throw=True)

    reason = " ".join((reason or "").split())
    if not reason:
        frappe.throw(_("Indique el motivo de la anulación."))
    # HKA identifica el documento a anular por serie, tipo y número; el control no hace falta.
    # Pedirlo dejaría sin forma de anular un 200 que llegó sin número de control.
    if doc.docstatus != 1 or doc.get("hka_status") != "Emitida" or not doc.get("bill_no"):
        frappe.throw(_("Solo se anula ante HKA un documento aprobado y ya emitido."))

    now: datetime.datetime = now_datetime()
    payload: dict = {
        "serie": doc.get("hka_series") or "",
        "tipoDocumento": DISPATCH_DOCUMENT_TYPE,
        "numeroDocumento": doc.get("bill_no") or "",
        "motivoAnulacion": reason[:255],
        "fechaAnulacion": now.strftime("%d/%m/%Y"),
        "horaAnulacion": now.strftime("%I:%M:%S %p").lower(),
    }

    client = TFHKAClient()
    client.authenticate()
    result: dict = client.void_document(payload) or {}

    if result.get("error") or not result.get("_http_ok"):
        detail: str = result.get("mensaje") or result.get("message") or "Error desconocido"
        _log_request("Anular", doc.name, payload, result, "Error", notes=detail, doctype=doctype)
        # El rechazo queda en el log aunque el throw revierta el request.
        frappe.db.commit()  # nosemgrep
        frappe.throw(
            _("HKA rechazó la anulación. Código: {0} | Respuesta: {1}").format(
                result.get("codigo", "—"), detail
            ),
            title=_("Error al anular en HKA"),
        )

    # HKA ya anuló: eso se persiste ANTES de cancelar. Si la cancelación falla, el rollback
    # del request no puede llevarse el estado, porque el documento fiscal ya no existe.
    _log_request("Anular", doc.name, payload, result, "Success", notes=f"Motivo: {reason}", doctype=doctype)
    frappe.db.set_value(doctype, name, "hka_status", "Anulada", update_modified=False)
    doc.add_comment("Comment", f"Documento fiscal 04 anulado ante HKA. Motivo: {reason}")
    frappe.db.commit()  # nosemgrep

    doc.reload()
    doc.cancel()
    return {"status": "success", "message": "Documento anulado ante HKA y cancelado."}
