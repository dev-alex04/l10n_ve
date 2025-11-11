import frappe
from frappe import _

from erpnext.setup.doctype.company.company import Company

from l10n_ve.utils.utils import validate_tax_id_format, validate_taxpayer_and_person_type_consistency

class CustomCompany(Company):

    def validate(self):
        super().validate()
        validate_tax_id_format(self)
        validate_taxpayer_and_person_type_consistency(self)

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

        self.set_municipality_from_primary_address()

    def set_municipality_from_primary_address(self):
        """
        Establece el campo 'municipality' de la Compañía en función de su
        'custom_company_primary_address'.
        """
        if self.custom_company_primary_address:
            try:
                address_doc = frappe.get_doc("Address",
                                              self.custom_company_primary_address)

                if address_doc.county:
                    self.municipality = address_doc.county
                else:
                    self.municipality = None

            except frappe.DoesNotExistError:

                frappe.log_error(
                    message=f"La dirección principal '{self.custom_company_primary_address}'"
                            f" no fue encontrada para la Compañía '{self.name}'.",
                    title="Error de Vínculo de Dirección en Compañía"
                )
                self.municipality = None
            except Exception as e:

                frappe.log_error(
                    message=f"Error al obtener el municipio desde la dirección '"
                    f"{self.custom_company_primary_address}' para la Compañía '{self.name}': {e}",
                    title="Error de Actualización de Municipio en Compañía"
                )
                self.municipality = None
        else:
            self.municipality = None
