import frappe
from frappe import _dict

from erpnext.utilities.utils import get_link_to_form
from erpnext.accounts.doctype.tax_withholding_category.tax_withholding_category import TaxWithholdingCategory

from l10n_ve.utils.constants import DocumentTransactionType

class CustomTaxWithholdingCategory(TaxWithholdingCategory):

    def get_withholding(self, company: str, doctype: str) -> dict:

        if doctype in DocumentTransactionType.__SALES_DOCTYPES__:
            account_field = 'sales_account'
        elif doctype in DocumentTransactionType.__PURCHASE_DOCTYPES__:
            account_field = 'account'
        else:
            return {}

        for account in self.accounts or []:
            if account.company != company:
                continue

            withholding_link: str = get_link_to_form(self.doctype, self.name)

            if not self.rates:
                frappe.throw(f'Debe establecer una tasa de retención en {withholding_link}')

            rate = self.rates[0].tax_withholding_rate

            return _dict({
                "rate": rate,
                "category": 'Total',
                "add_deduct_tax": 'Deduct',
                "description": f'{self.name}',
                "charge_type": "VAT Withholding",
                "is_tax_withholding_account": True,
                "account_head": account.get(account_field),
            })

        else:
            return {}
