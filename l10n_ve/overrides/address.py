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

        if self.links and len(self.links) > 0:
            link_row = self.links[0]

            try:
                link_doctype = link_row.link_doctype
                link_name = link_row.link_name

                if link_doctype in primary_address_field and link_name:
                    link_field_name = primary_address_field[link_doctype]

                    company_doc = frappe.get_doc(link_doctype, link_name)
                    current_primary = company_doc.get(link_field_name)

                    if not current_primary or current_primary == self.name:
                        company_doc.set(link_field_name, self.name)
                        company_doc.save(ignore_permissions=True, ignore_version=True)

            except AttributeError:
                frappe.log_error(
                    f"La fila de vínculo no tiene los atributos link_doctype o link_name. Fila: {link_row.as_dict()}",
                )
        else:
            frappe.log_error(f"La dirección {self.name} no está vinculada a ninguna entidad.", "Dirección Principal: Sin Vínculos")