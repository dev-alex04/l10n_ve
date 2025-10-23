import re
import frappe
from frappe import _
from frappe.contacts.doctype.address.address import Address

class CustomAddress(Address):
    def validate(self):
        super().validate()
        self.validate_phone_format()
        self.validate_address()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_primary_address()

    def update_primary_address(self) -> None:
        primary_address_field = {
            "Company": "custom_company_primary_address",
            "Supplier": "supplier_primary_address",
            "Customer": "customer_primary_address",
        }

        if not self.links:
            return

        for link_row in self.links:
            try:
                link_doctype = link_row.link_doctype
                link_name = link_row.link_name

                if link_doctype in primary_address_field and link_name:
                    link_field_name = primary_address_field[link_doctype]

                    linked_doc = frappe.get_doc(link_doctype, link_name)

                    if not linked_doc.get(link_field_name):
                        linked_doc.set(link_field_name, self.name)
                        linked_doc.save(ignore_permissions=True, ignore_version=True)

            except (AttributeError, frappe.DoesNotExistError) as e:
                frappe.log_error(
                    message=f"Error al procesar el vínculo de la dirección: {link_row.as_dict()}. Error: {e}",
                    title="Error al actualizar la dirección principal"
                )

    def validate_phone_format(self) -> None:
        phone = self.phone

        if phone:
            if not re.match(r'^[0-9]+$', phone):
                frappe.throw(_("El campo Teléfono solo puede contener números (0-9)."))

            if len(phone) != 11:
                frappe.throw(_("El número de teléfono debe tener exactamente 11 dígitos."))

    def validate_address(self) -> None:
        links = self.links

        if links and len(links) > 0:
            self.address_title = links[0].link_name
        elif self.address_line1:
            self.address_title = self.address_line1
        else:
            self.address_title = "Nueva Dirección"
