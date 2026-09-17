import frappe
from frappe import _
from frappe.utils import getdate, nowdate
from l10n_ve import numbering
from l10n_ve.utils.utils import get_company_address, get_supplier_address


class WithholdingVoucher():
    """Mixin base para comprobantes de retención (IVA e ISLR).

    Provee lógica compartida de direcciones, correlativos y estado declarado.
    """

    PURCHASE_PARENTTYPES: list[str] = [
        "Purchase Invoice",
        "VE Purchase Credit Note",
        "VE Purchase Debit Note",
    ]

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
        frappe.has_permission(self.doctype, "write", doc=self, throw=True)

        if self.docstatus != 1:
            frappe.throw(
                _("Solo se pueden marcar como declarados los comprobantes "
                  "que estén en estado Aprobado.")
            )
        self.db_set("is_declared", 1)
        return True

    @frappe.whitelist()
    def get_withholding_correlative(self, company_name: str, voucher_type: str) -> dict:
        """Vista previa del próximo número de comprobante. MIRA, no toma.

        El número de verdad lo toma `l10n_ve.numbering.take_withholding_number` al insertar
        el comprobante, con la fila de la empresa bloqueada. Acá solo se formatea lo que hay
        para enseñarlo en el formulario.
        """
        if not company_name:
            return {}

        company_doc = frappe.get_cached_doc("Company", company_name)

        correlative_format = company_doc.get(f"{voucher_type}_withholding_format")
        current_correlative = company_doc.get(f"{voucher_type}_withholding_correlative")

        correlative: int = numbering.parse_withholding_counter(current_correlative, correlative_format)
        today = getdate(nowdate())

        return {
            "voucher_number": numbering.format_withholding_number(correlative_format, correlative),
            "year": str(today.year),
            "month": f"{today.month:02d}",
        }

