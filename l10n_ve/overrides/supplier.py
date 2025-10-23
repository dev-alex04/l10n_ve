from erpnext.buying.doctype.supplier.supplier import Supplier
from l10n_ve.utils.utils import validate_tax_id_format, validate_taxpayer_and_person_type_consistency


class CustomSupplier(Supplier):
    def validate(self):
        super().validate()
        validate_tax_id_format(self)
        validate_taxpayer_and_person_type_consistency(self)