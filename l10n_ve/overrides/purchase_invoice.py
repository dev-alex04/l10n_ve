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
                'supplier': self.supplier,
                'bill_no': self.bill_no,
                # 'docstatus': 1,
                'name': ('!=', self.name),
            }
            if frappe.db.get_all("Purchase Invoice", filters=filters_bill_no):
                message = "El número de factura ya se encuentra asignado a otra factura del mismo proveedor."
                frappe.throw(message)

        if self.bill_control:
            filters_bill_control = {
                'supplier': self.supplier,
                'bill_control': self.bill_control,
                # 'docstatus': 1,
                'name': ('!=', self.name),
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

    def make_tax_gl_entries(self, gl_entries) -> None:
            valuation_tax = {}

            for tax in self.get("taxes"):
                amount, base_amount = self.get_tax_amounts(tax, None)
                if tax.category in ("Total", "Valuation and Total") and flt(base_amount):
                    account_currency = get_account_currency(tax.account_head)

                    dr_or_cr = "debit" if tax.add_deduct_tax == "Add" else "credit"

                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": tax.account_head,
                                "against": self.supplier,
                                dr_or_cr: base_amount,
                                dr_or_cr + "_in_account_currency": base_amount
                                if account_currency == self.company_currency
                                else amount,
                                dr_or_cr + "_in_transaction_currency": amount,
                                "cost_center": tax.cost_center,
                            },
                            account_currency,
                            item=tax,
                        )
                    )

                    if tax.is_tax_withholding_account:

                        gl_entries.append(
                            self.get_gl_dict(
                                {
                                    "account": self.credit_to,
                                    "party_type": "Supplier",
                                    "party": self.supplier,
                                    "due_date": self.due_date,
                                    "against": tax.account_head,
                                    "debit": tax.tax_amount,
                                    "debit_in_account_currency": tax.tax_amount,
                                    "debit_in_transaction_currency": tax.tax_amount,
                                    "against_voucher": self.name,
                                    "against_voucher_type": self.doctype,
                                    "project": self.project,
                                    "cost_center": self.cost_center,

                                },
                                account_currency,
                                item=tax,
                            )
                        )
                # accumulate valuation tax
                if (
                    self.is_opening == "No"
                    and tax.category in ("Valuation", "Valuation and Total")
                    and flt(base_amount)
                    and not self.is_internal_transfer()
                ):
                    if self.auto_accounting_for_stock and not tax.cost_center:
                        frappe.throw(
                            _("Cost Center is required in row {0} in Taxes table for type {1}").format(
                                tax.idx, _(tax.category)
                            )
                        )
                    valuation_tax.setdefault(tax.name, 0)
                    valuation_tax[tax.name] += (tax.add_deduct_tax == "Add" and 1 or -1) * flt(base_amount)

            if self.is_opening == "No" and self.negative_expense_to_be_booked and valuation_tax:
                # credit valuation tax amount in "Expenses Included In Valuation"
                # this will balance out valuation amount included in cost of goods sold

                total_valuation_amount = sum(valuation_tax.values())
                amount_including_divisional_loss = self.negative_expense_to_be_booked
                i = 1
                for tax in self.get("taxes"):
                    if valuation_tax.get(tax.name):
                        if i == len(valuation_tax):
                            applicable_amount = amount_including_divisional_loss
                        else:
                            applicable_amount = self.negative_expense_to_be_booked * (
                                valuation_tax[tax.name] / total_valuation_amount
                            )
                            amount_including_divisional_loss -= applicable_amount

                        gl_entries.append(
                            self.get_gl_dict(
                                {
                                    "account": tax.account_head,
                                    "cost_center": tax.cost_center,
                                    "against": self.supplier,
                                    "credit": applicable_amount,
                                    "credit_in_transaction_currency": flt(
                                        applicable_amount / self.conversion_rate,
                                        frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
                                    ),
                                    "remarks": self.remarks or _("Accounting Entry for Stock"),
                                },
                                item=tax,
                            )
                        )

                        i += 1

            if self.auto_accounting_for_stock and self.update_stock and valuation_tax:
                for tax in self.get("taxes"):
                    if valuation_tax.get(tax.name):
                        gl_entries.append(
                            self.get_gl_dict(
                                {
                                    "account": tax.account_head,
                                    "cost_center": tax.cost_center,
                                    "against": self.supplier,
                                    "credit": valuation_tax[tax.name],
                                    "credit_in_transaction_currency": flt(
                                        valuation_tax[tax.name] / self.conversion_rate,
                                        frappe.get_precision("Purchase Invoice Item", "item_tax_amount"),
                                    ),
                                    "remarks": self.remarks or _("Accounting Entry for Stock"),
                                },
                                item=tax,
                            )
                        )