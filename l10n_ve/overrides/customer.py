import frappe
from frappe import _
from erpnext.selling.doctype.customer.customer import Customer
from l10n_ve.utils.utils import validate_tax_id_format, validate_taxpayer_and_person_type_consistency
from l10n_ve.utils.utils import link_address_to_party


class CustomCustomer(Customer):
    def validate(self):
        super().validate()
        validate_tax_id_format(self)

        if not self.customer_primary_address:
            frappe.throw(_("El campo 'Dirección Principal' es " \
                            "obligatorio. Por favor, ingrese una dirección " \
                            "usando el botón 'Agregar Dirección' en la parte superior derecha"))

    def on_update(self):
        super().on_update()
        if self.customer_primary_address:
            link_address_to_party(self.customer_primary_address, self.doctype, self.name)
        validate_taxpayer_and_person_type_consistency(self)