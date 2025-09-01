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
        self._validate_bill_control(raise_throw=True)
        self._validate_bill_no(raise_throw=True)
        super().validate()
    
    def set_control_and_invoice_number(self):
        """
        Asigna el número de control y de factura si no existen.
        Utiliza un bucle para asegurar la unicidad en caso de concurrencia.
        """
        if self.bill_control and self.bill_no:
            return

      
        while True:
            # Carga el documento Company (con su clase de override)
            company: CustomCompany = frappe.get_doc('Company', self.company)
            
            
            numbers = company.get_control_and_invoice_number()
            bill_control = numbers.get('bill_control')
            bill_no = numbers.get('bill_no')

            # Valida si los números están duplicados.
            if not self._validate_bill_control(bill_control, raise_throw=False) or not self._validate_bill_no(bill_no, raise_throw=False):
                # Si son duplicados, se revierte y el bucle continúa
                frappe.db.rollback()
                continue

            self.bill_control = bill_control
            self.bill_no = bill_no
            
            break

    def _validate_bill_control(self, bill_control: str = None, raise_throw: bool = True) -> bool:
        """
        Valida que el número de control no esté ya asignado.
        Acepta un valor opcional para validar.
        """
        bill_control_to_validate = bill_control or self.bill_control
        if not bill_control_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'bill_control': bill_control_to_validate
            }
        )
        
        if is_duplicated:
            message = ("El número de control ya está asignado a otra factura.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False

        return True


    def _validate_bill_no(self, bill_no: str = None, raise_throw: bool = True) -> bool:
        """
        Valida que el número de factura no esté ya asignado.
        Acepta un valor opcional para validar.
        """
        bill_no_to_validate = bill_no or self.bill_no
        if not bill_no_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'bill_no': bill_no_to_validate
            }
        )

        if is_duplicated:
            message = ("El número de factura ya está asignado a otra factura.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False
        
        return True
     
    def before_save(self):
        super().before_save()
        self.template_change()

    def template_change(self):
       
        is_special_taxpayer = frappe.db.get_value("Customer", self.customer, "is_special_taxpayer")
        
        
        if not is_special_taxpayer:
            return

        if any(row.description == "Retención de IVA" for row in self.taxes):
            return 

       
        taxes_and_charges_template = self.taxes_and_charges
        
        if not taxes_and_charges_template:
            return 

        
        withholding_category_name = frappe.db.get_value("Sales Taxes and Charges Template", taxes_and_charges_template, "withholding")

        if withholding_category_name:
           
            withholding_rate = frappe.db.get_value("Tax Withholding Rate", {"parent": withholding_category_name}, "tax_withholding_rate")
            withholding_account = frappe.db.get_value("Tax Withholding Account", {"parent": withholding_category_name}, "account")

            vat_tax = None
            for tax_row in self.taxes:
                if "IVA" in tax_row.account_head:
                    vat_tax = tax_row
                    break
           
            if vat_tax:
                self.append("taxes", {
                   
                    "charge_type": "On Previous Row Amount", 
                    "add_deduct_tax": "Deduct",
                    "account_head": withholding_account,
                    "description": "Retención de IVA",
                    "rate": withholding_rate,
                    "amount": 0, 
                    "total": 0,  
                })