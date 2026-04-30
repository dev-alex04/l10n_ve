import frappe
from frappe import _
from frappe.utils import nowdate, getdate
from l10n_ve.utils.utils import get_company_address, get_supplier_address


class WithholdingVoucher():
    def validate_address(self) -> None:
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

    @frappe.whitelist()
    def mark_as_declared(self) -> bool:
        """Marca un comprobante como declarado ante el SENIAT."""
        if self.docstatus != 1:
            frappe.throw(
                _("Solo se pueden marcar como declarados los comprobantes "
                  "que estén en estado Aprobado.")
            )
        self.db_set("is_declared", 1)
        return True

    @frappe.whitelist()
    def get_withholding_correlative(self, company_name, voucher_type) -> dict:

        if not company_name:
            return {}

        company_doc = frappe.get_cached_doc("Company", company_name)

        format_field = f"{voucher_type}_withholding_format"
        correlative_field = f"{voucher_type}_withholding_correlative"

        correlative_format = company_doc.get(format_field)
        current_correlative = company_doc.get(correlative_field)

        final_voucher_number, _, year, month = (
            self._get_and_format_correlatives(
                correlative_format,
                current_correlative))

        return {
            "voucher_number": final_voucher_number,
            "year": year,
            "month": month
        }

    def _get_and_format_correlatives(self,
                                     correlative_format: str,
                                     current_correlative_value):

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

        return final_voucher_number, final_next_correlative_number, current_year, current_month

