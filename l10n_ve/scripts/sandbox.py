"""
Guarda de sandbox del ecosistema Domina (l10n_ve).

Vive acá y no en la app que la usa porque ``l10n_ve`` es la más baja del stack
--``domina_isp`` la declara en ``required_apps`` y ``mint`` también-- así que es la
única que todas pueden importar sin ciclo. La regla queda escrita una sola vez:
endurecerla después alcanza a todos los saneos, y ninguna app puede aflojarla por
su cuenta.

Por qué la bandera está en ``site_config.json`` y no en la base
--------------------------------------------------------------
Un ``bench restore`` de producción reemplaza la base entera --incluidos System
Settings y cualquier bandera que hubiéramos dejado ahí-- pero NO toca el
site_config, que es un archivo del sitio. Es la única señal de "esto es una copia"
que sobrevive a la restaura.

Comprobado el 2026-08-02: tras restaurar producción en una copia, TFHKA quedó en
``environment = Production`` y el cron de envío sin detener. Lo que salvó al sitio
fue el site_config, que seguía apuntando al host de demo.

Uso
---
    from l10n_ve.scripts.sandbox import assert_sandbox

    def run(dry: bool) -> list:
        assert_sandbox()
        ...
"""

import frappe
from frappe.utils import cint

#: Clave que el sitio debe declarar en su ``site_config.json`` para admitir el saneo.
#:
#: Es del ecosistema y no de una app: cada app tiene su propio script de saneo --sus
#: credenciales, sus destinos-- y todos consultan esta misma bandera. Si cada una
#: pidiera la suya, habilitar una copia serían N ediciones del site_config y bastaría
#: olvidarse de una para dejar esa app sin sanear sobre datos reales.
SANDBOX_CONFIG_KEY: str = "domina_sandbox"

#: Sitios que nunca se sanean, tengan la bandera que tengan. Segunda barrera por si
#: alguien copia un site_config de una copia a un servidor real.
PRODUCTION_SITES: frozenset = frozenset({
    "domina.galanet",
    "galanet.black",
    "domina.designet",
    "domina.dian",
})

#: Fragmentos que identifican un host de emisión fiscal de PRUEBA.
DEMO_HKA_HOSTS: tuple = ("demoemision", "demo.", "test.", "localhost", "127.0.0.1")


def hka_can_emit_for_real() -> tuple:
    """``(puede_emitir, motivo)`` — si el sitio le puede mandar algo a la HKA real.

    Replica la resolución de URL de ``tfhka_client``: la clave del site_config se
    elige según ``TFHKA Settings.environment``.
    """
    if not frappe.db.exists("DocType", "TFHKA Settings"):
        return False, "TFHKA no está instalado"

    ajustes = frappe.get_single("TFHKA Settings")
    if not cint(getattr(ajustes, "enabled", 0)):
        return False, "TFHKA deshabilitado"

    config: dict = frappe.get_site_config().get("digital_billing_settings") or {}
    es_produccion: bool = (getattr(ajustes, "environment", "") or "") == "Production"
    url: str = str(config.get("production_url" if es_produccion else "demo_url") or "")
    if not url:
        return False, "sin URL configurada"

    minuscula: str = url.lower()
    for host in DEMO_HKA_HOSTS:
        if host in minuscula:
            return False, f"apunta a {url}"
    return True, f"apunta a {url}"


def sandbox_status() -> str:
    """Línea de contexto para el encabezado de un saneo. Asume la guarda ya pasada."""
    _, motivo = hka_can_emit_for_real()
    return f"Sitio: {frappe.local.site}  ·  declarado como copia  ·  HKA: {motivo}"


def assert_sandbox() -> None:
    """Aborta si esto no es, sin lugar a dudas, una copia de trabajo.

    Son tres guardas y hacen falta las tres. Fallan cerrado: ante la duda, no procede.
    """
    sitio: str = frappe.local.site

    if sitio in PRODUCTION_SITES:
        frappe.throw(
            f"'{sitio}' está en la lista de sitios de PRODUCCIÓN. "
            "El saneo no se ejecuta ahí bajo ninguna circunstancia."
        )

    if not cint(frappe.conf.get(SANDBOX_CONFIG_KEY)):
        frappe.throw(
            f"'{sitio}' no está declarado como copia de trabajo.\n\n"
            f"Para habilitarlo, agregá esta clave en "
            f"sites/{sitio}/site_config.json:\n\n"
            f'    "{SANDBOX_CONFIG_KEY}": 1\n\n'
            "La bandera es del ecosistema: la comparten todos los scripts de saneo, "
            "así que declararla una vez habilita el saneo completo de la copia.\n"
            "Va en el site_config y no en la base a propósito: un restore de "
            "producción reemplaza la base entera, pero no toca este archivo."
        )

    puede_emitir, motivo = hka_can_emit_for_real()
    if puede_emitir:
        frappe.throw(
            f"'{sitio}' puede emitir documentos fiscales REALES ({motivo}). "
            "Un sitio con esa capacidad no es una copia de trabajo. "
            "Corregí la URL de 'digital_billing_settings' antes de sanear."
        )
