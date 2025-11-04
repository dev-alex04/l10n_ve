import frappe

from erpnext.utilities.utils import get_link_to_form
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomSalesOrder(TaxesMixin, SalesOrder):

    def calculate_taxes_and_totals(self) -> None:

        taxes_and_totals_calculator = TaxesAndTotals(self)

        self.calculate_commission()
        self.calculate_contribution()

        taxes_and_totals_calculator.calculate_total_exempt()
        self.calculate_total_withholding()
