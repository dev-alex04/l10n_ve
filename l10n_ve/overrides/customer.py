import frappe
from frappe import _
from erpnext.selling.doctype.customer.customer import Customer
from l10n_ve.utils.utils import validate_tax_id_format, validate_taxpayer_and_person_type_consistency
from l10n_ve.utils.utils import link_address_to_party


class VECustomer(Customer):
    def validate(self):
        super().validate()

        validate_tax_id_format(self)
        validate_taxpayer_and_person_type_consistency(self)

    def on_update(self):
        super().on_update()

        if self.customer_primary_address:
            link_address_to_party(self.customer_primary_address,
                                  self.doctype,
                                  self.name)

        validate_taxpayer_and_person_type_consistency(self)

    def get_email_list(self) -> list[str]:
        if not self.email_id:
            return []
        return [email.strip() for email in self.email_id.split(",") if email.strip()]

def get_customer_emails(customer_name):
    """
    Busca un cliente por su ID y devuelve la lista de correos.
    """
    doc = frappe.get_doc("Customer", customer_name)
    if hasattr(doc, "get_email_list"):
        return doc.get_email_list()
    
    return VECustomer.get_email_list(doc)
