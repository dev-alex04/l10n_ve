import frappe
from frappe.contacts.doctype.address.address import Address

class CustomAddress(Address):
    def on_update(self):
        self.update_primary_address()

    def update_primary_address(self):
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