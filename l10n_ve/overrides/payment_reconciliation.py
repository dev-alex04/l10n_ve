"""Conciliación de cobros contra su depósito bancario.

Regla central (solo para Payment Entry de tipo cobro / Receive):
  - Efectivo / Gangway: se aprueban sin exigir depósito (por su naturaleza).
  - Cualquier otro modo (banco): NO se puede aprobar hasta conciliarse con el
    depósito bancario cuyo número de referencia coincide con la referencia del
    cobro. Al conciliar, el monto AUTORITATIVO es el del depósito y se registra
    como monto de pago (paid_currency_amount, en paid_on_currency): bolívares
    con bolívares.

Piezas:
  - find_matching_deposit: localiza el Bank Transaction por referencia exacta.
  - reconcile_and_approve: rutina activa (botón / disparador desde el depósito)
    que fija el monto del cobro al del depósito y lo aprueba.
  - before_submit_receive_payment: compuerta pasiva; impide aprobar un cobro
    bancario que no esté conciliado.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

RECON_PENDING = "Conciliación Pendiente"
RECON_DONE = "Conciliado"

# Modos que no exigen depósito bancario para aprobarse.
CASH_LIKE_TYPES = ("Cash", "Gangway")


def is_receive_reconciliation_enforced() -> bool:
    """Flag que activa la EXIGENCIA de conciliación para aprobar cobros bancarios.

    Se controla por site_config (`enforce_receive_reconciliation`). Por defecto
    está DESACTIVADO: la compuerta no bloquea aprobaciones ni el disparador
    auto-aprueba borradores, hasta que el dashboard cree los cobros en borrador
    (pieza acoplada). Así se puede reiniciar bench sin romper el flujo actual.
    El botón "Intentar conciliar" funciona siempre (acción manual).
    """
    return bool(frappe.conf.get("enforce_receive_reconciliation"))


def _is_bank_receive(doc) -> bool:
    """True si es un cobro que exige depósito bancario (no efectivo/gangway)."""
    if doc.payment_type != "Receive":
        return False
    mop_type = (
        frappe.get_cached_value("Mode of Payment", doc.mode_of_payment, "type")
        if doc.mode_of_payment
        else None
    )
    return mop_type not in CASH_LIKE_TYPES


def find_matching_deposit(doc) -> frappe._dict | None:
    """Depósito bancario (Bank Transaction) cuyo número de referencia y MONEDA
    coinciden con los del cobro y que aún tiene saldo disponible. Devuelve
    {name, deposit, unallocated_amount, currency, bank_account} o None.

    Match por referencia + moneda (no por cuenta bancaria): los depósitos P2C /
    Pagomóvil caen en una cuenta concentradora distinta a la del modo de pago,
    pero la MONEDA sí debe coincidir — un depósito en VEF no concilia un cobro en
    USD. Se exige saldo sin conciliar (unallocated_amount > 0) para no reusar un
    depósito ya consumido. Match exacto a propósito.
    """
    ref = (doc.reference_no or "").strip()
    if not ref:
        return None

    filters = {
        "reference_number": ref,
        "docstatus": 1,
        "deposit": [">", 0],
        "unallocated_amount": [">", 0.001],
    }
    paid_currency = (doc.paid_on_currency or "").strip()
    if paid_currency:
        filters["currency"] = paid_currency

    return frappe.db.get_value(
        "Bank Transaction",
        filters,
        ["name", "deposit", "unallocated_amount", "currency", "bank_account"],
        as_dict=True,
    )


def _apply_deposit_amount(doc, deposit: frappe._dict) -> None:
    """Fija el monto del cobro al del depósito (monto autoritativo del banco).

    El monto se registra en paid_currency_amount (en paid_on_currency), que es el
    monto de pago real, y se replica en paid_amount/received_amount para que la
    asignación y el GL queden consistentes.

    Caso de una sola factura (o sin referencias). El reparto cuando el depósito
    cubre varias facturas se aborda en la bifurcación de asignación (3.2); por eso
    aquí se bloquea explícitamente el multi-referencia en lugar de adivinar.
    """
    if len(doc.references or []) > 1:
        frappe.throw(
            _(
                "Este cobro tiene varias facturas asociadas; el reparto del depósito "
                "entre ellas aún no está implementado en este flujo."
            )
        )

    company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
    deposit_currency = deposit.currency or company_currency

    # Saldo disponible del depósito, en SU moneda (la búsqueda ya garantizó que
    # coincide con la del cobro): para uno fresco == total; para uno parcial, el
    # resto sin asignar.
    deposit_amount = flt(deposit.unallocated_amount, 2)
    doc.paid_currency_amount = deposit_amount

    if deposit_currency == company_currency:
        # Cobro/depósito en moneda local: bolívares con bolívares.
        doc.paid_on_currency = company_currency
        doc.exchange_rate = 1.0
        doc.paid_amount = deposit_amount
        doc.received_amount = deposit_amount
    else:
        # Cobro/depósito en divisa (p. ej. USD): el monto base es el contravalor a
        # la tasa del cobro; el IGTF se recalcula sobre el monto en divisa.
        rate = flt(doc.exchange_rate) or 1.0
        base = flt(deposit_amount * rate, 2)
        doc.paid_amount = base
        doc.received_amount = base

    # Forzar recálculo del IGTF sobre el nuevo monto: calculate_igtf_taxes solo lo
    # recompone si igtf_amount viene vacío.
    doc.igtf_amount = 0
    doc.total_with_igtf = 0

    # Re-apuntar el cobro al banco donde realmente cayó el depósito: ERPNext exige
    # que el cobro afecte la misma cuenta bancaria del depósito para conciliar, y
    # contablemente la plata está en esa cuenta (depósitos P2C caen en el
    # concentrador, no en el banco del modo de pago del cobro).
    if deposit.bank_account:
        bank_gl = frappe.get_cached_value("Bank Account", deposit.bank_account, "account")
        if bank_gl and doc.paid_to != bank_gl:
            doc.paid_to = bank_gl
            doc.paid_to_account_currency = frappe.get_cached_value(
                "Account", bank_gl, "account_currency"
            )
            doc.bank_account = deposit.bank_account

    if doc.references:
        ref = doc.references[0]
        outstanding = flt(ref.outstanding_amount, 2)
        ref.allocated_amount = (
            min(deposit_amount, outstanding) if outstanding > 0 else deposit_amount
        )


@frappe.whitelist()
def reconcile_and_approve(payment_entry: str) -> dict:
    """Intenta conciliar el cobro con su depósito y, si lo encuentra, fija el
    monto del cobro al del depósito y lo aprueba. Llamada por el botón del
    formulario y por el disparador desde el lado del depósito bancario.
    """
    doc = frappe.get_doc("Payment Entry", payment_entry)

    if doc.docstatus != 0:
        frappe.throw(_("Solo se puede conciliar un cobro en borrador."))
    if not _is_bank_receive(doc):
        frappe.throw(_("Solo aplica a cobros bancarios (no efectivo/gangway)."))

    deposit = find_matching_deposit(doc)
    if not deposit:
        if doc.get("custom_reconciliation_status") != RECON_PENDING:
            doc.db_set("custom_reconciliation_status", RECON_PENDING)
        return {
            "reconciled": False,
            "message": _("Aún no se encontró un depósito con la referencia {0}.").format(
                doc.reference_no or ""
            ),
        }

    _apply_deposit_amount(doc, deposit)
    doc.custom_reconciliation_status = RECON_DONE
    doc.save(ignore_permissions=True)
    doc.submit()

    # Enlazar el depósito al cobro: la conciliación bancaria (y la activación del
    # servicio, vía el hook on_change de Bank Transaction) proceden desde aquí.
    _link_deposit_to_payment(deposit.name, doc.name)

    return {
        "reconciled": True,
        "amount": flt(deposit.unallocated_amount, 2),
        "bank_transaction": deposit.name,
        "message": _("Cobro conciliado y aprobado por {0} (depósito {1}).").format(
            flt(deposit.unallocated_amount, 2), deposit.name
        ),
    }


def _link_deposit_to_payment(bank_transaction_name: str, payment_entry_name: str) -> None:
    """Enlaza el Bank Transaction (depósito) al Payment Entry ya aprobado.

    Guardar el Bank Transaction con el pago enlazado dispara su hook on_change,
    que concilia la línea del ISP Payment Entry y, si corresponde, paga la factura
    y activa el servicio. Idempotente y tolerante a depósitos sin saldo libre.
    """
    bt = frappe.get_doc("Bank Transaction", bank_transaction_name)
    already = any(
        row.payment_entry == payment_entry_name and row.payment_document == "Payment Entry"
        for row in bt.payment_entries
    )
    if already or flt(bt.unallocated_amount) <= 0:
        return
    bt.add_payment_entries(
        [{"payment_doctype": "Payment Entry", "payment_name": payment_entry_name}]
    )
    bt.save(ignore_permissions=True)


def before_submit_receive_payment(doc, method=None) -> None:
    """Al aprobar un cobro bancario: buscar su depósito por referencia y conciliar.

    - Si NO hay un depósito con esa referencia en la cuenta del cobro → error
      (no se aprueba).
    - Si lo hay → se usa el MONTO DEL DEPÓSITO (no el tecleado) y se recalculan
      los montos base; el depósito se enlaza en on_submit.

    Solo actúa con la exigencia activada (flag); ver
    is_receive_reconciliation_enforced. El botón "Intentar conciliar"
    (reconcile_and_approve) funciona siempre, con flag o sin él.
    """
    if not _is_bank_receive(doc):
        return
    if not is_receive_reconciliation_enforced():
        return

    deposit = find_matching_deposit(doc)
    if not deposit:
        frappe.throw(
            _(
                "Este cobro no puede aprobarse: no se encontró un depósito bancario "
                "con la referencia {0} en la cuenta del cobro. Verifique la referencia "
                "y la cuenta bancaria, o espere a que el depósito ingrese."
            ).format(frappe.bold(doc.reference_no or ""))
        )

    # El monto autoritativo es el del banco: fijarlo y recalcular TODO
    # (bases, montos después de impuestos, monto en letras y descripción), para
    # que ningún campo quede apuntando al monto tecleado original.
    _apply_deposit_amount(doc, deposit)
    doc.calculate_igtf_taxes()  # recalcula IGTF si el cobro es en divisa
    doc.set_amounts()
    doc.set_amounts_after_tax()
    doc.set_total_in_words()
    doc.set_remarks()
    doc.custom_reconciliation_status = RECON_DONE
    doc.flags.l10n_ve_matched_deposit = deposit.name


def on_submit_receive_payment(doc, method=None) -> None:
    """Tras aprobar el cobro, enlazar su depósito bancario: el guardado del Bank
    Transaction dispara la conciliación y la activación por sus hooks."""
    if not _is_bank_receive(doc):
        return
    if not is_receive_reconciliation_enforced():
        return

    bt_name = doc.flags.get("l10n_ve_matched_deposit")
    if not bt_name:
        dep = find_matching_deposit(doc)
        bt_name = dep.name if dep else None
    if bt_name:
        _link_deposit_to_payment(bt_name, doc.name)


def reconcile_drafts_for_deposit(doc, method=None) -> None:
    """Disparador desde el depósito: al confirmarse un Bank Transaction, intenta
    aprobar los cobros en borrador que esperaban esa referencia.

    Se ejecuta en background (enqueue_after_commit) para no bloquear el guardado
    del depósito. Solo actúa con la exigencia activada (flag).
    """
    if not is_receive_reconciliation_enforced():
        return

    ref = (doc.reference_number or "").strip()
    if not ref or flt(doc.deposit) <= 0:
        return

    frappe.enqueue(
        "l10n_ve.overrides.payment_reconciliation.reconcile_drafts_job",
        queue="short",
        reference=ref,
        enqueue_after_commit=True,
    )


def reconcile_drafts_job(reference: str) -> None:
    """Aprueba los cobros en borrador cuya referencia coincide con el depósito."""
    drafts = frappe.get_all(
        "Payment Entry",
        filters={"docstatus": 0, "payment_type": "Receive", "reference_no": reference},
        pluck="name",
    )
    for name in drafts:
        try:
            reconcile_and_approve(name)
        except frappe.ValidationError:
            frappe.clear_last_message()
            continue
