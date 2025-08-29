import frappe     
# import frappe
from frappe.model.document import Document
# Importa la clase original de Sales Invoice
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
# Importa tu clase personalizada de Company
from l10n_ve.overrides.company import CustomCompany

class CustomSalesInvoice(SalesInvoice):

    def before_submit(self) -> None:
        
        """
        Llamado antes de que el documento sea enviado. Asigna números de control
        y de factura si no existen.
        """
        
        super().before_submit()
        self.set_control_and_invoice_number()

    def validate(self):
        self._validate_numbers(raise_throw=True)
        super().validate()
    
    def set_control_and_invoice_number(self):
        """
        Asigna el número de control y de factura si no existen.
        Utiliza un bucle para asegurar la unicidad en caso de concurrencia.
        """
        if self.bill_control and self.bill_no:
            return

        # Bucle para obtener y validar los números
        while True:
            # Carga el documento Company (con su clase de override)
            company: CustomCompany = frappe.get_doc('Company', self.company)
            
            # Pide el siguiente par de números formateados
            numbers = company.get_control_and_invoice_number()
            bill_control = numbers.get('bill_control')
            bill_no = numbers.get('bill_no')

            # Valida si los números están duplicados.
            if not self._validate_numbers(bill_control, bill_no, raise_throw=False):
                # Si son duplicados, se revierte y el bucle continúa
                continue
            
            # Si no son duplicados, asigna los números a la instancia actual
            self.bill_control = bill_control
            self.bill_no = bill_no
            
            # Le dice a la compañía que incremente y guarde el siguiente correlativo
            
            
            # Sale del bucle al encontrar un par de números válidos
            break

    def _validate_numbers(self, bill_control: str = None, bill_no: str = None, raise_throw: bool = True) -> bool:
       
        """
        Valida que el número de factura o el número de control no estén ya asignados.
        """
        bill_control = bill_control or self.bill_control
        bill_no = bill_no or self.bill_no

        if not bill_control and not bill_no:
            return True

        # Usar una consulta SQL para manejar la condición OR
        query = """
            SELECT
                name
            FROM
                `tabSales Invoice`
            WHERE
                docstatus = 1
                AND company = %(company)s
                AND name != %(name)s
                AND (
                    bill_control = %(bill_control)s
                    OR bill_no = %(bill_no)s
                )
        """
        
        # Prepara los valores para la consulta
        values = {
            "company": self.company,
            "name": self.name,
            "bill_control": bill_control,
            "bill_no": bill_no
        }
        
        # Ejecuta la consulta y verifica si existe algún resultado
        duplicates = frappe.db.sql(query, values, as_dict=True)
        is_duplicated = len(duplicates) > 0

        if is_duplicated:
            message = ("El número de factura o de control ya está asignado a otra factura.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False

        return True