from erpnext.buying.doctype.supplier_quotation.supplier_quotation import SupplierQuotation
from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomSupplierQuotation(TaxesMixin, SupplierQuotation):

    def validate(self) -> None:
        super().validate()
