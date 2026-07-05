import frappe
from frappe.utils import flt

def on_submit_payment_ledger_entry(doc, method=None):
    if doc.voucher_type != "Payment Entry" or doc.against_voucher_type != "Sales Invoice":
        return

    invoice_name = doc.against_voucher_no

    # Recalcular campos de IGTF en la Factura de Ventas
    recalculate_invoice_igtf(invoice_name)


def on_cancel_payment_ledger_entry(doc, method=None):
    if doc.voucher_type != "Payment Entry" or doc.against_voucher_type != "Sales Invoice":
        return

    invoice_name = doc.against_voucher_no

    # Recalcular campos de IGTF en la Factura de Ventas
    recalculate_invoice_igtf(invoice_name)


def on_trash_payment_ledger_entry(doc, method=None):
    on_cancel_payment_ledger_entry(doc, method)


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
            matched_amount_vef = abs(flt(entry.amount_in_account_currency))
            
            # Si la moneda de la cuenta de cobro es USD, el monto ya está en USD.
            # De lo contrario (ej. VES), se divide por la tasa del cobro.
            account_currency = entry.get("account_currency") or "VEF"
            if account_currency == "USD":
                matched_amount_usd = matched_amount_vef
            else:
                matched_amount_usd = matched_amount_vef / (flt(pe.exchange_rate) or 1.0)

            total_base_igtf += matched_amount_usd
            total_igtf += (matched_amount_usd * igtf_rate) / 100.0

    # Actualizar la factura
    frappe.db.set_value("Sales Invoice", invoice_name, {
        "base_amount_igtf": total_base_igtf,
        "total_igtf": total_igtf,
        "igtf_rate": igtf_rate if total_igtf > 0 else 0
    }, update_modified=False)
