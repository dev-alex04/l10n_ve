import frappe
from frappe import _, _dict

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.utils.constants import DocumentTransactionType
from frappe.utils import flt


class TaxesMixin:
    def validate_tax_structure(self) -> None:

        has_taxable_items = any(not item.vat_exempt for item in self.items)

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])
            self.apply_tds = 0

        has_vat_charge = any(tax.charge_type == 'VAT' for tax in self.taxes or [])

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

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
        self.set_islr_withholding_ve()

        for i, tax in enumerate(self.taxes or [], start=1):
            tax.idx = i

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

    def set_tax_withholding_ve(self) -> None:
        self.taxes = [
            tax for tax in self.taxes or []
            if not tax.get('is_tax_withholding_account') or tax.get('charge_type') == 'ISLR'
        ]

        if self.doctype in ("Purchase Invoice", "Purchase Order", "Supplier Quotation"):
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
                "Customer",
                self.customer,
                "tax_withholding_category")

        if not withholding_category_name:
            return

        withholding_category = frappe.get_cached_doc("Tax Withholding Category",
                                                      withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)

        if self.doctype in ("Purchase Invoice", "Sales Invoice", "VE Sales Credit Note"):
            affected = self.get("affected_invoice_number") or self.return_against
            if self.is_return:
                if not self.return_against:
                    return

                withholding['description'] = \
                    f'{withholding["description"]} por Nota de Crédito contra factura {affected}'

            elif self.is_debit_note:

                withholding['description'] = \
                    f'{withholding["description"]} por Nota de Crédito contra factura {affected}'


        self.append("taxes", withholding)

    def set_islr_withholding_ve(self) -> None:
        """Agrega retención ISLR a la tabla de impuestos para Sales Invoice y VE Sales Credit Note."""
        if self.doctype not in ("Sales Invoice", "VE Sales Credit Note"):
            return

        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") != "ISLR"
        ]

        tabulator_name: str = frappe.db.get_value(
            "Customer", self.customer, "tabulator_islr"
        ) or ""
        if not tabulator_name:
            return

        islr_account: str = frappe.get_cached_value(
            "Company", self.company, "sales_islr_account"
        ) or ""
        if not islr_account:
            return

        tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
        if not tabulator.aliquot:
            return
        aliquot_info = tabulator.aliquot[0]

        if not aliquot_info:
            return

        base_amount: float = flt(self.total)
        tax_base: float = flt(base_amount * flt(aliquot_info.percentage_base) / 100, 2)
        islr_amount: float = flt(
            (tax_base * flt(aliquot_info.aliquot) / 100) - flt(aliquot_info.subtracting), 2
        )

        if islr_amount <= 0:
            return

        description: str = f"ISLR {tabulator_name} {tabulator.descripcion} ({flt(aliquot_info.aliquot)}%)"
        if self.is_return and self.return_against:

            type_doctype: str = (
                "Sales" if self.doctype in DocumentTransactionType.__SALES_DOCTYPES__
                else "Purchase"
            )

            affected_invoice_number: str = frappe.get_cached_value(
                f"{type_doctype} Invoice",
                self.return_against,
                "bill_no"
            )

            description += f" por Nota de Crédito contra factura {affected_invoice_number}"

        self.append("taxes", _dict({
            "charge_type": "ISLR",
            "category": "Total",
            "add_deduct_tax": "Deduct",
            "description": description,
            "is_tax_withholding_account": True,
            "account_head": islr_account,
            "tax_amount": islr_amount,
            "base_tax_amount": islr_amount,
            "rate": flt(aliquot_info.aliquot),
            "percentage_base": flt(aliquot_info.percentage_base),
            "subtracting": flt(aliquot_info.subtracting),
        }))
