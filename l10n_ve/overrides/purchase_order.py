import frappe
from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder

from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomPurchaseOrder(TaxesMixin, PurchaseOrder):

    def on_cancel(self) -> None:
        super().on_cancel()

        #TODO: Mover a una funcion

        has_iva_withholding = frappe.db.exists(
            "VAT Withholding Voucher Item",
            {"purchase_invoice": self.name }
        )

        has_islr_withholding = frappe.db.exists(
            "ISLR Withholding Voucher Item",
            {"purchase_invoice": self.name }
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

        #TODO: Mover a una funcion

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
