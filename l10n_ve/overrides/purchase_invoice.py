import frappe
from frappe.utils import flt
from frappe import _, _dict
from erpnext.accounts.utils import get_account_currency

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomPurchaseInvoice(PurchaseInvoice):

    def on_cancel(self) -> None:
        super().on_cancel()

        has_iva_withholding = frappe.db.exists(
            "VAT Withholding Voucher Item",
            { "purchase_invoice": self.name }
        )

        has_islr_withholding = frappe.db.exists(
            "ISLR Withholding Voucher Item",
            { "purchase_invoice": self.name }
        )

        reasons = []
        if has_iva_withholding:
            reasons.append("un Comprobante de retención de IVA")

        if has_islr_withholding:
            reasons.append("un Comprobante de retención de ISLR")

        if reasons:
            message = "No se puede cancelar esta factura. Está asociada a " + " y a ".join(reasons) + "."
            frappe.throw(message, frappe.ValidationError)

    def validate(self) -> None:
        super().validate()

        self.validate_duplicate_invoice_numbers()
        self.set_affected_invoice_number()

        has_taxable_items = False
        for item in self.items:
            if not item.vat_exempt:
                has_taxable_items = True
                break

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])

            self.apply_tds = 0

        has_vat_charge = False
        for tax in self.taxes:
            if tax.charge_type == 'VAT':
                has_vat_charge = True
                break

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

        if self.is_debit_note:
            self.validate_debit_note_number()
            self.validate_affected_invoice_number()
        elif self.is_return:
            self.validate_credit_note_number()

        self.calculate_taxes_and_totals()

    def validate_affected_invoice_number(self) -> None:
        if self.is_debit_note:
            if not self.affected_invoice_number:
                frappe.throw("El número de la Factura Afectada es obligatorio.")
            else:
                affected_invoice_exists = frappe.db.exists(
                    "Purchase Invoice", {
                        "supplier": self.supplier,
                        "bill_no": self.affected_invoice_number,
                        "name": ["!=", self.name],
                        "is_debit_note": 0,
                        "is_return": 0
                    }
                )

                if not affected_invoice_exists:
                    frappe.throw("La factura con el número de Factura Afectada no existe.")

    def validate_debit_note_number(self) -> None:
        if self.is_debit_note:
            if not self.debit_note_no:
                frappe.throw("El número de la Nota de Débito es obligatorio para una Nota de Débito.")

            debit_note_exists = frappe.db.exists(
                "Purchase Invoice", {
                    "debit_note_no": self.debit_note_no,
                    "supplier": self.supplier,
                    "is_debit_note": 1,
                    "name": ["!=", self.name]
                }
            )

            if debit_note_exists:
                frappe.throw(f"Ya existe una Nota de Débito con el número {self.debit_note_no} para este proveedor.")

    def validate_credit_note_number(self) -> None:
        if self.is_return:
            if not self.credit_note_no:
                frappe.throw("El número de la Nota de Crédito es obligatorio para una Nota de Crédito.")

            credit_note_exists = frappe.db.exists(
                "Purchase Invoice", {
                    "credit_note_no": self.credit_note_no,
                    "supplier": self.supplier,
                    "is_return": 1,
                    "name": ["!=", self.name]
                }
            )

            if credit_note_exists:
                frappe.throw(f"Ya existe una Nota de Crédito con el número {self.credit_note_no} para este proveedor.")

    def calculate_taxes_and_totals(self) -> None:
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

        self.calculate_total_withholding()

    def set_affected_invoice_number(self) -> None:
        if self.is_return or self.is_debit_note :

            if self.return_against:
                self.affected_invoice_number  = frappe.db.get_value(
                    "Purchase Invoice",
                    self.return_against,
                    "bill_no"
                )

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:

        tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

        type_of_person: str = frappe.db.get_value("Supplier",
                                                  self.supplier,
                                                  "type_of_person")

        account_head: str = frappe.db.get_value("Company",
                                                  self.company,
                                                  "purchase_islr_account")

        for aliquot in tabulator.aliquot:
            if type_of_person == aliquot.types_of_person:

                self.append("taxes", {
                    "category": "Total",
                    "charge_type": "ISLR",
                    "add_deduct_tax": "Deduct",
                    "rate": aliquot.aliquot,
                    "code": tabulator.codigo,
                    "account_head": account_head,
                    "is_tax_withholding_account": True,
                    "subtracting": aliquot.subtracting,
                    "description": tabulator.descripcion,
                    "percentage_base": aliquot.percentage_base,
                })

        self.save()
        return self.name

    def validate_duplicate_invoice_numbers(self) -> None:
        if self.bill_no:
            filters_bill_no = {
                'docstatus': ['!=', 2],
                'bill_no': self.bill_no,
                'supplier': self.supplier,
                'name': ('!=', self.name),
            }

            if frappe.db.get_all("Purchase Invoice", filters=filters_bill_no):
                message = "El número de factura ya se encuentra asignado a otra factura del mismo proveedor."
                frappe.throw(message)

        if self.bill_control:
            filters_bill_control = {
                'docstatus': ['!=', 2],
                'name': ['!=', self.name],
                'supplier': self.supplier,
                'bill_control': self.bill_control,
            }

            if frappe.db.get_all("Purchase Invoice", filters=filters_bill_control):
                message = "El número de control ya se encuentra asignado a otra factura del mismo proveedor."
                frappe.throw(message)

    def set_tax_withholding(self) -> None:

        withholding_category_name = frappe.db.get_value("Supplier",
                                                        self.supplier,
                                                        "tax_withholding_category")
        if not withholding_category_name:
            return

        withholding_category = frappe.get_doc("Tax Withholding Category",
                                              withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)
        if self.is_return:
            if not self.return_against:
                return

            withholding['description'] = \
                f'{withholding.description} por Nota de Crédito contra factura {self.affected_invoice_number}'

        elif self.is_debit_note:

            withholding.description = \
                f'{withholding["description"]} por Nota de Crédito contra factura {self.affected_invoice_number}'

        # Primero se limpia la tabla de impuestos
        # Dejando solo los impuestos que no sean retencion de IVA
        self.taxes = [
            tax
            for tax in self.taxes or []
            if tax.charge_type != withholding.charge_type
        ]

        self.append("taxes", withholding)

    def calculate_total_withholding(self) -> None:
        self.total_withholding = 0.0

        if not self.get("taxes"):
            return

        for tax in self.get("taxes"):

            if not tax.is_tax_withholding_account:
                continue

            self.total_withholding += tax.get('tax_amount', 0)

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """
        Tax withholding amount is not part of supplier invoice.
        Separate supplier GL Entry for correct reporting.
        """

        for tax in self.get("taxes") or []:

            if not tax.is_tax_withholding_account or not tax.tax_amount:
                continue

            if (
                self.is_return
                and self.return_against
                and not self.update_outstanding_for_self
            ):
                against_voucher = self.return_against
            else:
                against_voucher = self.name

            debit_or_credit = "debit" if self.docstatus == 1 else "credit"

            gl = {
                "account": self.credit_to,
                "against": tax.account_head,
                "against_voucher": against_voucher,
                "against_voucher_type": self.doctype,
                "cost_center": self.cost_center,
                debit_or_credit: tax.tax_amount,
                f"{debit_or_credit}_in_account_currency": tax.tax_amount,
                f"{debit_or_credit}_in_transaction_currency": tax.tax_amount,
                "due_date": self.due_date,
                "party": self.supplier,
                "party_type": "Supplier",
                "project": self.project,
                "remarks": self.remarks,
                "_skip_merge": True,
            }

            gl_entries.append(self.get_gl_dict(gl, self.party_account_currency, item=self))
