import frappe
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals

class CustomPurchaseInvoice(PurchaseInvoice):

    def before_submit(self) -> None:
        super().before_submit()
        self.validate_duplicate_invoice_numbers()

    def calculate_taxes_and_totals(self):
        taxes_and_totals_calculator = TaxesAndTotals(self)
        taxes_and_totals_calculator.calculate_total_exempt()

        if self.doctype in (
            "Sales Order",
            "Delivery Note",
            "Sales Invoice",
            "POS Invoice",
        ):
            self.calculate_commission()
            self.calculate_contribution()

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:

        tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

        type_of_person: str = frappe.db.get_value("Supplier", 
                                                  self.supplier, 
                                                  "type_of_person")

        account_head: str = frappe.db.get_value("Company", 
                                                  self.company, 
                                                  "account_head")
        
        for aliquot in tabulator.aliquot:
            if type_of_person == aliquot.types_of_person:

                self.append("taxes", {
                    "category": "Total",
                    "charge_type": "ISLR",
                    "add_deduct_tax": "Add",
                    "rate": aliquot.aliquot,
                    "code": tabulator.codigo,
                    "account_head": account_head,
                    "subtracting": aliquot.subtracting,
                    "description": tabulator.descripcion,
                    "percentage_base": aliquot.percentage_base,
                })

        self.save()
        return self.name

    def validate_duplicate_invoice_numbers(self) -> None:

        numero_factura = self.bill_no
        numero_control = self.bill_control

        if not numero_factura and not numero_control:
            return

        new_filter = {}
        or_filters = {}

        new_filter = {
            'docstatus': 1,
            'name': ['!=', self.name],
            'supplier': ['=', self.supplier],
        }

        if numero_factura:
            or_filters["bill_no"] = ["=", numero_factura]

        if numero_control:
            or_filters["bill_control"] = ["=", numero_control]

        if len(or_filters) > 1:
            filters = {**new_filter, **or_filters}

        if frappe.db.get_all("Purchase Invoice",
                             filters=filters):
            message = (
                "El número de factura o número de control, ya se encuentra asignado a otra factura del mismo proveedor. Intente nuevamente")  # noqa
            frappe.throw(message)

    def set_tax_withholding(self) -> None:
        super(CustomPurchaseInvoice, self).set_tax_withholding()

        if not self.tax_withholding_category:
            return

        retention_details = frappe.get_all(
            "Tax Withholding Account",
            filters={"parent": self.tax_withholding_category},
            pluck="account"
        )
        if not retention_details:
            return
        retention_account_head = retention_details[0]

        retention_rate_data = frappe.get_all(
            "Tax Withholding Rate",
            filters={"parent": self.tax_withholding_category},
            pluck="tax_withholding_rate"
        )
        if not retention_rate_data:
            return
        retention_rate = retention_rate_data[0]

        iva_amount = 0
        retention_row = None

        for tax in self.taxes:
            if tax.charge_type == 'On Net Total':
                iva_amount = tax.tax_amount

            if tax.account_head == retention_account_head:
                retention_row = tax

        if retention_row and iva_amount > 0:
            retention_amount = (retention_rate / 100) * iva_amount

            retention_row.tax_amount = retention_amount

            self.calculate_taxes_and_totals()

            retention_row.rate = retention_rate
