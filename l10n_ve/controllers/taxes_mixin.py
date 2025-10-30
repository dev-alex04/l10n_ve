import frappe
from frappe import _, _dict

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals

class TaxesMixin:
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

    def set_tax_withholding_ve(self) -> None:
        if self.doctype in ("Purchase Invoice", "Purchase Order"):
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

        if self.doctype in ("Purchase Invoice", "Sales Invoice"):
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
