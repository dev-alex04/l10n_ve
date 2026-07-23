from frappe import _


def get_data() -> dict:
    """Conexiones del dashboard de VE Purchase Debit Note.

    Muestra los comprobantes de retención IVA e ISLR generados desde esta ND.
    El campo de enlace es 'purchase_invoice' en los child tables de ambos comprobantes,
    que almacena el name del documento origen (la Nota de Débito en este caso).
    """
    return {
        "fieldname": "purchase_invoice",
        "transactions": [
            {
                "label": _("Retenciones"),
                "items": ["VAT Withholding Voucher", "ISLR Withholding Voucher"],
            },
        ],
    }
