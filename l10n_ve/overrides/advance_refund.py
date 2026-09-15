# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Reembolso de un anticipo que quedó sin aplicar.

Dos casos, uno espejo del otro:

- Cobro a un cliente (Receive) con saldo sin aplicar: la empresa le devuelve el dinero.
- Pago a un proveedor (Pay) con saldo sin aplicar: el proveedor le devuelve el dinero a la
  empresa.

Por qué no un «Pago» suelto: los anticipos van a cuentas separadas (2104001 y 1107001 en
Galanet) que no tienen tipo de cuenta, así que ERPNext no las lleva en el libro de pagos y
la Conciliación de Pagos no ofrece un reembolso registrado como Payment Entry para
emparejarlo con el cobro. El cobro sigue mostrando el anticipo como disponible y se puede
usar otra vez: GRUPO VITALIS pagó en el portal la factura de septiembre con 62.898,04 que
ya se le habían devuelto por transferencia (07-09-2026).

El reembolso se registra como un asiento entre la cuenta por cobrar (o por pagar) del
tercero y el banco, y se le aplica el anticipo con la Conciliación de Pagos de ERPNext, la
misma que aplica un anticipo a una factura. El anticipo baja y la cuenta por cobrar (o por
pagar) del tercero no cambia.
"""

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
    get_dimensions,
)
from erpnext.accounts.party import get_party_account
from frappe import _
from frappe.utils import cint, flt, fmt_money, get_link_to_form, getdate

# (tipo de tercero, tipo de pago) -> sentido del dinero en el reembolso
REFUND_DIRECTION: dict[tuple[str, str], str] = {
    ("Customer", "Receive"): "out",
    ("Supplier", "Pay"): "in",
}


def build_refund_rows(
    direction: str,
    amount: float,
    party_type: str,
    party: str,
    party_account: str,
    cash_account: str,
    dimensions: dict | None = None,
) -> list[dict]:
    """Filas del asiento del reembolso.

    Si el dinero sale (reembolso a un cliente), la cuenta por cobrar va al débito y el banco
    al crédito. Si entra (reembolso de un proveedor), al revés: la cuenta por pagar al
    crédito y el banco al débito. La fila del tercero no lleva referencia: el asiento tiene
    que quedar con saldo propio para que la conciliación lo ofrezca como documento.
    """
    if direction not in ("in", "out"):
        raise ValueError(f"sentido inválido: {direction!r}")

    party_side, cash_side = (
        ("debit_in_account_currency", "credit_in_account_currency")
        if direction == "out"
        else ("credit_in_account_currency", "debit_in_account_currency")
    )
    common: dict = dict(dimensions or {})
    return [
        {
            "account": party_account,
            "party_type": party_type,
            "party": party,
            party_side: amount,
            **common,
        },
        {"account": cash_account, cash_side: amount, **common},
    ]


@frappe.whitelist()
def create_advance_refund(
    payment_entry: str,
    amount: float,
    account: str,
    posting_date: str,
    reference_no: str | None = None,
    is_batch_payment: int = 0,
) -> dict:
    """Registra el reembolso del anticipo de ``payment_entry`` y se lo aplica.

    Crea y envía el asiento (banco o caja contra la cuenta del tercero) y concilia el pago
    contra ese asiento. Todo corre en la misma transacción: si algo falla, no queda nada.
    """
    # Dos clics sobre el mismo pago no pueden reembolsar dos veces el mismo saldo.
    frappe.db.sql(
        "SELECT name FROM `tabPayment Entry` WHERE name = %s FOR UPDATE", payment_entry
    )
    pe = frappe.get_doc("Payment Entry", payment_entry)
    frappe.has_permission("Payment Entry", ptype="write", doc=pe, throw=True)
    frappe.has_permission("Journal Entry", ptype="create", throw=True)
    frappe.has_permission("Journal Entry", ptype="submit", throw=True)

    direction: str = _validate_refundable(pe)
    precision: int = pe.precision("unallocated_amount") or 2
    amount = flt(amount, precision)
    unallocated: float = flt(pe.unallocated_amount, precision)
    _validate_amount(amount, unallocated, precision, pe.party_account_currency)

    posting_date = getdate(posting_date)
    if posting_date < getdate(pe.posting_date):
        frappe.throw(
            _("El reembolso no puede ser anterior al pago ({0}).").format(
                frappe.format(pe.posting_date, {"fieldtype": "Date"})
            )
        )

    account_type: str = _validate_cash_account(account, pe)
    reference_no = (reference_no or "").strip()
    if account_type == "Bank" and not reference_no:
        frappe.throw(_("Indique el número de referencia de la transferencia."))

    party_account, advance_account = _party_accounts(pe)

    journal_entry = _make_refund_entry(
        pe,
        direction,
        amount,
        account,
        account_type,
        party_account,
        posting_date,
        reference_no,
        is_batch_payment,
    )
    _apply_advance(pe, journal_entry, party_account, advance_account, amount, precision)

    pe.reload()
    expected: float = flt(unallocated - amount, precision)
    if flt(pe.unallocated_amount, precision) != expected:
        frappe.throw(
            _(
                "El anticipo no quedó aplicado al reembolso: sin aplicar {0}, se esperaba {1}. "
                "No se registró nada."
            ).format(pe.unallocated_amount, expected)
        )

    _add_comments(pe, journal_entry, direction, amount)
    return {
        "journal_entry": journal_entry.name,
        "amount": amount,
        "unallocated_amount": pe.unallocated_amount,
    }


def _validate_refundable(pe) -> str:
    """Sentido del reembolso, o error si el pago no admite uno."""
    if pe.docstatus != 1:
        frappe.throw(_("El pago tiene que estar validado para registrar un reembolso."))

    direction: str | None = REFUND_DIRECTION.get((pe.party_type, pe.payment_type))
    if not direction:
        frappe.throw(
            _(
                "Solo se reembolsa el anticipo de un cobro a un cliente o de un pago a un proveedor."
            )
        )

    company_currency: str = frappe.get_cached_value(
        "Company", pe.company, "default_currency"
    )
    if pe.party_account_currency != company_currency:
        frappe.throw(
            _(
                "El anticipo está en {0}. Por ahora solo se reembolsan anticipos en la moneda "
                "de la compañía ({1})."
            ).format(pe.party_account_currency, company_currency)
        )
    return direction


def _validate_amount(
    amount: float, unallocated: float, precision: int, currency: str
) -> None:
    if unallocated <= 0:
        frappe.throw(_("El pago no tiene saldo sin aplicar para reembolsar."))
    if amount <= 0:
        frappe.throw(_("El monto a reembolsar tiene que ser mayor que cero."))
    if amount > unallocated:
        frappe.throw(
            _("El monto ({0}) supera lo que queda sin aplicar del pago ({1}).").format(
                fmt_money(amount, precision, currency),
                fmt_money(unallocated, precision, currency),
            )
        )


def _validate_cash_account(account: str, pe) -> str:
    """Tipo de la cuenta (Bank o Cash), o error si no sirve para el reembolso."""
    data = frappe.db.get_value(
        "Account",
        account,
        ["company", "is_group", "disabled", "account_type", "account_currency"],
        as_dict=True,
    )
    if not data:
        frappe.throw(_("La cuenta {0} no existe.").format(account))
    if data.company != pe.company:
        frappe.throw(
            _("La cuenta {0} no pertenece a la compañía {1}.").format(
                account, pe.company
            )
        )
    if data.is_group or data.disabled:
        frappe.throw(_("La cuenta {0} no admite movimientos.").format(account))
    if data.account_type not in ("Bank", "Cash"):
        frappe.throw(
            _("La cuenta {0} tiene que ser de banco o de caja.").format(account)
        )
    if data.account_currency != pe.party_account_currency:
        frappe.throw(
            _(
                "La cuenta {0} está en {1} y el anticipo en {2}. El reembolso se registra en la "
                "misma moneda del anticipo."
            ).format(account, data.account_currency, pe.party_account_currency)
        )
    return data.account_type


def _party_accounts(pe) -> tuple[str, str | None]:
    """Cuenta del tercero donde va el reembolso y cuenta de anticipo, si la hay.

    Con anticipos en cuenta separada, el pago está en la cuenta de anticipo y el reembolso va
    a la cuenta por cobrar (o por pagar) del tercero, igual que una factura: la conciliación
    mueve el anticipo de una a la otra. Sin cuenta separada (hay pagos a proveedores así), el
    pago y el reembolso comparten la cuenta del tercero.
    """
    if cint(pe.book_advance_payments_in_separate_party_account):
        party_account: str = get_party_account(pe.party_type, pe.party, pe.company)
        advance_account: str | None = pe.party_account
    else:
        party_account = pe.party_account
        advance_account = None

    currency: str = frappe.get_cached_value(
        "Account", party_account, "account_currency"
    )
    if currency != pe.party_account_currency:
        frappe.throw(
            _("La cuenta {0} del tercero está en {1} y el anticipo en {2}.").format(
                party_account, currency, pe.party_account_currency
            )
        )
    return party_account, advance_account


def _make_refund_entry(
    pe,
    direction: str,
    amount: float,
    account: str,
    account_type: str,
    party_account: str,
    posting_date,
    reference_no: str,
    is_batch_payment: int,
):
    """Crea y envía el asiento del reembolso, con la sucursal y el centro de costo del pago."""
    dimensions: dict = {"cost_center": pe.cost_center}
    if pe.get("branch") and frappe.db.has_column("Journal Entry Account", "branch"):
        dimensions["branch"] = pe.branch
    for dimension in get_dimensions()[0]:
        if pe.get(dimension.fieldname):
            dimensions[dimension.fieldname] = pe.get(dimension.fieldname)

    journal_entry = frappe.new_doc("Journal Entry")
    journal_entry.voucher_type = (
        "Bank Entry" if account_type == "Bank" else "Cash Entry"
    )
    journal_entry.company = pe.company
    journal_entry.posting_date = posting_date
    if reference_no:
        # mint concilia el asiento con el retiro del banco por esta referencia al enviarlo.
        journal_entry.cheque_no = reference_no
        journal_entry.cheque_date = posting_date
    if (
        cint(is_batch_payment)
        and direction == "out"
        and frappe.db.has_column("Journal Entry", "is_batch_payment")
    ):
        journal_entry.is_batch_payment = 1

    for row in build_refund_rows(
        direction, amount, pe.party_type, pe.party, party_account, account, dimensions
    ):
        journal_entry.append("accounts", row)

    remark: str = (
        _("Reembolso al cliente {0} del anticipo del cobro {1}")
        if direction == "out"
        else _("Reembolso del proveedor {0} del anticipo del pago {1}")
    )
    journal_entry.user_remark = remark.format(pe.party, pe.name)
    journal_entry.insert(ignore_permissions=True)
    journal_entry.submit()
    return journal_entry


def _apply_advance(
    pe,
    journal_entry,
    party_account: str,
    advance_account: str | None,
    amount: float,
    precision: int,
) -> None:
    """Aplica el anticipo del pago al asiento con la Conciliación de Pagos de ERPNext."""
    reconciliation = frappe.new_doc("Payment Reconciliation")
    reconciliation.update(
        {
            "company": pe.company,
            "party_type": pe.party_type,
            "party": pe.party,
            "receivable_payable_account": party_account,
            "default_advance_account": advance_account,
            "invoice_name": journal_entry.name,
            "payment_name": pe.name,
        }
    )
    reconciliation.get_unreconciled_entries()

    invoice = next(
        (
            r
            for r in reconciliation.invoices
            if r.invoice_type == "Journal Entry"
            and r.invoice_number == journal_entry.name
        ),
        None,
    )
    payment = next(
        (
            r
            for r in reconciliation.payments
            if r.reference_type == "Payment Entry" and r.reference_name == pe.name
        ),
        None,
    )
    if not invoice or not payment:
        frappe.throw(
            _(
                "La conciliación no ofreció el pago {0} y el asiento {1} para aplicarlos. "
                "No se registró nada."
            ).format(pe.name, journal_entry.name)
        )

    reconciliation.allocate_entries(
        frappe._dict(invoices=[invoice.as_dict()], payments=[payment.as_dict()])
    )
    allocated: float = flt(
        sum(flt(a.allocated_amount) for a in reconciliation.allocation), precision
    )
    if allocated != amount:
        frappe.throw(
            _(
                "Se iba a aplicar {0} y el reembolso es de {1}. No se registró nada."
            ).format(allocated, amount)
        )

    # Sin el «Conciliado con éxito» de la herramienta: el aviso lo da el botón.
    muted = frappe.flags.mute_messages
    frappe.flags.mute_messages = True
    try:
        reconciliation.reconcile()
    finally:
        frappe.flags.mute_messages = muted


def _add_comments(pe, journal_entry, direction: str, amount: float) -> None:
    """Deja el enlace en la línea de tiempo de los dos documentos."""
    amount_text: str = fmt_money(amount, currency=pe.party_account_currency)
    journal_link: str = get_link_to_form("Journal Entry", journal_entry.name)
    payment_link: str = get_link_to_form("Payment Entry", pe.name)
    if direction == "out":
        text = _("Se le reembolsaron {0} al cliente con el asiento {1}.").format(
            amount_text, journal_link
        )
    else:
        text = _(
            "El proveedor reembolsó {0}; quedó registrado en el asiento {1}."
        ).format(amount_text, journal_link)
    pe.add_comment("Comment", text=text)
    journal_entry.add_comment(
        "Comment", text=_("Reembolso del anticipo del pago {0}.").format(payment_link)
    )
