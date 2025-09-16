import frappe     
from frappe.model.document import Document
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from l10n_ve.overrides.company import CustomCompany
from frappe.utils import flt
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals

class CustomSalesInvoice(SalesInvoice):
    

    def calculate_taxes_and_totals(self):

        self.template_change()
      
        TaxesAndTotals(self)

        self.calculate_commission()
        self.calculate_contribution()

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
        """
        Función auxiliar para encontrar y devolver la fila del impuesto de IVA de la factura.
        Se busca en la tabla de impuestos de la factura, no en la plantilla.
        """
        # Encuentra la fila del impuesto de IVA buscando la descripción "Iva"
        for tax_row in self.taxes:
            # Una forma robusta de identificar el IVA es buscando "IVA" en la descripción
            if tax_row.charge_type == "On Net Total" and frappe.as_json(tax_row.description).lower() == '"iva"':
                return tax_row
        return None

   

    def template_change(self):
        """
        Gestiona la lógica de retención de IVA para contribuyentes especiales.
        """
        # 1. Verificar si el cliente es un contribuyente especial
        is_special_taxpayer = frappe.db.get_value("Customer", self.customer, "is_special_taxpayer")
        if not is_special_taxpayer:
            return

        # Obtener el nombre de la plantilla de impuestos y cargos
        taxes_and_charges_template_name = self.taxes_and_charges
        if not taxes_and_charges_template_name:
            return

        # Obtener el documento de la plantilla de impuestos y cargos
        taxes_and_charges_template = frappe.get_doc("Sales Taxes and Charges Template", taxes_and_charges_template_name)
        
        # 2. Obtener la categoría de retención (campo personalizado 'withholding' en tu plantilla)
        withholding_category_name = taxes_and_charges_template.withholding
        if not withholding_category_name:
            return

        # 3. Obtener el documento de la categoría de retención
        withholding_category = frappe.get_doc("Tax Withholding Category", withholding_category_name)
        if not withholding_category:
            return
        
        # 4. Acceder a la cuenta contable desde la tabla hija 'accounts' del documento de la categoría
        if withholding_category.accounts:
            # Se usa .account para obtener la cuenta y .description para la descripción
            withholding_account = withholding_category.accounts[0].account
            withholding_description = withholding_category.accounts[0].account
        else:
            frappe.throw("No se encontró la cuenta de retención en la categoría de retención.")

        # 5. Obtener la tasa de retención desde el campo de la Compañía
        company_name = self.company
        withholding_rate = frappe.db.get_value("Company", company_name, "sales_vat_withholding_rate")
        
        # Validar que la tasa de retención exista
        if not withholding_rate:
            frappe.throw("La tasa de retención de IVA para ventas no está configurada en el documento de la Compañía.")

        # Limpiar las retenciones existentes en la factura para evitar duplicados
        self.taxes = [row for row in self.taxes if row.account_head != withholding_account]

        # 6. Encontrar el impuesto de IVA en las filas de la factura
        vat_tax = self.get_iva_tax_row()
        
        # 7. Si se encontró el IVA y existe la tasa de retención, agregar la nueva fila
        if vat_tax and withholding_rate:     
            
            iva_amount = vat_tax.tax_amount
            withholding_amount = flt(iva_amount * withholding_rate / 100.0)

            self.vat_withholding_rate = withholding_rate
            
            self.append("taxes", {
                "charge_type": "VAT Withholding",
                "add_deduct_tax": "Deduct",                
                "account_head": withholding_account,
                "description": withholding_description,
                "rate": withholding_rate,
                "tax_amount": withholding_amount,
            })
            