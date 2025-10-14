import frappe
from l10n_ve.utils.utils import get_company_address, get_supplier_address

class WithholdingVoucher():
    def validate_address(self):
        error_messages = []

        company_address = get_company_address(self.empresa)

        if not company_address or not company_address.get('address_line1'):
            error_messages.append("La Empresa debe tener una Dirección Primaria Fiscal asignada.")
        else:
            self.company_address = company_address.get('address_line1')

        supplier_address = get_supplier_address(self.supplier)

        if not supplier_address or not supplier_address.get('address_line1'):
            error_messages.append("El Proveedor debe tener una Dirección Primaria Fiscal asignada.")
        else:
            self.supplier_address = supplier_address.get('address_line1')

        if error_messages:
            list_items = "".join([f"<li>{msg}</li>" for msg in error_messages])

            final_error_message = f"""
                <p>Se encontraron los siguientes errores de validación:</p>
                <ul style="padding-left: 20px;">
                    {list_items}
                </ul>
            """

            frappe.throw(final_error_message)