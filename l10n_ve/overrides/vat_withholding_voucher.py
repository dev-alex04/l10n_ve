import frappe
from frappe.model.document import Document

class VATWithholdingVoucher(Document):
    def onload(self):
        super(VATWithholdingVoucher, self).onload()
        if self.supplier:
            self.set_invoice_filters()

    def set_invoice_filters(self):
        filters = {}
        filters['supplier'] = self.supplier
        print(filters)
        frappe.ui.form.add_filter(self, 'VAT Withholding Voucher Item', 'purchase_invoice', filters)