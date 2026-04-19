"""
Hook on_update para GL Entry.

ERPNext solo actualiza outstanding_amount para Sales Invoice,
Purchase Invoice y Fees (ver gl_entry.py:111-124).

Este hook extiende esa lógica para los DocTypes fiscales
venezolanos (VE Sales Debit Note, VE Sales Credit Note).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

VE_VOUCHER_TYPES: tuple = ("VE Sales Debit Note", "VE Sales Credit Note")


def update_ve_outstanding_amount(doc, method: str | None = None) -> None:
    """
    Recalcula outstanding_amount de NC/ND cuando un GL Entry
    se registra contra ellas (ej. al aprobar un Payment Entry).

    Replica la lógica de ``update_outstanding_amt`` de ERPNext
    (erpnext/accounts/doctype/gl_entry/gl_entry.py:328)
    pero adaptada a los DocTypes venezolanos.
    """
    if doc.against_voucher_type not in VE_VOUCHER_TYPES:
        return

    if not doc.against_voucher:
        return

    if doc.flags.update_outstanding != "Yes":
        return

    if doc.is_cancelled:
        return

    against_voucher_type: str = doc.against_voucher_type
    against_voucher: str = doc.against_voucher

    bal = flt(
        frappe.db.sql(
            """
            SELECT SUM(debit_in_account_currency) - SUM(credit_in_account_currency)
            FROM `tabGL Entry`
            WHERE against_voucher_type = %s
              AND against_voucher = %s
              AND account = %s
              AND is_cancelled = 0
            """,
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
