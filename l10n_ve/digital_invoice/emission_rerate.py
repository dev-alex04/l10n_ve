# Copyright (c) 2026, Grupo Altia
"""
Retasado a tasa de emisión para clientes jurídicos.

La factura fiscal debe expresarse en Bs a la tasa BCV vigente en la fecha
de emisión del documento (Ley IVA Art. 25 / Providencia SNAT/2011/0071).
El flujo ISP paga primero y el cron emite después: si la emisión cae otro
día, la factura porta la tasa del pago. Este módulo retasa la Sales Invoice
submitted a la tasa del día ANTES de construir el payload HKA, re-derivando
los montos Bs (ítems, impuestos, totales), regenerando el ledger del voucher
y posteando el diferencial cambiario sobre lo ya cobrado.

El IGTF NO se retasa: es un impuesto sobre el pago (su GL vive en el
Payment Entry a la tasa del cobro) y recalculate_invoice_igtf lo re-deriva
desde los pagos ante cualquier evento del Payment Ledger; un valor escalado
aquí sería sobrescrito.
"""

import frappe
from frappe.utils import cint, flt, today

from l10n_ve.utils.utils import (
    get_exchange_rate,
    is_juridical_customer,
    resolve_exchange_rate_date,
)

RERATE_TAG = "[retasado-emision]"

# Delta mínimo (en moneda de la cuenta CxC) para postear diferencial.
_MIN_FX_DELTA = 0.01

# Tolerancia de comparación de tasas cuando no se puede decidir por fecha.
_RATE_TOLERANCE = 0.0001

# Campos monetarios del padre que se persisten tras el recálculo.
# NUNCA incluir outstanding_amount/status: calculate_taxes_and_totals()
# los recalcula en memoria ignorando los Payment Entries reconciliados
# (una factura Paid quedaría con outstanding = total completo).
_PARENT_FIELDS = (
    "conversion_rate",
    "plc_conversion_rate",
    "base_total",
    "base_net_total",
    "base_total_taxes_and_charges",
    "base_grand_total",
    "base_rounded_total",
    "base_rounding_adjustment",
    "base_discount_amount",
    "base_total_exempt",
    "base_total_with_vat",
    "base_in_words",
)

_LEDGER_TABLES = ("GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry")


def rerate_to_emission_rate(doc: object) -> bool:
    """
    Retasa `doc` (Sales Invoice submitted de cliente jurídico) a la tasa BCV
    de hoy si la tasa que porta corresponde a otra fecha.

    Muta y recarga `doc` en el proceso: el caller puede seguir usándolo.
    Retorna True si retasó, False si no aplicaba (no-op).

    Lanza frappe.ValidationError (tras rollback al savepoint) si el retasado
    falla a mitad: ese camino cae en el `raise` de process_invoice y evita
    el commit del except genérico.
    """
    new_rate = _get_target_rate(doc)
    if new_rate is None:
        return False

    reason = _blocking_condition(doc)
    if reason:
        _log_skip(doc, reason)
        return False

    # Lock de fila (cron */5 min vs botón manual) + re-check post-lock.
    if frappe.db.get_value(doc.doctype, doc.name, "bill_control", for_update=True):
        return False

    old_rate = flt(doc.conversion_rate)
    frappe.db.savepoint("hka_rerate")
    try:
        _apply_rate_in_memory(doc, new_rate)
        _persist_recalculated_fields(doc)
        _regenerate_voucher_ledger(doc)
        _post_fx_difference(doc, old_rate, new_rate)
        _close_outstanding_and_status(doc)
    except Exception:
        frappe.db.rollback(save_point="hka_rerate")
        tb = frappe.get_traceback(with_context=True)
        frappe.logger("l10n_ve").error(
            f"Retasado a tasa de emisión falló para {doc.name}: {tb}"
        )
        raise frappe.ValidationError(
            f"El retasado a tasa de emisión falló para {doc.name}; "
            "no se envió a HKA. Revise el log de l10n_ve."
        )

    doc.add_comment(
        "Comment",
        f"Retasado a tasa de emisión: {old_rate} → {new_rate} "
        f"(Bs por 1 {doc.currency}).",
    )
    frappe.logger("l10n_ve").info(
        f"{RERATE_TAG} {doc.name}: {old_rate} → {new_rate}"
    )
    return True


