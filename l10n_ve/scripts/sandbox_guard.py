"""Guarda de sandbox de ``l10n_ve``: la emisión fiscal contra HKA.

Contrato del hook ``sandbox_guards`` (ver ``domina_core.scripts.sandbox``)::

    def check() -> list:   # -> [(canal, puede_actuar, motivo), ...]

Esta comprobación vivía dentro de ``domina_core``, con los hosts de demo de The Factory
y la forma de ``digital_billing_settings`` metidos en la app base. Llegó ahí de arrastre
al mover la guarda de sandbox desde acá para arreglar una dependencia invertida, y dejó
la lista de hosts duplicada en dos repos --dos copias de una regla que protege una
emisión irreversible--. Ahora la regla vive en un solo lado, ``hka_environment``, y esto
es apenas su traducción al contrato del hook.

Un ``bench restore`` de producción deja ``TFHKA Settings`` tal cual venía, cron de envío
incluido; lo único que puede impedir que la copia certifique documentos de verdad es que
su site_config apunte al host de demo. Eso es lo que se comprueba.
"""

import frappe
from frappe.utils import cint

from l10n_ve.digital_invoice import hka_environment

_CANAL: str = "emisión fiscal (HKA)"


def check() -> list:
    """¿Puede este sitio certificar documentos fiscales de verdad?"""
    if not frappe.db.exists("DocType", "TFHKA Settings"):
        return [(_CANAL, False, "TFHKA no está instalado")]

    if not cint(frappe.db.get_single_value("TFHKA Settings", "enabled")):
        return [(_CANAL, False, "TFHKA deshabilitado")]

    estado: dict = hka_environment.inspect()
    if not estado["configured"]:
        return [(_CANAL, False, "sin digital_billing_settings")]

    # Una configuración que no se sostiene no se interpreta a favor: si no se puede
    # decir con certeza a dónde apunta el sitio, cuenta como que apunta a producción.
    if estado["problem"]:
        return [(_CANAL, True, f"configuración ambigua — {estado['problem']}")]

    url: str = estado["url"]
    if hka_environment.is_demo_host(url):
        return [(_CANAL, False, f"apunta a {url}")]
    return [(_CANAL, True, f"apunta a {url}")]
