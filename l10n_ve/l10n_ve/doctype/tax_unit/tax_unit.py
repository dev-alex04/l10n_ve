# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from frappe.model.document import Document
import frappe

class TaxUnit(Document):

    def validate(self) -> None:

        if not self.is_active:
            return

        value = frappe.db.get_all('Tax Unit',
                                  filters={
                                        'is_active': True,
                                        'name':['!=', self.name]
                                  })

        if not value:
            return

        frappe.throw('No se puede activar esta unidad tributaria ya que existe otra unidad tributaria activa.')