def _get_target_rate(doc: object) -> float | None:
    """
    Gate del retasado. Retorna la tasa BCV de hoy si el documento debe
    retasarse, o None si no aplica.

    La decisión es POR FECHA (lookup inverso de la tasa que porta el doc
    vs. fecha efectiva de hoy), no por valor: en Currency Exchange existen
    tasas del mismo día que difieren entre sí ~1e-4 y compararlas por valor
    dispararía retasados en bucle.
    """
    if doc.doctype != "Sales Invoice":
        return None
    if cint(doc.docstatus) != 1:
        return None
    if doc.get("bill_control"):
        return None
    if not flt(doc.conversion_rate):
        return None

    company_currency = frappe.get_cached_value(
        "Company", doc.company, "default_currency"
    )
    # Factura en moneda de curso legal: no hay carril Bs que retasar.
    if (doc.currency or company_currency) == company_currency:
        return None

    if not is_juridical_customer(doc.customer):
        return None

    new_rate = flt(get_exchange_rate(today(), doc.currency))
    if not new_rate:
        return None

    current_date = resolve_exchange_rate_date(flt(doc.conversion_rate), doc.currency)
    target_date = resolve_exchange_rate_date(new_rate, doc.currency)
    if current_date and target_date and str(current_date) == str(target_date):
        return None

    # Sin fecha resoluble para la tasa actual (tasa manual/histórica):
    # decidir por valor con tolerancia.
    if abs(new_rate - flt(doc.conversion_rate)) < _RATE_TOLERANCE:
        return None

    return new_rate


def _blocking_condition(doc: object) -> str | None:
    """
    Condiciones bajo las cuales NO se retasa (se emite con la tasa que porta
    el documento, comportamiento previo) y se deja rastro en el Error Log.
    Retorna la razón o None.
    """
    if cint(frappe.get_cached_value("Customer", doc.customer, "disabled")):
        # Regenerar el GL de un cliente deshabilitado revienta en la
        # validación de party (PartyDisabled) — la emisión SIN retasa no
        # toca el GL y sí procede. Descubierto en smoke (17-jul-2026).
        return "el cliente está deshabilitado (no se puede regenerar su GL)"

    # Los anticipos aplicados YA NO bloquean (30-jul-2026). El motivo original era que
    # make_gl_entries() dispararia make_exchange_gain_loss_journal contra los PEs de
    # anticipo, duplicando asientos en reintentos. Medido sobre datos de produccion
    # (retasado real de 5 facturas con anticipos, dentro de una transaccion con
    # rollback): crea CERO asientos nuevos, el diferencial queda posteado UNA sola vez
    # --el de _post_fx_difference, exacto contra el delta-- y el mayor de la factura
    # cuadra. El flag through_repost_accounting_ledger que activa
    # _regenerate_voucher_ledger ya neutraliza el asiento de ERPNext.
    #
    # Quitarlo lleva de 29 a 72 las facturas juridicas represadas que se emiten con la
    # tasa correcta (Ley IVA Art. 25). Las 36 restantes que traian anticipos siguen
    # bloqueadas, pero por _find_unsupported_credit: esta condicion iba antes y tapaba
    # a la otra.

    if any(cint(item.get("enable_deferred_revenue")) for item in doc.get("items") or []):
        return "tiene ítems con ingreso diferido (enable_deferred_revenue)"

    payment_entries = _get_allocating_payment_entries(doc)
    if payment_entries and frappe.db.get_value(
        "Payment Entry Deduction",
        {"parent": ("in", payment_entries)},
        "parent",
    ):
        # Retención IVA/ISLR del contribuyente especial registrada como
        # deducción del pago sobre el IVA Bs viejo: retasar descuadraría
        # el comprobante ya emitido.
        return "tiene pagos con deducciones (retenciones) registradas"

    foreign = _find_unsupported_credit(doc)
    if foreign:
        return f"tiene créditos de origen no soportado ({foreign})"

    return None


def _get_allocating_payment_entries(doc: object) -> list[str]:
    rows = frappe.get_all(
        "Payment Ledger Entry",
        filters={
            "against_voucher_type": "Sales Invoice",
            "against_voucher_no": doc.name,
            "voucher_type": "Payment Entry",
            "docstatus": 1,
            "delinked": 0,
        },
        pluck="voucher_no",
        distinct=True,
    )
    return rows or []


