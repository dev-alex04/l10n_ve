from erpnext.selling.doctype.quotation.quotation import Quotation
from l10n_ve.controllers.taxes_mixin import TaxesMixin

class CustomQuotation(TaxesMixin, Quotation):

    def validate(self) -> None:
        super().validate()
