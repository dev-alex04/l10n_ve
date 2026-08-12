"""
Saneo de la parte fiscal de una copia de producción (l10n_ve).

Lo que apaga acá es la capacidad de consumir correlativos reales: una emisión desde
la copia usaría la serie de la sucursal de verdad y le quemaría números a la
imprenta digital. Y baja TFHKA a ``Demo``, que es la segunda barrera contra emitir
de verdad.

No se ejecuta solo: lo descubre y lo dispara el orquestador de ``domina_core`` vía
el hook ``sandbox_sanitizers``. Igual expone ``dry_run``/``execute`` por si hace
falta correr sólo esta parte.

    bench --site <copia> execute l10n_ve.scripts.sanitize_sandbox.dry_run
"""

import frappe

def _guard():
    """Trae la guarda de saneo desde ``domina_core``, o corta.

    El import es diferido y **falla cerrado** a propósito: la guarda vive en
    ``domina_core`` --la app base-- pero hay sitios con ``l10n_ve`` y sin ella
    (``galanet.black`` al 2026-08-11). Sin poder verificar que el sitio es una copia,
    la única salida segura es no sanear: esos sitios son de producción.

    Diferido y no en el nivel de módulo para que la ausencia de ``domina_core`` no
    rompa la carga de la app entera, sólo el saneo.
    """
    try:
        from domina_core.scripts.sandbox import assert_sandbox, sandbox_status
    except ImportError:
        frappe.throw(
            "El saneo necesita la guarda de sandbox de 'domina_core', que no está "
            "instalada en este sitio. Sin ella no hay forma de verificar que esto es "
            "una copia de trabajo, así que el saneo no procede."
        )
    return assert_sandbox, sandbox_status

#: Serie de pruebas a la que se llevan todas las series fiscales de la copia.
SANDBOX_HKA_SERIES: str = "MAR-05"

#: Entorno al que se lleva el espejo de TFHKA en la copia.
#:
#: OJO: este campo ya NO decide nada. El entorno lo resuelve ``hka_environment`` contra
#: el site_config, que es lo único que no viaja en un ``bench restore``. Acá se pone en
#: ``Demo`` para que el Desk no muestre ``Production`` en una copia, nada más.
#:
#: La barrera de verdad la pone ``_set_hka_environment``: si el site_config de la copia
#: apunta a PRODUCCIÓN, apaga TFHKA. Medido el 2026-08-02: tras restaurar producción en
#: una copia, TFHKA quedó en ``Production`` con el cron de envío andando; lo que salvó
#: al sitio fue que el site_config seguía apuntando al host de demo. Si alguien copia
#: además el site_config, esa línea desaparece y la copia emite de verdad.
SANDBOX_HKA_ENVIRONMENT: str = "Demo"


def run(dry: bool) -> list:
    """Contrato del hook ``sandbox_sanitizers``: devuelve ``[(título, detalle), ...]``.

    La guarda se llama acá y no sólo en el orquestador a propósito: este módulo es
    ejecutable por su cuenta, y un saneo que dependa de que alguien más haya
    chequeado es un saneo sin guarda.
    """
    assert_sandbox, _ = _guard()
    assert_sandbox()
    return [_set_hka_series(dry), _set_hka_environment(dry)]


def _set_hka_series(dry: bool) -> tuple:
    filas: list = frappe.db.sql(
        """SELECT name, serie FROM `tabVE Digital Billing Series`""", as_dict=True
    )
    pendientes: list = [f for f in filas if f.serie != SANDBOX_HKA_SERIES]

    if dry:
        actuales: dict = {}
        for fila in filas:
            actuales[fila.serie] = actuales.get(fila.serie, 0) + 1
        detalle: str = ", ".join(f"{s!r} ({n})" for s, n in sorted(actuales.items()))
        return ("Series fiscales HKA",
                f"{len(filas)} serie(s), {len(pendientes)} por cambiar. Actuales: {detalle}")

    for fila in pendientes:
        frappe.db.set_value(
            "VE Digital Billing Series", fila.name, "serie", SANDBOX_HKA_SERIES,
            update_modified=False,
        )
    return ("Series fiscales HKA",
            f"{len(pendientes)} serie(s) -> {SANDBOX_HKA_SERIES} (de {len(filas)})")


def _set_hka_environment(dry: bool) -> tuple:
    """Alinea el espejo del Desk y, si el site_config apunta a PRODUCCIÓN, apaga TFHKA.

    Normalmente no toca ``enabled``: la copia tiene que poder probar emisión contra el
    ambiente de pruebas, que es para lo que existe. Pero si el site_config quedó
    apuntando a la HKA real, la copia puede emitir documentos fiscales de verdad y eso
    no se puede deshacer, así que ahí sí se apaga. Es lo único que se puede hacer desde
    acá: el site_config es un archivo y el saneo no lo edita.
    """
    from l10n_ve.digital_invoice.hka_environment import inspect as inspect_hka

    if not frappe.db.exists("DocType", "TFHKA Settings"):
        return ("Entorno TFHKA", "TFHKA no está instalado")

    estado: dict = inspect_hka()
    actual: str = frappe.db.get_single_value("TFHKA Settings", "environment") or "(vacío)"
    habilitado: bool = bool(frappe.db.get_single_value("TFHKA Settings", "enabled"))
    apunta_a_produccion: bool = estado["is_production"] is True

    if dry:
        detalle: str = f"site_config: {estado['url'] or 'sin URL'}"
        if estado["problem"]:
            detalle = f"site_config INCOHERENTE — {estado['problem']}"
        elif apunta_a_produccion:
            detalle = (
                f"site_config apunta a PRODUCCIÓN ({estado['url']}): esta copia puede "
                f"emitir de verdad. Se apagará TFHKA (enabled={int(habilitado)})"
            )
        espejo: str = (
            "espejo ya en Demo" if actual == SANDBOX_HKA_ENVIRONMENT
            else f"espejo {actual!r} -> {SANDBOX_HKA_ENVIRONMENT!r}"
        )
        return ("Entorno TFHKA", f"{detalle}; {espejo}")

    cambios: list = []
    if apunta_a_produccion and habilitado:
        frappe.db.set_single_value("TFHKA Settings", "enabled", 0)
        cambios.append(
            f"TFHKA APAGADO: el site_config apunta a producción ({estado['url']})"
        )
    if actual != SANDBOX_HKA_ENVIRONMENT:
        frappe.db.set_single_value("TFHKA Settings", "environment", SANDBOX_HKA_ENVIRONMENT)
        cambios.append(f"espejo {actual!r} -> {SANDBOX_HKA_ENVIRONMENT!r}")

    return ("Entorno TFHKA", "; ".join(cambios) or "sin cambios")


def dry_run() -> None:
    _standalone(dry=True)


def execute() -> None:
    _standalone(dry=False)


def _standalone(dry: bool) -> None:
    modo: str = "DRY-RUN" if dry else "EJECUCIÓN"
    print(f"=== Saneo fiscal de la copia (l10n_ve) — {modo} ===\n")
    assert_sandbox, sandbox_status = _guard()
    assert_sandbox()
    print(f"  {sandbox_status()}\n")
    for titulo, detalle in run(dry):
        print(f"  {titulo:<22} {detalle}")
    if dry:
        print("\n  Nada fue modificado.")
    else:
        frappe.db.commit()
        print("\n  Saneo aplicado.")