def _find_unsupported_credit(doc: object) -> str | None:
    """
    El cálculo del diferencial asume que los créditos contra la factura
    vienen de Payment Entries o de nuestros propios JEs de diferencial.
    Cualquier otro origen (JE manual, nota aplicada, etc.) invalida la
    aritmética: se omite el retasado.
    """
    rows = frappe.get_all(
        "Payment Ledger Entry",
        filters={
            "against_voucher_type": "Sales Invoice",
            "against_voucher_no": doc.name,
            "docstatus": 1,
            "delinked": 0,
            "voucher_no": ("!=", doc.name),
        },
        fields=["voucher_type", "voucher_no"],
        distinct=True,
    )
    for row in rows:
        if row.voucher_type == "Payment Entry":
            continue
        if row.voucher_type == "Journal Entry":
            remark = (
                frappe.db.get_value("Journal Entry", row.voucher_no, "user_remark")
                or ""
            )
            if RERATE_TAG in remark:
                continue
        return f"{row.voucher_type} {row.voucher_no}"
    return None


def _apply_rate_in_memory(doc: object, new_rate: float) -> None:
    doc.conversion_rate = new_rate
    doc.plc_conversion_rate = new_rate
    # VESalesInvoice.calculate_taxes_and_totals() corre el motor VE completo
    # (anclaje del carril Bs según el Método de cálculo de Impuestos).
    doc.calculate_taxes_and_totals()
    # base_total_with_vat (Bs, lo consumen reportes financieros) se deriva
    # en validate(), que aquí no corre: re-derivar explícito.
    if hasattr(doc, "_set_base_total_with_vat"):
        doc._set_base_total_with_vat()
    if hasattr(doc, "set_total_in_words"):
        doc.set_total_in_words()
    for row in doc.get("payment_schedule") or []:
        row.base_payment_amount = flt(flt(row.payment_amount) * new_rate, 2)


def _persist_recalculated_fields(doc: object) -> None:
    """
    Persistencia selectiva en un documento submitted: children fila a fila
    (no tienen estado de cobranza) y el padre con lista explícita de campos.
    PROHIBIDO doc.db_update() del padre: escribiría el outstanding/status
    corruptos que calculate_taxes_and_totals() dejó en memoria.
    """
    child_rows = (
        list(doc.get("items") or [])
        + list(doc.get("taxes") or [])
        + list(doc.get("payment_schedule") or [])
    )
    for row in child_rows:
        row.db_update()

    values = {
        field: doc.get(field)
        for field in _PARENT_FIELDS
        if doc.meta.has_field(field)
    }
    frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)


def _regenerate_voucher_ledger(doc: object) -> None:
    """
    Patrón delete de Repost Accounting Ledger: borra GL/PLE/Advance PLE del
    voucher y los regenera con los base_* nuevos. Destructivo a propósito
    (sin flip de docstatus) para no acumular asientos reversos en
    reintentos; solo corre pre-certificación (bill_control vacío).
    Los ledgers de los Payment Entries contra la factura NO se tocan.
    """
    for table in _LEDGER_TABLES:
        if frappe.db.table_exists(table):
            frappe.db.delete(
                table, filters={"voucher_type": doc.doctype, "voucher_no": doc.name}
            )

    previous_flag = frappe.flags.through_repost_accounting_ledger
    frappe.flags.through_repost_accounting_ledger = True
    try:
        doc.docstatus = 1
        doc.force_set_against_income_account()
        doc.make_gl_entries()
    finally:
        frappe.flags.through_repost_accounting_ledger = previous_flag


