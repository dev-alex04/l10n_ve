"""
Hook on_update para GL Entry.

ERPNext solo actualiza outstanding_amount para Sales Invoice,
Purchase Invoice y Fees (ver gl_entry.py:111-124).

Este hook extiende esa lógica para las Notas de Débito venezolanas.
Las Notas de Crédito NO se incluyen porque no manejan outstanding
propio — reducen el outstanding de la factura original.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

VE_VOUCHER_TYPES: tuple = (
    "VE Sales Debit Note",
    "VE Purchase Debit Note",
)

# ND de compras usa AP (outstanding = credit - debit)
# ND de ventas usa AR (outstanding = debit - credit)
_AP_VOUCHER_TYPES: frozenset = frozenset({"VE Purchase Debit Note"})


def update_ve_outstanding_amount(doc, method: str | None = None) -> None:
    """
    Recalcula outstanding_amount de la ND cuando un GL Entry
    se registra contra ellas (ej. al aprobar un Payment Entry).

    Replica la lógica de ``update_outstanding_amt`` de ERPNext
    (erpnext/accounts/doctype/gl_entry/gl_entry.py:328)
    pero adaptada a los DocTypes venezolanos.

    Para AP (compras): outstanding = SUM(credit) - SUM(debit)
    Para AR (ventas):  outstanding = SUM(debit) - SUM(credit)
    """
    if doc.against_voucher_type not in VE_VOUCHER_TYPES:
        return

    if not doc.against_voucher:
        return

    if doc.flags.update_outstanding != "Yes":
        return

    # OJO: NO se corta cuando el asiento viene cancelado. Al anular un pago, ERPNext
    # marca sus GL Entry con is_cancelled=1 y dispara este mismo on_update; si se
    # saliera aca, el outstanding se quedaria con el valor de cuando estaba pagada y
    # la nota figuraria saldada para siempre. Recalcular es correcto igual, porque la
    # consulta de abajo ya filtra `is_cancelled = 0`: al pasar por aca despues de la
    # anulacion, la suma excluye el pago anulado y el saldo vuelve solo.

    against_voucher_type: str = doc.against_voucher_type
    against_voucher: str = doc.against_voucher

    if against_voucher_type in _AP_VOUCHER_TYPES:
        # AP: outstanding = credit - debit (crédito aumenta deuda)
        sql: str = """
            SELECT SUM(credit_in_account_currency) - SUM(debit_in_account_currency)
            FROM `tabGL Entry`
            WHERE against_voucher_type = %s
              AND against_voucher = %s
              AND account = %s
              AND is_cancelled = 0
        """
    else:
        # AR: outstanding = debit - credit (débito aumenta saldo)
        sql = """
            SELECT SUM(debit_in_account_currency) - SUM(credit_in_account_currency)
            FROM `tabGL Entry`
            WHERE against_voucher_type = %s
              AND against_voucher = %s
              AND account = %s
              AND is_cancelled = 0
        """

    bal = flt(
        frappe.db.sql(
            sql,
            (against_voucher_type, against_voucher, doc.account),
        )[0][0]
        or 0.0
    )

    frappe.db.set_value(
        against_voucher_type,
        against_voucher,
        "outstanding_amount",
        bal,
        update_modified=False,
    )

    ref_doc = frappe.get_doc(against_voucher_type, against_voucher)
    ref_doc.set_status(update=True)
