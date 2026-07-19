import frappe
from frappe import _
from erpnext.buying.doctype.supplier.supplier import Supplier
from l10n_ve.utils.utils import validate_tax_id_format, validate_unique_tax_id, validate_taxpayer_and_person_type_consistency
from l10n_ve.utils.utils import link_address_to_party


class CustomSupplier(Supplier):
    def validate(self):
        super().validate()
        validate_tax_id_format(self)
        validate_unique_tax_id(self)
        validate_taxpayer_and_person_type_consistency(self)

        if not self.supplier_primary_address:
            frappe.throw(_("El campo 'Dirección Principal' es obligatorio. "
                            "Por favor, ingrese una dirección usando el botón "
                            "'Agregar Dirección' en la parte superior derecha"))

        if self.supplier_primary_address:
            if frappe.db.exists("Address", self.supplier_primary_address):
                links: list[dict] = frappe.db.get_all(
                    "Dynamic Link",
                    filters={"parenttype": "Address", "parent": self.supplier_primary_address},
                    fields=["link_doctype", "link_name"]
                )
                other_suppliers: list[str] = [
                    l.get("link_name") for l in links
                    if l.get("link_doctype") == "Supplier" and l.get("link_name") != self.name
                ]
                if other_suppliers:
                    other_supplier_names: list[str] = [
                        frappe.get_cached_value("Supplier", s, "supplier_name") or s
                        for s in other_suppliers
                    ]
                    frappe.throw(
                        _("La dirección seleccionada ya está vinculada a otro proveedor ({0}). "
                          "Por favor, cree una nueva dirección para este proveedor.")
                        .format(", ".join(other_supplier_names)),
                        title=_("Dirección de otro Proveedor")
                    )

    def on_update(self):
        super().on_update()
        if self.supplier_primary_address:
            link_address_to_party(self.supplier_primary_address, self.doctype, self.name)

