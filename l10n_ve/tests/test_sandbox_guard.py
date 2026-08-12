# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
La guarda de sandbox de l10n_ve: ¿puede esta copia certificar documentos de verdad?

Es lo que esta app le responde al hook ``sandbox_guards`` de ``domina_core``. La
comprobación vivía dentro de la app base --con los hosts de demo de HKA y la forma de
``digital_billing_settings`` metidos en el núcleo-- y quedó duplicada en dos repos al
mover la guarda de sandbox. Acá se fija que la respuesta salga de ``hka_environment``,
que es donde vive la regla, y que ante una configuración que no se sostiene la guarda
cuente como peligrosa en vez de dejar pasar el saneo.

Un ``bench restore`` de producción deja TFHKA tal cual venía, cron incluido; lo único
que frena a la copia es que su site_config apunte al host de demo.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.scripts.sandbox_guard import check

DEMO = "https://demoemisionv2.thefactoryhka.com.ve"
PROD = "https://emisionv2.thefactoryhka.com.ve"


def _cfg(**over) -> dict:
    base = {"is_production_mode": 0, "demo_url": DEMO, "production_url": PROD}
    base.update(over)
    return {"digital_billing_settings": base}


class TestSandboxGuard(unittest.TestCase):
    def _check(self, config: dict, enabled: int = 1, installed: bool = True) -> tuple:
        with patch("frappe.db.exists", return_value=installed), \
             patch("frappe.db.get_single_value", return_value=enabled), \
             patch("frappe.get_site_config", return_value=config):
            filas = check()
        self.assertEqual(len(filas), 1, "la guarda declara un solo canal")
        return filas[0]

    # ── El canal abierto ──────────────────────────────────────────────────

    def test_production_url_means_it_can_emit(self):
        _, puede, motivo = self._check(_cfg(is_production_mode=1))
        self.assertTrue(puede)
        self.assertIn(PROD, motivo)

    def test_demo_url_is_harmless(self):
        _, puede, motivo = self._check(_cfg(is_production_mode=0))
        self.assertFalse(puede)
        self.assertIn(DEMO, motivo)

    # ── Lo que no se puede comprobar cuenta como peligroso ────────────────

    def test_ambiguous_flag_counts_as_dangerous(self):
        """Un ``"0"`` con comillas: hasta hace poco se leía como producción.

        No se elige una de las dos lecturas a favor del saneo.
        """
        _, puede, motivo = self._check(_cfg(is_production_mode="0"))
        self.assertTrue(puede)
        self.assertIn("ambigua", motivo)

    def test_production_mode_with_demo_url_is_harmless_for_the_copy(self):
        """Incoherente y bloqueado para emitir, pero no puede tocar nada real."""
        _, puede, _ = self._check(_cfg(is_production_mode=1, production_url=DEMO))
        self.assertTrue(puede)

    # ── Nada que consultar ────────────────────────────────────────────────

    def test_disabled_tfhka_is_harmless(self):
        _, puede, motivo = self._check(_cfg(is_production_mode=1), enabled=0)
        self.assertFalse(puede)
        self.assertIn("deshabilitado", motivo)

    def test_uninstalled_tfhka_is_harmless(self):
        _, puede, motivo = self._check(_cfg(), installed=False)
        self.assertFalse(puede)
        self.assertIn("no está instalado", motivo)

    def test_missing_config_block_is_harmless(self):
        _, puede, motivo = self._check({})
        self.assertFalse(puede)
        self.assertIn("digital_billing_settings", motivo)


class TestGuardIsDeclared(unittest.TestCase):
    def test_hook_points_at_this_module(self):
        """Sin la declaración la guarda no existe para el orquestador."""
        import l10n_ve.hooks as hooks

        self.assertEqual(
            hooks.sandbox_guards, ["l10n_ve.scripts.sandbox_guard.check"]
        )


class TestTheRuleLivesInOnePlace(unittest.TestCase):
    """La lista de hosts de demo estaba en dos repos a la vez."""

    def test_the_guard_does_not_keep_its_own_host_list(self):
        import inspect as _inspect

        from l10n_ve.scripts import sandbox_guard

        src = _inspect.getsource(sandbox_guard)
        self.assertNotIn("demoemision", src)
        self.assertIn("hka_environment", src)


class TestProductionMode(unittest.TestCase):
    """Contra el sitio real: una copia con el flag en producción tiene que delatarse."""

    def test_a_site_pointing_at_the_real_hka_is_flagged(self):
        with patch("frappe.db.exists", return_value=True), \
             patch("frappe.db.get_single_value", return_value=1), \
             patch("frappe.get_site_config", return_value=_cfg(is_production_mode=1)):
            canal, puede, _ = check()[0]
        self.assertTrue(puede)
        self.assertIn("HKA", canal)


if __name__ == "__main__":
    unittest.main()
