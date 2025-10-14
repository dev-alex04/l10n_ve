import frappe
from frappe.utils import nowdate, getdate
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

    def _get_and_format_correlatives(correlative_format, current_correlative_value):
        today = getdate(nowdate())
        current_year = str(today.year)
        current_month = f"{today.month:02d}"

        template = correlative_format or '##############'
        num_digits = len(template) - 6

        if current_correlative_value:
            voucher_correlative_num = int(current_correlative_value)
        else:
            voucher_correlative_num = 1

        next_correlative_num = voucher_correlative_num + 1

        formatted_voucher = str(voucher_correlative_num).zfill(num_digits)

        final_voucher_number = f"{current_year}{current_month}{formatted_voucher}"
        final_next_correlative_number = f"{next_correlative_num}"

        return final_voucher_number, final_next_correlative_number
