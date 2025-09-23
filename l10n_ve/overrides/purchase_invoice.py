import frappe
from frappe.utils import flt
from frappe import _
from erpnext.accounts.utils import get_account_currency

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals



class CustomPurchaseInvoice(PurchaseInvoice):

    def before_submit(self) -> None:
        super().before_submit()
        self.validate_duplicate_invoice_numbers()

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

        if has_iva_withholding and has_islr_withholding:
            frappe.throw("No se puede cancelar esta factura. Está asociada a un Comprobante de retención de IVA y a un Comprobante de retención de ISLR.", frappe.ValidationError)
        elif has_iva_withholding:
            frappe.throw("No se puede cancelar esta factura. Está asociada a un Comprobante de retención de IVA.", frappe.ValidationError)
        elif has_islr_withholding:
            frappe.throw("No se puede cancelar esta factura. Está asociada a un Comprobante de retención de ISLR.", frappe.ValidationError)

    def validate(self):
        super().validate()

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

        self.calculate_taxes_and_totals()

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
            if tax.charge_type == 'VAT':
                iva_amount = tax.tax_amount

            if tax.account_head == retention_account_head:
                retention_row = tax

        if retention_row and iva_amount > 0:
            retention_amount = (retention_rate / 100) * iva_amount

            retention_row.tax_amount = retention_amount
            retention_row.charge_type = "VAT Withholding"
            retention_row.rate = retention_rate

        self.calculate_taxes_and_totals()


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