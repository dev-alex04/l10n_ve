import frappe
from erpnext.setup.doctype.company.company import Company
class CustomCompany(Company):
            
    def before_save(self):
        # Inicializa los campos si están vacíos al crear la compañía
        if not self.vat_withholding_format:
            # Puedes usar un formato por defecto si el cliente no lo ha especificado
            self.vat_withholding_format = "##############" 
        
        if not self.vat_withholding_correlative:
            self.vat_withholding_correlative = 1