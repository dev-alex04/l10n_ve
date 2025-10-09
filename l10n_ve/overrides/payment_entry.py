import frappe
from frappe.utils import cint, flt
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry


class CustomPaymentEntry(PaymentEntry):
    pass

    def apply_taxes(self) -> None:
        self.initialize_taxes()
        self.set_taxes_withholding()
        self.determine_exclusive_rate()
        self.calculate_taxes()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_taxes_withholding  se encargara de esto
        """
        return

    def set_taxes_withholding(self) -> None:

        self.taxes = []

        documents_map = {}

        for reference in self.references or []:

            if reference.reference_doctype not in documents_map:
                documents_map[reference.reference_doctype] = []

            documents_map[reference.reference_doctype].append(reference.reference_name)

        for doctype, docnames in documents_map.items():

            doc_type = doctype.split(' ')[0]

            taxes = frappe.db.get_all(
                f'{doc_type} Taxes and Charges',
                filters={
                    'docstatus': 1,
                    'parent': ['in', docnames],
                    'is_tax_withholding_account': True,
                },
                fields=[
                    'rate',
                    'tax_amount',
                    'description',
                    'charge_type',
                    'account_head',
                    'add_deduct_tax',
                ])

            for tax in taxes:
                self.append('taxes', tax)

    def get_current_tax_amount(self, tax):
        tax_rate = tax.rate

        # To set row_id by default as previous row.
        if tax.charge_type in ["On Previous Row Amount", "On Previous Row Total"]:
            if tax.idx == 1:
                frappe.throw(
                    _(
                        "Cannot select charge type as 'On Previous Row Amount' or 'On Previous Row Total' for first row"
                    )
                )

            if not tax.row_id:
                tax.row_id = tax.idx - 1

        if tax.charge_type == "Actual":
            current_tax_amount = flt(tax.tax_amount, self.precision("tax_amount", tax))
        elif tax.charge_type == "On Paid Amount":
            current_tax_amount = (tax_rate / 100.0) * self.paid_amount_after_tax
        elif tax.charge_type == "On Previous Row Amount":
            current_tax_amount = (tax_rate / 100.0) * self.get("taxes")[cint(tax.row_id) - 1].tax_amount

        elif tax.charge_type == "On Previous Row Total":
            current_tax_amount = (tax_rate / 100.0) * self.get("taxes")[cint(tax.row_id) - 1].total

        else:
            current_tax_amount = tax.tax_amount or 0.0

        return current_tax_amount
