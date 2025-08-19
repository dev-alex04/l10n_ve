import frappe
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

class CustomPurchaseInvoice(PurchaseInvoice):

    def before_submit(self) -> None:
        super().before_submit()

        self.validate_duplicate_invoice_numbers()

    def validate_duplicate_invoice_numbers(self) -> None:

        invoice_number = self.bill_no
        control_number = self.bill_control

        if not invoice_number and not control_number:
            return

        new_filter = {}
        or_filters = {}

        new_filter = {
            'docstatus': 1,
            'name': ['!=', self.name],
            'supplier': ['=', self.supplier],
        }

        if invoice_number:
            or_filters["bill_no"] = ["=", invoice_number]

        if control_number:
            or_filters["bill_control"] = ["=", control_number]

        if len(or_filters) > 1:
            filters = {**new_filter, **or_filters}

        if frappe.db.get_all("Purchase Invoice",
                             filters=filters):
            message = (
                "El número de factura o número de control, ya se encuentra asignado a otra factura del mismo proveedor. Intente nuevamente")  # noqa
            frappe.throw(message)

