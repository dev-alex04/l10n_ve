import frappe
from erpnext.setup.doctype.company.company import Company

class CustomCompany(Company):

    def before_save(self):
        print("Aquiiiiiiiiiiiiiii")
        # Inicializa los campos si están vacíos al crear la compañía
        if not self.vat_withholding_format:
            # Puedes usar un formato por defecto si el cliente no lo ha especificado
            self.vat_withholding_format = "##############" 
        
        if not self.vat_withholding_correlative:
            self.vat_withholding_correlative = 1

        # self.get_correlative_number(self.vat_withholding_format, self.vat_withholding_correlative)

    # def get_correlative_number(self, vat_withholding_format, vat_withholding_correlative) -> dict:
    #     """
    #     Lee los correlativos actuales y los devuelve formateados.
    #     """
       
    #     voucher_format = self.vat_withholding_format or "##############"
    #     correlative = self.vat_withholding_correlative or 1
    #     vat_withholding_correlative = self.format_number(voucher_format, correlative)
        
    #     # self.set_control_and_invoice_number()
    #     print(vat_withholding_correlative)  
    #     return {
    #         'vat_withholding_correlative': vat_withholding_correlative
    #     }

    # def set_control_and_invoice_number(self):
    #     """
    #     Incrementa los contadores de correlativos y guarda el documento.
    #     """
    #     next_invoice = (self.sales_invoice_number_correlative or 1) + 1
    #     next_control = (self.sales_invoice_control_number_correlative or 1) + 1
        
    #     frappe.db.set_value("Company", self.name, "sales_invoice_number_correlative", next_invoice)
    #     frappe.db.set_value("Company", self.name, "sales_invoice_control_number_correlative", next_control)
    #     frappe.db.commit()

    # def format_number(self, number_format: str, number: int) -> str:
    #     """
    #     Función de utilidad para aplicar el formato al número.
    #     """
    #     if '#' not in number_format:
    #         return f"{number_format}{number}"
        
    #     num_placeholders = number_format.count('#')
    #     formatted_number = str(number).zfill(num_placeholders)
        
    #     return number_format.replace('#' * num_placeholders, formatted_number)