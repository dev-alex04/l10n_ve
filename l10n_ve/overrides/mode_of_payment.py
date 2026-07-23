import frappe
from frappe import _


def validate_mode_of_payment(doc, method=None) -> None:
    """Un modo de pago de tipo Efectivo (Cash) no puede ser público.

    Un modo público queda disponible de cara al cliente (por ejemplo, en el
    portal). Los modos de tipo Cash se dan por conciliados sin exigir un depósito
    bancario que los respalde, así que exponerlos como públicos permitiría
    registrar cobros sin entrada real en banco. Por eso se obliga a que cualquier
    modo Cash sea privado.
    """
    if doc.type == "Cash" and doc.get("visibility_type") == "Public":
        frappe.throw(
            _(
                "Un modo de pago de tipo Efectivo (Cash) no puede ser público. "
                "Cámbielo a Privado o use un tipo Banco."
            ),
            title=_("Modo de pago inválido"),
        )
