from frappe.utils import cint, flt
from frappe.model.document import Document

from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals

class TaxesAndTotals(calculate_taxes_and_totals):
    def __init__(self, doc):
        super().__init__(doc)

    def calculate_total_exempt(self):
        total_exempt = 0
        for item in self.doc.items:
            if item.vat_exempt:
                total_exempt += item.amount

        self.doc.total_exempt = total_exempt

    def get_current_tax_amount(self, item, tax, item_tax_map):
        tax_rate = self._get_tax_rate(tax, item_tax_map)
        current_tax_amount = 0.0

        if tax.charge_type == "Actual":
            # distribute the tax amount proportionally to each item row
            actual = flt(tax.tax_amount, tax.precision("tax_amount"))

            if tax.get("is_tax_withholding_account") and item.meta.get_field("apply_tds"):
                if not item.get("apply_tds") or not self.doc.tax_withholding_net_total:
                    current_tax_amount = 0.0
                else:
                    current_tax_amount = item.net_amount * actual / self.doc.tax_withholding_net_total
            else:
                current_tax_amount = (
                    item.net_amount * actual / self.doc.net_total if self.doc.net_total else 0.0
                )

        elif tax.charge_type == "On Net Total":
            if item.idx == 1:
                taxable_base = 0
                for doc_item in self.doc.items:
                    if not doc_item.vat_exempt:
                        taxable_base += doc_item.net_amount
                current_tax_amount = (tax_rate / 100.0) * taxable_base
            else:
                current_tax_amount = 0

        elif tax.charge_type == "On Previous Row Amount":
            current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
                cint(tax.row_id) - 1
            ].tax_amount_for_current_item

        elif tax.charge_type == "On Previous Row Total":
            current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
                cint(tax.row_id) - 1
            ].grand_total_for_current_item

        elif tax.charge_type == "On Item Quantity":
            current_tax_amount = tax_rate * item.qty
            
        elif tax.charge_type == "ISLR":
            if item.idx == 1:
                tax_base = (self.doc.total * tax.percentage_base) / 100
                tax_amount = ((tax_base * tax.rate) / 100) - tax.subtracting
                
                current_tax_amount = tax_amount if tax_amount > 0 else 0
            else:
                current_tax_amount = 0

            current_tax_amount = tax_amount if tax_amount > 0 else 0
            
        elif tax.charge_type == "VAT Withholding":

            tax_base = self.doc.get("taxes")[cint(tax.idx) - 2].tax_amount                                   

            current_tax_amount = (tax_base * tax.rate) / 100        

        if not (self.doc.get("is_consolidated") or tax.get("dont_recompute_tax")):
            self.set_item_wise_tax(item, tax, tax_rate, current_tax_amount)

        return current_tax_amount
    
    def get_tax_amount_if_for_valuation_or_deduction(self,
                                                        tax_amount: float,
                                                        tax: Document) -> float:

            # if just for valuation, do not add the tax amount in total
            # if tax/charges is for deduction, multiply by -1
            tax_amount = 0.0 \
                if (tax.get('category', '') == "Valuation") else tax_amount

            if self.doc.doctype in [
                "Sales Invoice",
                "Purchase Order",
                "Purchase Invoice",
                "Purchase Receipt",
                "Supplier Quotation",
            ]:
                tax_amount *= -1.0 if (tax.add_deduct_tax == "Deduct") else 1.0

            return tax_amount
    