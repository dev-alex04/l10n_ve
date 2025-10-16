import frappe
import re
from erpnext.setup.doctype.company.company import Company
from frappe import _

class CustomCompany(Company):

    def validate(self):
        super().validate()
        self.validate_rif()

    def get_invoice_number(self) -> str:
        invoice_format = self.sales_invoice_number_format or "#####"
        next_invoice_num = self.sales_invoice_number_correlative or 1
        return self.format_number(invoice_format, next_invoice_num)

    def get_credit_note_number(self) -> str:
        credit_note_format = self.sales_credit_note_number_format or "#####"
        next_credit_note_num = self.sales_credit_note_number_correlative or 1
        return self.format_number(credit_note_format, next_credit_note_num)

    def get_debit_note_number(self) -> str:
        debit_note_format = self.sales_debit_note_number_format or "#####"
        next_debit_note_num = self.sales_debit_note_number_correlative or 1
        return self.format_number(debit_note_format, next_debit_note_num)

    def get_control_number(self) -> str:
        control_format = self.sales_invoice_control_number_format or "#####"
        next_control_num = self.sales_invoice_control_number_correlative or 1
        return self.format_number(control_format, next_control_num)


    def increment_invoice_number(self):
        next_invoice = (self.sales_invoice_number_correlative or 1) + 1
        frappe.db.set_value("Company",
                            self.name,
                            "sales_invoice_number_correlative",
                            next_invoice)

    def increment_credit_note_number(self):
        next_credit_note = (self.sales_credit_note_number_correlative or 1) + 1
        frappe.db.set_value("Company",
                            self.name,
                            "sales_credit_note_number_correlative",
                            next_credit_note)

    def increment_debit_note_number(self):
        next_debit_note = (self.sales_debit_note_number_correlative or 1) + 1
        frappe.db.set_value("Company",
                            self.name,
                            "sales_debit_note_number_correlative",
                            next_debit_note)

    def increment_control_number(self):
        next_control = (self.sales_invoice_control_number_correlative or 1) + 1
        frappe.db.set_value("Company",
                            self.name,
                            "sales_invoice_control_number_correlative",
                            next_control)
        frappe.db.commit()

    def format_number(self, number_format: str | None, number: int) -> str:
        """
        Función de utilidad para aplicar el formato al número.
        """
        # Asegura que number_format no sea None
        number_format = number_format or ""

        if '#' not in number_format:
            return f"{number_format}{number}"

        num_placeholders = number_format.count('#')
        formatted_number = str(number).zfill(num_placeholders)

        return number_format.replace('#' * num_placeholders, formatted_number)

    def before_save(self):
        
        if not self.vat_withholding_format:
        
            self.vat_withholding_format = "##############"

        if not self.vat_withholding_correlative:
            self.vat_withholding_correlative = 1

    def validate_rif(self):
        """Valida el formato del RIF en el campo tax_id."""
        if not self.tax_id:
            return

        cleaned_rif = re.sub(r'[^a-zA-Z0-9]', '', self.tax_id).upper()

        self.tax_id = cleaned_rif

        rif_regex = r"^[VEJG]\d{9}$"
        if not re.match(rif_regex, cleaned_rif):
            frappe.throw(_("El RIF/ID de Impuesto '{0}' no es válido. " \
            "El formato debe ser una letra seguida de 9 dígitos (ej: J123456789).").format(self.tax_id))
