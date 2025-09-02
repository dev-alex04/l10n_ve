import frappe
from erpnext.setup.doctype.company.company import Company

class CustomCompany(Company):

    def get_withholding_voucher_number(self) -> str:

        withholding_format: str = self.vat_withholding_format
        correlative_number: str = self.vat_withholding_number

        withholding_voucher_number = f'{withholding_format[:-len(str(correlative_number))]}{correlative_number}'  # noqa

        self.vat_withholding_number += 1

        self.save()

        return withholding_voucher_number