def _post_fx_difference(doc: object, old_rate: float, new_rate: float) -> None:
    """
    Postea el diferencial cambiario SOLO sobre lo ya cobrado.

    delta = outstanding_actual(PLE, moneda de cuenta)
            - (USD no pagado × tasa nueva)

    Con eso la porción no cobrada queda re-expresada a la tasa de emisión
    (la cobrará la política de cobro vigente) y la cobrada cierra contra
    ganancia/pérdida cambiaria. Como el outstanding ya incluye JEs de
    retasados anteriores, el delta es incremental e idempotente entre
    reintentos.
    """
    allocations = frappe.get_all(
        "Payment Ledger Entry",
        filters={
            "against_voucher_type": "Sales Invoice",
            "against_voucher_no": doc.name,
            "voucher_type": "Payment Entry",
            "docstatus": 1,
            "delinked": 0,
        },
        fields=["voucher_no", "amount_in_account_currency", "account_currency"],
    )
    if not allocations:
        return

    paid_in_invoice_currency = 0.0
    for entry in allocations:
        amount = abs(flt(entry.amount_in_account_currency))
        if (entry.account_currency or "") == doc.currency:
            paid_in_invoice_currency += amount
        else:
            pe_rate = flt(
                frappe.db.get_value("Payment Entry", entry.voucher_no, "exchange_rate")
            ) or old_rate
            paid_in_invoice_currency += amount / pe_rate

    invoice_total = flt(doc.get("rounded_total") or doc.grand_total)
    unpaid_in_invoice_currency = max(0.0, invoice_total - paid_in_invoice_currency)

    outstanding_in_account_currency = flt(
        frappe.db.sql(
            """
            SELECT SUM(amount_in_account_currency)
            FROM `tabPayment Ledger Entry`
            WHERE against_voucher_type = 'Sales Invoice'
              AND against_voucher_no = %s
              AND docstatus = 1 AND delinked = 0
            """,
            doc.name,
        )[0][0]
    )

    delta = flt(
        outstanding_in_account_currency - unpaid_in_invoice_currency * new_rate, 2
    )
    if abs(delta) < _MIN_FX_DELTA:
        return

    _make_fx_journal_entry(doc, delta, old_rate, new_rate)


def _make_fx_journal_entry(doc: object, delta: float, old_rate: float, new_rate: float) -> None:
    """Wrapper del retasado de Sales Invoice: arma el remark y delega."""
    make_fx_adjustment_je(
        company=doc.company,
        debit_to=doc.debit_to,
        customer=doc.customer,
        reference_invoice=doc.name,
        delta=delta,
        remark=(
            f"{RERATE_TAG} Diferencial cambiario por retasado a tasa de "
            f"emisión de {doc.name}: {old_rate} → {new_rate}."
        ),
        branch=doc.get("branch"),
        cost_center=doc.get("cost_center"),
    )


def make_fx_adjustment_je(
    *,
    company: str,
    debit_to: str,
    customer: str,
    reference_invoice: str,
    delta: float,
    remark: str,
    branch: str | None = None,
    cost_center: str | None = None,
) -> None:
    """
    Postea un Journal Entry de diferencial cambiario contra el CxC, con la
    fila del CxC referenciando la Sales Invoice para que su PLE cierre el
    outstanding.

    delta > 0: el CxC quedó inflado en Bs → crédito al CxC contra la
    cuenta de PÉRDIDA en cambio.
    delta < 0: el CxC quedó corto en Bs → débito al CxC contra la cuenta
    de GANANCIA en cambio.

    No se usa create_gain_loss_journal de erpnext: usa una sola cuenta de
    Company. Galanet separa 7101005 Ganancia en Cambio (configurada en
    unrealized_exchange_gain_loss_account) y 8101011 Pérdida en Cambio
    (exchange_gain_loss_account); se elige por signo.
    """
    loss_account, gain_account = frappe.get_cached_value(
        "Company",
        company,
        ["exchange_gain_loss_account", "unrealized_exchange_gain_loss_account"],
    )
    counter_account = loss_account if delta > 0 else (gain_account or loss_account)
    if not counter_account:
        frappe.throw(
            "La Company no tiene configurada la cuenta de ganancia/pérdida "
            "cambiaria (exchange_gain_loss_account); no se puede ajustar "
            f"el diferencial de la factura {reference_invoice}."
        )

    cost_center = cost_center or frappe.get_cached_value(
        "Company", company, "cost_center"
    )
    amount = abs(delta)

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Exchange Gain Or Loss"
    je.company = company
    je.posting_date = today()
    if je.meta.has_field("branch") and branch:
        je.branch = branch
    je.user_remark = remark
    je.append(
        "accounts",
        {
            "account": debit_to,
            "party_type": "Customer",
            "party": customer,
            "reference_type": "Sales Invoice",
            "reference_name": reference_invoice,
            "cost_center": cost_center,
            "credit_in_account_currency": amount if delta > 0 else 0,
            "debit_in_account_currency": amount if delta < 0 else 0,
        },
    )
    je.append(
        "accounts",
        {
            "account": counter_account,
            "cost_center": cost_center,
            "debit_in_account_currency": amount if delta > 0 else 0,
            "credit_in_account_currency": amount if delta < 0 else 0,
        },
    )
    je.flags.ignore_permissions = True
    je.insert()
    je.submit()


