from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder
from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomPurchaseOrder(TaxesMixin, PurchaseOrder):

    def validate(self) -> None:
        super().validate()
