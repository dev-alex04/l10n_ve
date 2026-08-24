"""Entorno de HKA: demo o producción. Fuente de verdad, el site_config.json.

Todo el que necesite saber contra qué HKA está hablando el sitio pregunta acá. No se
lee `TFHKA Settings.environment`, que es un espejo informativo y no decide nada: llegó
a haber dos interruptores con cara de "el entorno", y el Desk podía mostrar
`Production` mientras cada factura se iba a demo.

Por qué el site_config y no el DocType: es lo único que NO viaja en un `bench restore`.
Una copia de producción llega con el DocType en `Production` y el cron de envío andando;
lo que la salva es que su site_config sigue apuntando al host de demo. Si la autoridad
viviera en la base de datos, esa red desaparecería justo cuando hace falta.

Estructura esperada::

    "digital_billing_settings": {
        "is_production_mode": 0,
        "demo_url":       "https://demoemisionv2.thefactoryhka.com.ve",
        "production_url": "https://emisionv2.thefactoryhka.com.ve",
        "username":       "...",
        "password":       "..."
    }
"""

from urllib.parse import urlparse

import frappe

#: Clave del site_config.json donde vive todo esto.
CONFIG_KEY: str = "digital_billing_settings"

#: Fragmentos que identifican un host de emisión de PRUEBA. Se comparan contra el
#: netloc, no contra la URL entera, para que un path no dispare un falso positivo.
DEMO_HKA_HOSTS: tuple = ("demoemision", "demo.", "test.", "localhost", "127.0.0.1")

_TITLE: str = "Entorno de Facturación Digital"


def get_config() -> dict:
    """El bloque del site_config, o ``{}`` si no está."""
    return frappe.get_site_config().get(CONFIG_KEY) or {}


def is_demo_host(url: str) -> bool:
    """¿La URL apunta a un host de pruebas de HKA?"""
    parsed = urlparse((url or "").strip())
    host: str = (parsed.netloc or parsed.path or "").lower()
    return any(fragment in host for fragment in DEMO_HKA_HOSTS)


def inspect() -> dict:
    """Estado del entorno **sin lanzar**, para diagnósticos y para el saneo.

    Devuelve ``{"configured", "is_production", "url", "problem"}``. ``problem`` trae el
    mensaje listo para mostrar cuando la configuración no se sostiene, y es ``None``
    cuando el modo y el host se corresponden.
    """
    config: dict = get_config()
    out: dict = {"configured": bool(config), "is_production": None, "url": "", "problem": None}
    if not config:
        return out

    # `is_production_mode` se lee sin adivinar: solo 0/1 (o true/false) sin comillas.
    # Un string se rechaza en vez de interpretarse, porque `"0"` es texto no vacío y
    # hasta acá se leía como PRODUCCIÓN, o sea lo contrario de lo que escribió quien lo
    # puso. Elegir una de las dos lecturas es exactamente lo que no se hace cuando del
    # otro lado hay una emisión fiscal irreversible.
    raw = config.get("is_production_mode", 0)
    if raw is None:
        raw = 0
    if not isinstance(raw, (bool, int)):
        out["problem"] = (
            f"`{CONFIG_KEY}.is_production_mode` del site_config.json vale {raw!r}, que "
            "no es 0 ni 1. Escríbalo como número y sin comillas: un texto como \"0\" se "
            "lee como PRODUCCIÓN, que es lo contrario de lo que parece."
        )
        return out

    is_production: bool = bool(raw)
    url_key: str = "production_url" if is_production else "demo_url"
    url: str = (config.get(url_key) or "").strip().rstrip("/")
    out["is_production"] = is_production
    out["url"] = url

    if not url:
        out["problem"] = f"Falta `{CONFIG_KEY}.{url_key}` en el site_config.json."
    elif is_production and is_demo_host(url):
        out["problem"] = (
            f"El sitio está en modo PRODUCCIÓN pero `{url_key}` apunta a un host de "
            f"pruebas ({url}). Nada se estaría certificando de verdad. Corrija la URL, "
            "o ponga `is_production_mode` en 0 si la intención era emitir en demo."
        )
    elif not is_production and not is_demo_host(url):
        out["problem"] = (
            f"El sitio está en modo DEMO pero `{url_key}` apunta a {url}, que no es un "
            "host de pruebas conocido. Emitir contra él es irreversible, así que no se "
            "envía. Si ese host ES de pruebas, agréguelo a DEMO_HKA_HOSTS en "
            "l10n_ve/digital_invoice/hka_environment.py."
        )
    return out


