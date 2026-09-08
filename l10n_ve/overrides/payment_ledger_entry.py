import frappe
from frappe.utils import flt

_VE_DEBIT_NOTE_TYPES: frozenset[str] = frozenset({
    "VE Purchase Debit Note",
    "VE Sales Debit Note",
})


def on_submit_payment_ledger_entry(doc, method: str | None = None) -> None:
    # Recalcular campos de IGTF en la Factura de Ventas
    if doc.voucher_type == "Payment Entry" and doc.against_voucher_type == "Sales Invoice":
        recalculate_invoice_igtf(doc.against_voucher_no)

    # Recalcular saldo de Notas de Débito venezolanas
    if doc.against_voucher_type in _VE_DEBIT_NOTE_TYPES and doc.against_voucher_no:
        update_ve_debit_note_outstanding(doc.against_voucher_type, doc.against_voucher_no)


def on_cancel_payment_ledger_entry(doc, method: str | None = None) -> None:
    # Recalcular campos de IGTF en la Factura de Ventas
    if doc.voucher_type == "Payment Entry" and doc.against_voucher_type == "Sales Invoice":
        recalculate_invoice_igtf(doc.against_voucher_no)

    # Recalcular saldo de Notas de Débito venezolanas
    if doc.against_voucher_type in _VE_DEBIT_NOTE_TYPES and doc.against_voucher_no:
        update_ve_debit_note_outstanding(doc.against_voucher_type, doc.against_voucher_no)


def on_trash_payment_ledger_entry(doc, method: str | None = None) -> None:
    on_cancel_payment_ledger_entry(doc, method)


def update_ve_debit_note_outstanding(voucher_type: str, voucher_no: str) -> None:
    """
    Recalcula y actualiza el campo outstanding_amount y el status de una
    Nota de Débito venezolana según los movimientos en Payment Ledger Entry.
    """
    if not frappe.db.exists(voucher_type, voucher_no):
        return

    from erpnext.accounts.utils import QueryPaymentLedger

    vouchers: list[frappe._dict] = [
        frappe._dict({"voucher_type": voucher_type, "voucher_no": voucher_no})
    ]
    results: list[dict] = QueryPaymentLedger().get_voucher_outstandings(vouchers)

    precision: int = frappe.get_precision(voucher_type, "outstanding_amount") or 2
    if results:
        outstanding: float = flt(results[0].get("outstanding_in_account_currency"), precision)
    else:
        grand_total: float = flt(
            frappe.get_cached_value(voucher_type, voucher_no, "rounded_total")
            or frappe.get_cached_value(voucher_type, voucher_no, "grand_total")
            or 0.0
        )
        outstanding = flt(grand_total, precision)

    frappe.db.set_value(voucher_type, voucher_no, "outstanding_amount", outstanding)
    ref_doc = frappe.get_doc(voucher_type, voucher_no)
    ref_doc.set_status(update=True)


def recalculate_invoice_igtf(invoice_name):
    # Obtener todas las relaciones activas del libro mayor de pagos
    entries = frappe.get_all(
        "Payment Ledger Entry",
        filters={
            "against_voucher_type": "Sales Invoice",
            "against_voucher_no": invoice_name,
            "voucher_type": "Payment Entry",
            "docstatus": 1,
            "delinked": 0
        },
        fields=["voucher_no", "amount_in_account_currency", "account_currency"]
    )

    total_base_igtf = 0.0
    total_igtf = 0.0
    igtf_rate = frappe.db.get_single_value("Venezuela Account Settings", "igtf_rate") or 3.0

    for entry in entries:
        try:
            pe = frappe.get_cached_doc("Payment Entry", entry.voucher_no)
        except frappe.DoesNotExistError:
            continue

        # Verificar si el pago tiene el impuesto IGTF en su tabla de impuestos
        igtf_tax = next((t for t in pe.taxes or [] if t.charge_type == "IGTF"), None)
        if igtf_tax and flt(igtf_tax.tax_amount) > 0:
            matched_amount_in_acc_currency = abs(flt(entry.amount_in_account_currency))
            
            # El IGTF en la factura (base_amount_igtf y total_igtf) debe estar expresado en VEF (moneda base).
            # Si el Ledger Entry está en USD, lo convertimos a VEF usando la tasa del cobro.
            # Si está en VEF, lo tomamos directo.
            account_currency = entry.get("account_currency") or "VEF"
            if account_currency == "USD":
                matched_amount_vef = matched_amount_in_acc_currency * (flt(pe.exchange_rate) or 1.0)
            else:
                matched_amount_vef = matched_amount_in_acc_currency

            total_base_igtf += matched_amount_vef
            total_igtf += (matched_amount_vef * igtf_rate) / 100.0

    # Actualizar la factura
    frappe.db.set_value("Sales Invoice", invoice_name, {
        "base_amount_igtf": total_base_igtf,
        "total_igtf": total_igtf,
        "igtf_rate": igtf_rate if total_igtf > 0 else 0
    }, update_modified=False)