def validate_note_rate(doc: object) -> None:
    """
    Guard de emisión para NC/ND.

    NC: porta siempre la tasa de la factura afectada; el servidor se la
    re-aplica en cada validate mientras está en borrador
    (_inherit_branch_from_si). Si llegó a la emisión con otra tasa, algo la
    pisó fuera del flujo normal —o la factura afectada se retasó después de
    creada la nota—, y certificar así dejaría un diferencial en Bs contra el
    CxC de la factura. Se bloquea: regenerar la nota la deja correcta,
    porque la herencia vuelve a leer la tasa vigente de la factura.

    ND: la tasa arranca en la de la factura afectada pero es editable por
    diseño (el usuario puede reexpresarla al cambiar posting_date), así que
    aquí no hay invariante que exigir. Su par tasa/fecha lo valida
    _validate_tasa_coherencia contra Currency Exchange.
    """
    if doc.doctype != "VE Sales Credit Note":
        return

    company_currency = frappe.get_cached_value(
        "Company", doc.company, "default_currency"
    )
    if (doc.currency or company_currency) == company_currency:
        return
    if not doc.get("return_against"):
        return

    expected = flt(
        frappe.db.get_value("Sales Invoice", doc.return_against, "conversion_rate")
    )
    if not expected:
        # Factura sin tasa utilizable: lo decide _validate_tasa_coherencia.
        return
    if abs(expected - flt(doc.conversion_rate)) < _RATE_TOLERANCE:
        return

    frappe.throw(
        f"La Nota de Crédito {doc.name} porta la tasa "
        f"{flt(doc.conversion_rate)}, que no es la de la factura afectada "
        f"{doc.return_against} (tasa de la factura: {expected}). "
        "Anule la nota y génerela de nuevo para que herede la tasa correcta.",
        title="Tasa inconsistente con la factura afectada",
    )


def cancel_credit_note_fx_truing(nc_doc: object) -> None:
    """
    Anula los JEs de ajuste cambiario que dejó una NC emitida bajo la regla
    de tasa propia (16-jul-2026 → 24-jul-2026). Desde que la NC hereda la
    tasa de la factura afectada no se generan asientos nuevos, pero los
    históricos siguen vivos y deben anularse con su nota.

    Solo aplica a cancelaciones pre-HKA: después de certificada, la
    cancelación de la NC está bloqueada por _block_cancel_if_sent_to_hka.
    """
    jes = frappe.get_all(
        "Journal Entry",
        filters={
            "docstatus": 1,
            "user_remark": (
                "like",
                f"{RERATE_TAG} Ajuste cambiario por NC {nc_doc.name}:%",
            ),
        },
        pluck="name",
    )
    for name in jes:
        je = frappe.get_doc("Journal Entry", name)
        je.flags.ignore_permissions = True
        je.cancel()


def _close_outstanding_and_status(doc: object) -> None:
    """
    Recalcula el outstanding desde el Payment Ledger y restaura el status
    en la MISMA transacción del retasado. Invariante de salida: una factura
    Paid vuelve a Paid con outstanding 0 (sigue elegible/emitible); una
    Unpaid queda re-expresada a la tasa nueva.
    """
    from erpnext.accounts.utils import update_voucher_outstanding

    update_voucher_outstanding(
        doc.doctype, doc.name, doc.debit_to, "Customer", doc.customer
    )
    doc.reload()
    doc.set_status(update=True)
    doc.reload()


def _log_skip(doc: object, reason: str) -> None:
    """
    El retasado se omite pero la emisión continúa con la tasa que porta el
    documento (comportamiento previo). Se registra en el Error Log para que
    la revisión operativa lo vea; NO se bloquea la emisión: un throw aquí
    sacaría la factura de la cola del cron para siempre.
    """
    frappe.log_error(
        title=f"Retasado a tasa de emisión omitido: {doc.name}",
        message=(
            f"La factura {doc.name} (jurídico {doc.customer_name}) se emitió con "
            f"la tasa que portaba ({flt(doc.conversion_rate)}) porque {reason}. "
            "Evaluar ajuste manual por nota de débito/crédito si aplica."
        ),
    )


