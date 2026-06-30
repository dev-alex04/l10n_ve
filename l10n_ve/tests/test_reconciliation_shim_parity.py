# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Test de paridad del shim de conciliación (MINT-03).

El shim `l10n_ve.overrides.payment_reconciliation` re-exporta los símbolos de
`mint.apis.reconciliation` y, si mint no está disponible, cae a un bloque
`except ImportError` con literales propios. Esos literales DEBEN coincidir
exactamente con los de mint, porque son los valores del Select
`custom_reconciliation_status` (opciones en español). Un literal divergente
nunca casaría contra la BD (estados fantasma).

Este test fuerza la rama de fallback (simulando que mint no está instalado) y
verifica que las 8 constantes del fallback igualan a las de mint.
"""

import builtins
import importlib.util
import os
import unittest

import l10n_ve.overrides.payment_reconciliation as shim_module

_CONSTANTS = [
    "RECON_PENDING",
    "RECON_DONE",
    "RECON_REVIEW",
    "REVIEW_OTHER_BANK",
    "REVIEW_DUPLICATE_REFERENCE",
    "CASH_LIKE_TYPES",
    "DEPOSIT_COVERAGE_TOLERANCE",
    "DEPOSIT_FIELDS",
]


def _load_shim_fallback():
    """Carga el shim forzando el `except ImportError` (mint no disponible)."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mint.apis.reconciliation" or name.startswith("mint.apis.reconciliation"):
            raise ImportError("forced: mint no disponible para el test de paridad")
        return real_import(name, *args, **kwargs)

    path = shim_module.__file__
    spec = importlib.util.spec_from_file_location("_shim_fallback_under_test", path)
    mod = importlib.util.module_from_spec(spec)

    original = builtins.__import__
    builtins.__import__ = fake_import
    try:
        spec.loader.exec_module(mod)
    finally:
        builtins.__import__ = original
    return mod


class TestReconciliationShimParity(unittest.TestCase):
    def test_fallback_constants_match_mint(self):
        """Los literales del fallback igualan a los de mint.apis.reconciliation."""
        try:
            from mint.apis import reconciliation as mint_recon
        except ImportError:
            self.skipTest("mint no está instalado en el bench; no hay fuente de verdad que comparar")

        fallback = _load_shim_fallback()
        for const in _CONSTANTS:
            self.assertEqual(
                getattr(fallback, const),
                getattr(mint_recon, const),
                f"Divergencia en {const}: fallback={getattr(fallback, const)!r} "
                f"vs mint={getattr(mint_recon, const)!r}",
            )

    def test_fallback_branch_actually_exercised(self):
        """Sanidad: el módulo cargado tomó la rama de fallback, no el import real."""
        fallback = _load_shim_fallback()
        # En el fallback, deposit_covers_payment es la lambda no-op (-> None); en el
        # import real sería la función de mint. Esto distingue la rama tomada.
        self.assertIsNone(fallback.deposit_covers_payment("x", "y"))


if __name__ == "__main__":
    unittest.main()
