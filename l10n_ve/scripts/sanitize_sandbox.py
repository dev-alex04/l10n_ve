"""
Saneo de la parte fiscal de una copia de producción (l10n_ve).

Lo que apaga acá es la capacidad de consumir correlativos reales: una emisión desde
la copia usaría la serie de la sucursal de verdad y le quemaría números a la
imprenta digital.

No se ejecuta solo: lo descubre y lo dispara el orquestador de ``domina_core`` vía
el hook ``sandbox_sanitizers``. Igual expone ``dry_run``/``execute`` por si hace
falta correr sólo esta parte.

    bench --site <copia> execute l10n_ve.scripts.sanitize_sandbox.dry_run
"""

import frappe

from l10n_ve.scripts.sandbox import assert_sandbox, sandbox_status

#: Serie de pruebas a la que se llevan todas las series fiscales de la copia.
SANDBOX_HKA_SERIES: str = "MAR-05"


def run(dry: bool) -> list:
    """Contrato del hook ``sandbox_sanitizers``: devuelve ``[(título, detalle), ...]``.

    La guarda se llama acá y no sólo en el orquestador a propósito: este módulo es
    ejecutable por su cuenta, y un saneo que dependa de que alguien más haya
    chequeado es un saneo sin guarda.
    """
    assert_sandbox()
    return [_set_hka_series(dry)]


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


def dry_run() -> None:
    _standalone(dry=True)


def execute() -> None:
    _standalone(dry=False)


def _standalone(dry: bool) -> None:
    modo: str = "DRY-RUN" if dry else "EJECUCIÓN"
    print(f"=== Saneo fiscal de la copia (l10n_ve) — {modo} ===\n")
    assert_sandbox()
    print(f"  {sandbox_status()}\n")
    for titulo, detalle in run(dry):
        print(f"  {titulo:<22} {detalle}")
    if dry:
        print("\n  Nada fue modificado.")
    else:
        frappe.db.commit()
        print("\n  Saneo aplicado.")