def branch_has_active_digital_series(company: str, branch: str) -> bool:
    """¿La sucursal de la factura emite ante HKA? (serie de facturación digital activa).

    No se reutiliza `get_active_billing_series` de l10n_ve porque esa LANZA excepción
    cuando la sucursal no está en ninguna serie: acá sólo se necesita un booleano y una
    factura sin serie debe seguir su curso normal, no abortar el cobro.
    """
    if not company or not branch or branch.upper() == "N/A":
        return False

    return bool(frappe.db.sql("""
        SELECT 1
        FROM `tabVE Digital Billing Series Branch` child
        INNER JOIN `tabVE Digital Billing Series` serie ON serie.name = child.parent
        WHERE child.branch = %s AND serie.company = %s AND serie.status = 'Active'
        LIMIT 1
    """, (branch, company)))


def rerate_juridical_on_submit(doc: object, method: str | None = None) -> None:
    """Hook `before_validate` de Sales Invoice: retasa al aprobar, venga de donde venga.

    Este es el punto de estrangulamiento real. Enganchar el retasado en cada flujo de
    cobro NO alcanza: hay caminos que llaman `submit()` directamente sin pasar por
    `_submit_invoice_with_advances` --`reconcile_dashboard_payments`, la suscripción con
    `submit_invoice`, la regeneración desde Customer-- y esas facturas quedaban aprobadas
    con la tasa vieja. Caso real: ACC-SINV-2026-13907, cobrada el 30-jul y emitida a la
    tasa del 23-jul.

    Por qué `before_validate` y no `before_submit`
    ---------------------------------------------
    Medido sobre datos de producción, retasando en `before_submit` el padre se recalcula
    pero las filas hijas quedan viejas: `payment_schedule.base_payment_amount` conservaba
    el total anterior (66.980,38 contra 67.107,34). El payload fiscal se arma de esas
    filas. En `before_validate` el `validate()` nativo que corre a continuación recalcula
    todo, y el resultado es IDENTICO --campo por campo, incluido el GL-- al de retasar en
    borrador y guardar.

    Es idempotente: si el flujo de cobro ya retasó, la tasa coincide y no hace nada.
    """
    if getattr(doc, "_action", None) != "submit":
        # Guardados de borrador, update-after-submit y cancelaciones no retasan.
        return

    if doc.flags.get("skip_emission_rerate"):
        # Envío forzado por el Administrador: emitir con la tasa que porta el documento.
        # Sin esta salida el hook retasaba igual y el botón "Forzar Envío HKA" no servía
        # para nada, que es justo lo contrario de lo que existe para hacer.
        return

    rerate_juridical_before_submit(doc, during_submit=True)


def target_rate_before_submit(
    sales_invoice: object, *, during_submit: bool = False
) -> float | None:
    """Tasa con la que se emitiría la factura si se aprobara ahora, o None si no se retasa.

    Es SOLO LECTURA: no toca el documento ni la base. Existe para que la vista previa de
    HKA muestre exactamente la tasa que va a salir, sin duplicar la regla. Preguntar dos
    veces lo mismo por caminos distintos ya produjo divergencias en este módulo.

    A diferencia del retasado post-submit (`_get_target_rate`), acá NO hay condiciones de
    bloqueo: el documento todavía no tiene mayor que reparar.
    """
    if not during_submit and cint(sales_invoice.docstatus) != 0:
        # Ya emitida: retasarla exige recontabilizar, y de eso se encarga
        # rerate_to_emission_rate.
        return None

    if cint(sales_invoice.get("is_return")) or cint(sales_invoice.get("is_debit_note")):
        # Una nota debe expresarse en la MISMA tasa que el documento que corrige, o los
        # Bs dejan de corresponderse. Hoy Galanet usa doctypes propios (VE Sales Credit
        # Note / Debit Note, que pasan por validate_note_rate) y no hay ninguna nota
        # nativa de ERPNext en el sistema, pero el hook corre sobre toda Sales Invoice:
        # sin esta guarda, la primera que alguien cree saldría retasada a la tasa de hoy.
        return None

    company_currency: str = frappe.get_cached_value(
        "Company", sales_invoice.company, "default_currency"
    )
    if (sales_invoice.currency or company_currency) == company_currency:
        # Factura en moneda de curso legal: no hay carril en divisa que retasar.
        return None

    if not is_juridical_customer(sales_invoice.customer):
        # El natural conserva la tasa congelada del 1° del mes.
        return None

    if not branch_has_active_digital_series(
        sales_invoice.company, sales_invoice.get("branch")
    ):
        # Sin serie digital activa no se emite ante HKA: no hay fecha de emisión fiscal
        # que respetar y retasar sólo movería importes sin motivo.
        return None

    new_rate: float = flt(get_exchange_rate(today(), sales_invoice.currency))
    if not new_rate:
        # Sin tasa publicada para hoy se emite con la que porta el documento; bloquear
        # el cobro por esto sería peor que emitir con la tasa anterior.
        return None

    if abs(new_rate - flt(sales_invoice.conversion_rate)) < 0.0001:
        return None

    return new_rate


