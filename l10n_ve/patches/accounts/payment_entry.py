from frappe.utils import flt, cint

from erpnext.accounts.doctype.payment_entry.payment_entry import (
    PaymentEntry,
    validate_inclusive_tax,
)
from erpnext.controllers.accounts_controller import validate_taxes_and_charges

# Tipos de cargo venezolanos cuyo monto ya viene calculado desde el cliente.
# NO deben resetearse a cero durante initialize_taxes.
_TIPOS_CARGO_VENEZOLANOS = frozenset({"IGTF", "ISLR", "VAT Withholding"})


def _initialize_taxes_parcheado(self) -> None:
    """
    Extensión de initialize_taxes que preserva el tax_amount de tipos de
    cargo venezolanos (IGTF, ISLR, VAT Withholding) cuyo valor es calculado
    por el cliente y no debe ser reseteado a cero.

    ERPNext 15.101.0 resetea tax_amount para cualquier charge_type != 'Actual',
    lo que rompe el flujo de IGTF ya que get_current_tax_amount no lo maneja.
    """
    for tax in self.get("taxes"):
        validate_taxes_and_charges(tax)
        validate_inclusive_tax(tax, self)

        tax_fields = [
            "total",
            "tax_fraction_for_current_item",
            "grand_total_fraction_for_current_item",
        ]

        if tax.charge_type != "Actual" and tax.charge_type not in _TIPOS_CARGO_VENEZOLANOS:
            tax_fields.append("tax_amount")

        for fieldname in tax_fields:
            tax.set(fieldname, 0.0)

    self.paid_amount_after_tax = self.base_paid_amount


def _get_current_tax_amount_parcheado(self, tax) -> float:
    """
    Extensión de get_current_tax_amount que agrega un bloque else para manejar
    tipos de cargo que ERPNext no conoce (IGTF, ISLR, VAT Withholding).

    En ERPNext 15.101.0, la función solo maneja: Actual, On Paid Amount,
    On Previous Row Amount, On Previous Row Total. Para cualquier otro tipo,
    current_tax_amount queda sin asignar y se lanza UnboundLocalError.
    """
    import frappe

    tax_rate = tax.rate

    if tax.charge_type in ["On Previous Row Amount", "On Previous Row Total"]:
        if tax.idx == 1:
            frappe.throw(
                frappe._(
                    "Cannot select charge type as 'On Previous Row Amount'"
                    " or 'On Previous Row Total' for first row"
                )
            )
        if not tax.row_id:
            tax.row_id = tax.idx - 1

    if tax.charge_type == "Actual":
        current_tax_amount = flt(tax.tax_amount, self.precision("tax_amount", tax))
    elif tax.charge_type == "On Paid Amount":
        current_tax_amount = (tax_rate / 100.0) * self.paid_amount_after_tax
    elif tax.charge_type == "On Previous Row Amount":
        current_tax_amount = (
            (tax_rate / 100.0) * self.get("taxes")[cint(tax.row_id) - 1].tax_amount
        )
    elif tax.charge_type == "On Previous Row Total":
        current_tax_amount = (
            (tax_rate / 100.0) * self.get("taxes")[cint(tax.row_id) - 1].total
        )
    else:
        # Tipos venezolanos: IGTF, ISLR, VAT Withholding.
        # El monto ya fue calculado por el cliente y viene en tax.tax_amount.
        current_tax_amount = flt(tax.tax_amount, self.precision("tax_amount", tax))

    return current_tax_amount


PaymentEntry.initialize_taxes = _initialize_taxes_parcheado
PaymentEntry.get_current_tax_amount = _get_current_tax_amount_parcheado