def resolve_endpoint() -> tuple[bool, str]:
    """``(es_producción, base_url)`` del sitio, ya validado.

    Corta si el modo y el host no se corresponden, en los dos sentidos. Nada validaba el
    contenido de las URLs, así que copiar un site_config entre sitios alcanzaba para
    quedar en modo producción pegándole a demo --los documentos no existen fiscalmente y
    nadie se entera-- o en modo demo pegándole a producción, que es irreversible.
    """
    estado: dict = inspect()
    if not estado["configured"]:
        frappe.throw(
            f"Falta `{CONFIG_KEY}` en el site_config.json.",
            title=_TITLE,
        )
    if estado["problem"]:
        frappe.throw(estado["problem"], title=_TITLE)
    return estado["is_production"], estado["url"]


def is_production() -> bool:
    """¿El sitio emite contra la HKA real?"""
    return resolve_endpoint()[0]


def is_demo() -> bool:
    """¿El sitio emite contra la HKA de pruebas?"""
    return not is_production()


def environment_label() -> str:
    """``Production`` / ``Demo``, con las etiquetas del Select de TFHKA Settings."""
    return "Production" if is_production() else "Demo"


#: Bloque del site_config donde vive el correo de pruebas. NO es `digital_billing_settings`:
#: lo comparte con los avisos de retenciones, que lo leen de acá (ver `tasks.py`).
_SETTINGS_KEY: str = "l10n_ve_settings"


def notification_emails(real: list[str]) -> list[str]:
    """A qué correos se le avisa: los del cliente en producción, el de pruebas si no.

    Se resuelve acá y no en cada llamador para que el payload que se le manda a HKA y
    la vista previa que ve el usuario digan lo mismo. Que diverjan es peor que no
    filtrar: la pantalla asegura que el correo del cliente no sale, y sale igual.

    Sin `test_email` configurado se devuelve la lista vacía: nadie recibe nada. NO se
    corta. Cortar seria fail-closed sobre el papel y en la practica rompe la vista previa
    y la emision de todo sitio de desarrollo y del CI, que no tienen ese valor puesto --y
    para un dato cuyo unico proposito es proteger, "no mandar a nadie" ya es el resultado
    seguro. Queda anotado en el log para que la falta de configuracion se pueda ver.
    """
    estado: dict = inspect()

    # Sin el bloque en el site_config, el sitio no emite a HKA: no hay correo que
    # proteger y tampoco a donde mandarlo. Lista vacia. Cortar aca rompia toda la suite
    # de payload en un sitio recien creado --el del CI-- sin ganar nada.
    if not estado["configured"]:
        return []

    # Ambiguo es distinto de ausente: si no se puede saber si el sitio es de pruebas,
    # tampoco se puede saber si el correo del cliente debe salir. Ahi si se corta.
    if estado["problem"]:
        frappe.throw(estado["problem"], title=_TITLE)

    if estado["is_production"]:
        return list(real or [])

    prueba: str = (
        (frappe.get_site_config().get(_SETTINGS_KEY) or {}).get("test_email") or ""
    ).strip()
    if not prueba:
        if real:
            # `error` y no `info` a proposito. El logger de Frappe arranca con nivel
            # efectivo ERROR, asi que TODO lo de abajo se descarta en silencio y el
            # archivo queda en cero bytes -- medido:
            #
            #     isEnabledFor(INFO)    = False
            #     isEnabledFor(WARNING) = False
            #     isEnabledFor(ERROR)   = True
            #
            # O sea que `warning` tampoco alcanza. Y esto tiene que quedar escrito
            # porque el docstring de arriba apoya la decision de NO cortar justamente
            # en que la falta de configuracion se puede ver despues.
            frappe.logger("l10n_ve").error(
                f"HKA: sitio fuera de produccion sin {_SETTINGS_KEY}.test_email; "
                "el documento sale sin correo en vez de con el del cliente."
            )
        return []
    return [e.strip() for e in prueba.split(",") if e.strip()]