def rerate_juridical_before_submit(
    sales_invoice: object, *, during_submit: bool = False
) -> bool:
    """Lleva la factura a la tasa BCV de HOY antes de aprobarla. True si la retasó.

    Por qué acá y no al enviar a HKA
    ---------------------------------
    La factura de un cliente jurídico debe emitirse con la tasa del día de emisión
    (Ley IVA Art. 25 / Providencia SNAT/2011/0071). Hoy eso lo resuelve
    `rerate_to_emission_rate` (l10n_ve) DESPUÉS del submit, lo que obliga a borrar y
    regenerar el mayor del documento y trae condiciones de bloqueo que dejan facturas
    emitidas con tasa vieja.

    Retasando ANTES de que el documento quede emitido alcanza con asignar la tasa: el
    recálculo nativo deriva base_*, impuestos y retenciones. Sin repost, sin asientos
    correctivos y sin bloqueos.

    NO se guarda ni se emite acá: sólo se ajusta el documento en memoria. Persistir es
    responsabilidad del flujo que llama (que ya hace save + submit), para no romper la
    atomicidad del cobro.

    Dos formas de entrar:

    - `during_submit=False` (por defecto) — desde la cadena de cobro, con la factura en
      BORRADOR. Recalcula en memoria porque el capeo de anticipos que corre a
      continuación se guía por `base_grand_total`.
    - `during_submit=True` — desde el hook `before_validate` mientras se aprueba. El
      docstatus ya es 1 pero el documento todavía no se persistió, y el `validate()`
      nativo que sigue hace el recálculo.

    No aplica a naturales: conservan la tasa congelada del 1° del mes.
    """
    new_rate: float | None = target_rate_before_submit(
        sales_invoice, during_submit=during_submit
    )
    if new_rate is None:
        return False

    old_rate: float = flt(sales_invoice.conversion_rate)
    sales_invoice.conversion_rate = new_rate

    if not during_submit:
        # Recalcular EN MEMORIA: asignar la tasa no toca los base_*, y el capeo de
        # anticipos que corre a continuacion se guia por base_grand_total. Sin esto
        # capearia contra el total viejo (menor) y dejaria anticipos sin aplicar. El
        # save() posterior vuelve a calcular, pero para entonces el capeo ya estaria
        # hecho con el numero equivocado.
        #
        # En el camino del hook no se llama: validate() corre inmediatamente despues y
        # recalcula todo, incluidas las filas hijas.
        sales_invoice.calculate_taxes_and_totals()

    frappe.logger("l10n_ve").info(
        f"{RERATE_TAG} pre-submit {sales_invoice.name}: {old_rate} -> {new_rate}"
    )
    sales_invoice.add_comment(
        "Comment",
        f"Retasada a tasa de emisión antes de aprobar: {old_rate} → {new_rate} "
        f"(Bs por 1 {sales_invoice.currency}).",
    )
    return True


#: Endpoints por los que la interfaz aprueba documentos. El candado fiscal apunta a
#: estos y no a un flag en cada camino programatico: hay 6 lugares que emiten facturas
#: (regeneracion desde Customer x2, suscripcion, cobro, emision masiva y la migracion de
#: Odoo) y sembrar llaves en todos era fragil. Aca la regla queda en un solo lugar y
#: expresa literalmente lo que se quiere: no aprobar A MANO una factura que debe salir
#: por el boton de emision.
_UI_SUBMIT_ENDPOINTS: frozenset = frozenset({
    "frappe.desk.form.save.savedocs",
    "frappe.client.submit",
    "frappe.desk.doctype.bulk_update.bulk_update.submit_cancel_or_update_docs",
})


def _is_ui_submit() -> bool:
    """¿La aprobacion viene de la interfaz (no de un flujo programatico)?"""
    try:
        return (frappe.local.form_dict or {}).get("cmd") in _UI_SUBMIT_ENDPOINTS
    except Exception:
        # Sin request (cron, consola, jobs): no es la interfaz.
        return False


