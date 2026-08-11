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

#: Entorno al que se lleva TFHKA en la copia.
#:
#: Es una SEGUNDA barrera, no la principal. La resolución de la URL en ``tfhka_client``
#: elige la clave del site_config según este campo, así que con ``Demo`` la copia apunta
#: a ``demo_url`` aunque alguien haya dejado una ``production_url`` real.
#:
#: La barrera principal sigue siendo el site_config, porque es lo único que sobrevive a
#: un ``bench restore``. Pero es una sola línea: medido el 2026-08-02, tras restaurar
#: producción en una copia TFHKA quedó en ``Production`` y el cron de envío sin detener;
#: lo que salvó al sitio fue que el site_config seguía apuntando al host de demo. Si
#: alguien copia además el site_config, esa línea desaparece y la copia emite de verdad.
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
    """Baja TFHKA a Demo. No toca ``enabled``: la copia tiene que poder probar
    emisión contra el ambiente de pruebas, que es para lo que existe."""
    if not frappe.db.exists("DocType", "TFHKA Settings"):
        return ("Entorno TFHKA", "TFHKA no está instalado")

    actual: str = frappe.db.get_single_value("TFHKA Settings", "environment") or "(vacío)"

    if dry:
        if actual == SANDBOX_HKA_ENVIRONMENT:
            return ("Entorno TFHKA", f"ya está en {SANDBOX_HKA_ENVIRONMENT!r}")
        return ("Entorno TFHKA", f"{actual!r}, por cambiar a {SANDBOX_HKA_ENVIRONMENT!r}")

    if actual == SANDBOX_HKA_ENVIRONMENT:
        return ("Entorno TFHKA", f"sin cambios, ya estaba en {SANDBOX_HKA_ENVIRONMENT!r}")

    frappe.db.set_single_value("TFHKA Settings", "environment", SANDBOX_HKA_ENVIRONMENT)
    return ("Entorno TFHKA", f"{actual!r} -> {SANDBOX_HKA_ENVIRONMENT!r}")


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
