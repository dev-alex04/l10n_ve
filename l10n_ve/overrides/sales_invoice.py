import frappe     
from frappe.model.document import Document
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
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
        super().validate()
        # validación de numero de control y de factura
        self._validate_bill_control(raise_throw=True)
        self._validate_bill_no(raise_throw=True)
        # 
        self.validate_vat_tax()
        self.template_change()
       
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
    
    def get_iva_tax_row(self):
        """Función auxiliar para encontrar y devolver la fila del impuesto de IVA de la factura."""
        # Obtener el nombre de la cuenta de IVA de la plantilla
        vat_tax_account = frappe.db.get_value(
            "Sales Taxes and Charges Template",
            self.taxes_and_charges,
            "withholding_account_head"
        )
        
        if not vat_tax_account:
            return None

        # Encuentra la fila del impuesto de IVA usando la cuenta de la plantilla
        for tax_row in self.taxes:
            if tax_row.account_head == vat_tax_account:
                return tax_row
        
        return None

    def validate_vat_tax(self):
        """Valida que la cuenta de IVA tenga un monto positivo (crédito)."""
        vat_tax = self.get_iva_tax_row()
        
        # Si se encontró una fila de IVA, verifica si su monto es positivo.
        if vat_tax and vat_tax.tax_amount <= 0:
            frappe.throw("El balance para la cuenta de IVA debe ser de crédito. Por favor, asegure que el monto del impuesto es un valor positivo.")

    def template_change(self):
        # 1. Verificar si el cliente es un contribuyente especial
        is_special_taxpayer = frappe.db.get_value("Customer", self.customer, "is_special_taxpayer")
    
        if not is_special_taxpayer:
            return

        # Obtener la categoría de retención directamente de la plantilla de impuestos
        taxes_and_charges_template = self.taxes_and_charges
        
        if not taxes_and_charges_template:
            return 
        
        withholding_category_name = frappe.db.get_value("Sales Taxes and Charges Template", taxes_and_charges_template, "withholding")

        if withholding_category_name:
        
            withholding_description = frappe.db.get_value("Tax Withholding Category", withholding_category_name, "name")
            
            #  Verificar si la factura ya tiene la retención de IVA y eliminarla para volver a calcularla
            self.taxes = [row for row in self.taxes if row.description != withholding_description]

            #  Obtener la tasa de retención directamente del campo 'sales_vat_withholding_rate' en la Compañía
            company = frappe.db.get_value("Company", self.company, "name")
            if not company:
                frappe.throw("Compañía no encontrada.")
            withholding_rate = frappe.db.get_value("Company", company, "sales_vat_withholding_rate")

            #  Obtener la cuenta contable de la categoría de retención
            withholding_account = frappe.db.get_value("Tax Withholding Account", {"parent": withholding_category_name}, "account")

            #  Encontrar el impuesto de IVA en las filas de la factura usando la nueva función auxiliar
            vat_tax = self.get_iva_tax_row()
                
            #  Si se encontró el IVA y existe la tasa de retención, agregar la nueva fila de retención
            if vat_tax and withholding_rate:
                iva_amount = vat_tax.tax_amount
                withholding_amount = (iva_amount * withholding_rate) / 100.0

                self.append("taxes", {
                    "charge_type": "Actual",
                    "add_deduct_tax": "Deduct",
                    "account_head": withholding_account,
                    "description": withholding_description,
                    "rate": withholding_rate,
                    "tax_amount": -withholding_amount,
                })
            
            self.calculate_taxes_and_totals()
            
            for row in self.taxes:
                if  row.description == withholding_description:
                    row.rate = withholding_rate
