import re
from contextlib import contextmanager
import frappe
from frappe import _
from frappe.contacts.doctype.address.address import Address

@contextmanager
def ignore_permissions():
    """
    Gestor de contexto para ejecutar un bloque de código ignorando temporalmente los permisos.
    """
    old_flag = frappe.flags.ignore_permissions
    frappe.flags.ignore_permissions = True
    try:
        yield
    finally:
        frappe.flags.ignore_permissions = old_flag

class CustomAddress(Address):
    def validate(self):
        super().validate()
        self.validate_phone_format()
        self.validate_unique_address_link()
        self.validate_address()
        self.prevent_unlinking()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_primary_address()
        self.update_company_municipality()

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

                    with ignore_permissions():
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
            # Limpiar símbolos decorativos para la validación
            clean_phone = re.sub(r'[\s\-()]', '', phone)

            if not re.match(r'^\+?\d{10,15}$', clean_phone):
                frappe.throw(_("El número de teléfono debe contener entre 10 y 15 dígitos y solo puede incluir símbolos como (), -, espacios o el signo '+' al principio."))

            # Normalizar para prefijos venezolanos (convertir +58 o 58 a 0)
            normalized = clean_phone
            if normalized.startswith("+58"):
                normalized = "0" + normalized[3:]
            elif normalized.startswith("58") and len(normalized) > 10:
                normalized = "0" + normalized[2:]

            if normalized.startswith("04") and len(normalized) != 11:
                frappe.throw(_("Los números de celular venezolanos (04xx) deben tener exactamente 11 dígitos (ej. 04141234567 o +58 414 123 45 67)."))

            if normalized.startswith("02") and len(normalized) < 10:
                frappe.throw(_("Los números locales (02xx) deben tener al menos 10 dígitos."))

    def validate_address(self) -> None:
        links = self.links

        if links and len(links) > 0:
            self.address_title = links[0].link_name
        elif self.address_line1:
            self.address_title = self.address_line1
        else:
            self.address_title = "Nueva Dirección"

    def validate_unique_address_link(self) -> None:
        """
        Valida que un Cliente, Proveedor o Compañía solo pueda tener una dirección principal.
        """
        primary_address_field_map = {
            "Customer": "customer_primary_address",
            "Supplier": "supplier_primary_address",
            "Company": "custom_company_primary_address",
        }

        if not self.links:
            return

        for link in self.links:
            doctype = link.link_doctype
            docname = link.link_name

            if doctype not in primary_address_field_map:
                continue

            field = primary_address_field_map[doctype]
            
            with ignore_permissions():
                existing_address = frappe.db.get_value(doctype, docname, field)

            if existing_address and existing_address != self.name:

                message = _("El {0} '{1}' ya tiene una dirección principal asignada. Solo se permite una " 
                            "dirección. Por favor, edite la dirección " 
                            "existente si desea cambiarla.").format(_(doctype), docname)
                
                frappe.throw(message, title=_("Dirección Duplicada"))

    def prevent_unlinking(self) -> None:
        """
        Evita que un usuario desvincule una dirección de una entidad desde
        el formulario de Dirección.
        """
        if self.is_new():
            return

        doc_before_save = self.get_doc_before_save()
        if not doc_before_save:
            return

        old_links = {(link.link_doctype, link.link_name) for link in doc_before_save.links}
        current_links = {(link.link_doctype, link.link_name) for link in self.links}

        if current_links < old_links:
            removed_links = old_links - current_links
            removed_link_details = ", ".join([f"{_(doctype)} '{docname}'" for doctype, docname in removed_links])

            message = _("No se permite desvincular una dirección de una entidad ({0}). "
                        "Si la dirección ya no es necesaria, debe eliminar la entidad " \
                        "principal.").format(removed_link_details)
            
            frappe.throw(message, title=_("Acción no permitida"))

    def update_company_municipality(self) -> None:
        """
        Si la dirección está vinculada a una Compañía, actualiza el campo
        'municipality' de la Compañía con el valor del campo 'county' de la dirección.
        """
        if not self.links:
            return

        for link in self.links:
            if link.link_doctype == "Company":
                try:
                    company_doc = frappe.get_doc("Company", link.link_name)
                    if company_doc.municipality != self.county:
                        company_doc.municipality = self.county
                        company_doc.save(ignore_permissions=True, ignore_version=True)
                        frappe.msgprint(_("El municipio de la compañía {0} ha sido actualizado " \
                                          "a {1}.").format(frappe.bold(link.link_name), frappe.bold(self.county)))
                        
                except frappe.DoesNotExistError:
                    frappe.log_error(f"Compañía '{link.link_name}' no encontrada " 
                                     f"al intentar actualizar el municipio desde la dirección '{self.name}'.")
                    
                except Exception as e:
                    frappe.log_error(f"Error actualizando el municipio para la compañía '{link.link_name}': {e}")


@frappe.whitelist()
def get_address_link_count(link_doctype, link_name) -> int:
    """
    Cuenta los enlaces dinámicos para una dirección específica,
    ignorando los permisos para evitar errores.
    """
    with ignore_permissions():
        count = frappe.db.get_value('Dynamic Link', {
        'parenttype': 'Address',
        'link_doctype': link_doctype,
        'link_name': link_name
        }, "count(*)")

    return count