def block_manual_submit_of_fiscal_invoice(doc) -> None:
    """Impide aprobar A MANO una factura que debe emitirse ante HKA.

    Si la sucursal tiene serie de facturacion digital activa, la factura no debe
    aprobarse desde el formulario: el camino correcto es el boton de emision (o el
    cobro), que primero la retasa a la tasa del dia --obligatorio para clientes
    juridicos, Ley IVA Art. 25-- y recien despues la aprueba y la manda a HKA.

    Aprobarla a mano la deja emitida con la tasa vieja, y corregir eso despues obliga a
    recontabilizar el documento.

    Solo bloquea la INTERFAZ. Los flujos programaticos (cobro, suscripcion, emision
    masiva, regeneracion, migracion) siguen funcionando: son ellos los que hacen el
    retasado o los que ya emiten en el momento correcto.
    """
    if not _is_ui_submit():
        return

    if not branch_has_active_digital_series(doc.company, doc.get("branch")):
        return

    frappe.throw(
        f"Esta factura pertenece a la sucursal <b>{doc.get('branch')}</b>, que emite "
        "facturas fiscales ante HKA. No debe aprobarse manualmente: use el botón "
        "<b>Factura Digital</b>, que la retasa a la tasa del día, la aprueba y la envía. "
        "Aprobarla a mano la dejaría emitida con una tasa que no corresponde.",
        title="Aprobación manual no permitida",
    )


def stale_rate_reason(sales_invoice: object) -> str | None:
    """Motivo por el cual la tasa del documento NO corresponde a su fecha de emisión
    fiscal, o None si corresponde.

    Es SOLO LECTURA. Existe para frenar la certificación ante HKA de una factura cuya
    tasa quedó desincronizada de su `posting_date`: una vez emitida, el error no se
    deshace --hay que anularla con nota de crédito y reemitirla--.

    Caso que lo motivó: `ACC-SINV-2026-13754` (01-ago-2026). Creada el 2 de julio para
    el período 01-07 al 31-07, su `posting_date` terminó en 2026-08-01 mientras la tasa
    se quedó en 633,3644 --la del 1° de julio--. Salió ante el SENIAT con base imponible
    Bs 109.200,76 cuando a la tasa de su fecha de emisión eran Bs 128.726,43: unos
    Bs 19.526 de base y Bs 3.124 de IVA por debajo.

    Nadie movió esa fecha por el ciclo normal del documento --las cinco versiones del
    historial no la tocan--, así que la causa sigue sin identificarse. Este guard no la
    busca: impide que el resultado salga a la imprenta digital.

    La comparación es POR FECHA y no por valor: en Currency Exchange conviven tasas del
    mismo día que difieren ~1e-4, y compararlas por valor daría falsos positivos. Es la
    misma vara de `_get_target_rate`.
    """
    if cint(sales_invoice.get("is_return")) or cint(sales_invoice.get("is_debit_note")):
        # Una nota se expresa en la tasa del documento que corrige, no en la suya.
        return None

    company_currency: str = frappe.get_cached_value(
        "Company", sales_invoice.company, "default_currency"
    )
    if (sales_invoice.currency or company_currency) == company_currency:
        return None

    actual: float = flt(sales_invoice.conversion_rate)
    if not actual:
        return None

    posting_date = sales_invoice.get("posting_date")
    esperada: float = flt(get_exchange_rate(posting_date, sales_invoice.currency))
    if not esperada:
        # Sin tasa publicada para esa fecha no hay contra qué comparar. Bloquear la
        # emisión por no poder verificar sería peor que dejarla pasar.
        return None

    fecha_actual = resolve_exchange_rate_date(actual, sales_invoice.currency)
    fecha_esperada = resolve_exchange_rate_date(esperada, sales_invoice.currency)
    if fecha_actual and fecha_esperada and str(fecha_actual) == str(fecha_esperada):
        return None

    if abs(esperada - actual) < _RATE_TOLERANCE:
        return None

    return (
        f"La tasa del documento ({actual:,.4f}"
        + (f", del {fecha_actual}" if fecha_actual else "")
        + f") no corresponde a su fecha de emisión {posting_date} "
        f"(tasa {esperada:,.4f}). Emitirla así declararía una base imponible "
        f"distinta a la que corresponde. Corregir la tasa o la fecha antes de enviar."
    )
