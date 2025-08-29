import frappe
from erpnext.setup.doctype.company.company import Company

class CustomCompany(Company):

    def get_control_and_invoice_number(self) -> dict:
        """
        Lee los correlativos actuales y los devuelve formateados.
        """
        # Formatear el número de factura
        invoice_format = self.sales_invoce_number_format or "#####"
        next_invoice_num = self.sales_invoice_number_correlative or 1
        bill_no = self.format_number(invoice_format, next_invoice_num)
        
        # Formatear el número de control
        control_format = self.sales_invoce_control_number_format or "#####"
        next_control_num = self.sales_invoice_control_number_correlative or 1
        bill_control = self.format_number(control_format, next_control_num)
        
        self.set_control_and_invoice_number()    
        return {
            'bill_control': bill_control,
            'bill_no': bill_no
        }

    def set_control_and_invoice_number(self):
        """
        Incrementa los contadores de correlativos y guarda el documento.
        """
        next_invoice = (self.sales_invoice_number_correlative or 1) + 1
        next_control = (self.sales_invoice_control_number_correlative or 1) + 1
        
        frappe.db.set_value("Company", self.name, "sales_invoice_number_correlative", next_invoice)
        frappe.db.set_value("Company", self.name, "sales_invoice_control_number_correlative", next_control)
        frappe.db.commit()

    def format_number(self, number_format: str, number: int) -> str:
        """
        Función de utilidad para aplicar el formato al número.
        """
        if '#' not in number_format:
            return f"{number_format}{number}"
        
        num_placeholders = number_format.count('#')
        formatted_number = str(number).zfill(num_placeholders)
        
        return number_format.replace('#' * num_placeholders, formatted_number)