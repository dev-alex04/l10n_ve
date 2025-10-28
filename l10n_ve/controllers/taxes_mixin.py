import frappe
from frappe import _, _dict
from frappe.utils import flt, get_link_to_form, getdate, cint
import erpnext

from erpnext.stock import get_warehouse_account_map
from erpnext.accounts.utils import get_account_currency
from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled
from erpnext.assets.doctype.asset_category.asset_category import get_asset_category_account

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals

class TaxesMixin:
    # TODO: Mover esto a una sola funcion
    def calculate_total_withholding(self) -> None:

        self.total_withholding = 0.0

        self.total_withholding = sum([
            tax.tax_amount
            for tax in self.taxes or []
            if tax.is_tax_withholding_account
        ])

    # ------------------------------ OVERRIDES ------------------------------ #

    def set_taxes_and_charges(self) -> None:
        super().set_taxes_and_charges()

        self.set_tax_withholding_ve()

    def calculate_taxes_and_totals(self) -> None:
        taxes_and_totals_calculator = TaxesAndTotals(self)
        taxes_and_totals_calculator.calculate_total_exempt()

        self.calculate_total_withholding()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_tax_withholding_ve  se encargara de esto
        """
        return

    # TODO: Refactorizar a una sola funcion
    def set_tax_withholding_ve(self) -> None:
        if self.doctype == "Purchase Invoice" or self.doctype == "Purchase Order":
            if not bool(frappe.db.get_value('Company',
                                            self.company,
                                            'is_special_taxpayer')):
                return

            withholding_category_name = frappe.db.get_value("Supplier",
                                                        self.supplier,
                                                        "tax_withholding_category")
        else:
            if not bool(frappe.db.get_value('Customer',
                                        self.customer,
                                        'is_special_taxpayer')):
                return

            withholding_category_name: str = frappe.db.get_value(
                "Company",
                self.company,
                "tax_withholding_category")

        if not withholding_category_name:
            return

        withholding_category = frappe.get_doc("Tax Withholding Category",
                                              withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)

        if self.doctype == "Sales Invoice" or self.doctype == "Purchase Invoice":
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
            if tax.get('charge_type') != withholding.get('charge_type')
        ]

        self.append("taxes", withholding)

    def make_tax_gl_entries(self, gl_entries) -> None:

        if self.doctype in ("Sales Invoice", "Sales Order"):
            enable_discount_accounting = cint(
                frappe.db.get_single_value("Selling Settings", "enable_discount_accounting")
            )

            for tax in self.get("taxes"):
                amount, base_amount = self.get_tax_amounts(tax, enable_discount_accounting)

                if flt(tax.base_tax_amount_after_discount_amount):
                    account_currency = get_account_currency(tax.account_head)

                    if tax.charge_type == 'VAT':
                        debit_or_credit = 'credit'
                    else:
                        debit_or_credit = 'debit'

                    gl_entries.append(
                        self.get_gl_dict(
                            {
                                "account": tax.account_head,
                                "against": self.customer,
                                debit_or_credit: flt(base_amount, tax.precision("tax_amount_after_discount_amount")),
                                f"{debit_or_credit}_in_account_currency": (
                                    flt(base_amount, tax.precision("base_tax_amount_after_discount_amount"))
                                    if account_currency == self.company_currency
                                    else flt(amount, tax.precision("tax_amount_after_discount_amount"))
                                ),
                                f"{debit_or_credit}_in_transaction_currency": flt(
                                    amount, tax.precision("tax_amount_after_discount_amount")
                                ),
                                "cost_center": tax.cost_center,
                            },
                            account_currency,
                            item=tax,
                        )
                    )
        else:
            """
            Override para solo hacer los asientos que NO sean de retenciones
            """

            # tax table gl entries
            valuation_tax = {}

            for tax in self.get("taxes"):

                if tax.is_tax_withholding_account or not tax.tax_amount:
                    continue

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

                    if tax.is_tax_withholding_account:
                        continue

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

                    if tax.is_tax_withholding_account:
                        continue

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

    def make_gl_entries_for_tax_withholding(self, gl_entries) -> None:
        """
        Se inactiva esta funcion, ya que aqui no se harán los asientos de las retenciones
        """
        return
