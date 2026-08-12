# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Resolución del entorno de HKA (``l10n_ve.digital_invoice.hka_environment``).

Contexto: había dos interruptores con cara de "el entorno" --el flag del site_config y
``TFHKA Settings.environment``-- y sólo el primero decidía la URL. El Desk podía decir
`Production` con cada factura yéndose a demo, y nada validaba que la URL correspondiera
al modo. Acá se fija que hay un solo interruptor y que las combinaciones incoherentes
cortan en vez de emitir.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.digital_invoice import hka_environment

DEMO = "https://demoemisionv2.thefactoryhka.com.ve"
PROD = "https://emisionv2.thefactoryhka.com.ve"


def _cfg(**over) -> dict:
    base = {"is_production_mode": 0, "demo_url": DEMO, "production_url": PROD}
    base.update(over)
    return {"digital_billing_settings": base}


class _Base(unittest.TestCase):
    def _resolve(self, **over):
        with patch("frappe.get_site_config", return_value=_cfg(**over)):
            return hka_environment.resolve_endpoint()

    def _problem(self, **over) -> str:
        with patch("frappe.get_site_config", return_value=_cfg(**over)):
            return hka_environment.inspect()["problem"] or ""


class TestResolveEndpoint(_Base):
    def test_demo_mode_uses_demo_url(self):
        self.assertEqual(self._resolve(is_production_mode=0), (False, DEMO))

    def test_production_mode_uses_production_url(self):
        self.assertEqual(self._resolve(is_production_mode=1), (True, PROD))

    def test_trailing_slash_is_dropped(self):
        """La URL se concatena con /api/Emision: una barra de más da //api."""
        _, url = self._resolve(is_production_mode=1, production_url=PROD + "/")
        self.assertEqual(url, PROD)

    def test_missing_flag_is_demo(self):
        cfg = {"digital_billing_settings": {"demo_url": DEMO, "production_url": PROD}}
        with patch("frappe.get_site_config", return_value=cfg):
            self.assertEqual(hka_environment.resolve_endpoint(), (False, DEMO))

    def test_missing_block_throws(self):
        with patch("frappe.get_site_config", return_value={}):
            with self.assertRaises(frappe.ValidationError):
                hka_environment.resolve_endpoint()


class TestCoherenceGuard(_Base):
    """El modo y el host tienen que corresponderse, en los dos sentidos."""

    def test_production_pointing_at_demo_host_throws(self):
        """Copiar un site_config entre sitios alcanzaba para esto: modo producción,
        URL de demo, y ni un documento certificado de verdad."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._resolve(is_production_mode=1, production_url=DEMO)
        self.assertIn("PRODUCCIÓN", str(ctx.exception))

    def test_demo_pointing_at_real_host_throws(self):
        """El caso caro: se cree que es una prueba y la emisión es irreversible."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._resolve(is_production_mode=0, demo_url=PROD)
        self.assertIn("DEMO", str(ctx.exception))

    def test_empty_url_for_the_active_mode_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._resolve(is_production_mode=1, production_url="")

    def test_the_inactive_url_is_not_validated(self):
        """En demo, una production_url rota no molesta: no se va a usar."""
        self.assertEqual(
            self._resolve(is_production_mode=0, production_url="lo que sea"),
            (False, DEMO),
        )


class TestProductionFlagIsNotGuessed(_Base):
    """`"0"` es texto no vacío: con bool() se leía como PRODUCCIÓN."""

    def test_quoted_zero_throws_instead_of_emitting(self):
        problem = self._problem(is_production_mode="0")
        self.assertIn("no es 0 ni 1", problem)

    def test_quoted_one_also_throws(self):
        """No se acepta ni siquiera cuando adivinar acertaría: la regla es una sola."""
        self.assertIn("no es 0 ni 1", self._problem(is_production_mode="1"))

    def test_booleans_are_accepted(self):
        self.assertEqual(self._resolve(is_production_mode=True), (True, PROD))
        self.assertEqual(self._resolve(is_production_mode=False), (False, DEMO))

    def test_null_is_demo(self):
        self.assertEqual(self._resolve(is_production_mode=None), (False, DEMO))


class TestDemoHostDetection(unittest.TestCase):
    def test_known_demo_hosts(self):
        for url in (DEMO, "https://demo.hka.com", "http://localhost:8000",
                    "https://127.0.0.1", "https://test.hka.com"):
            self.assertTrue(hka_environment.is_demo_host(url), url)

    def test_real_host(self):
        self.assertFalse(hka_environment.is_demo_host(PROD))

    def test_path_does_not_trigger_a_false_positive(self):
        """Se mira el host, no la URL entera: un /demo en el path no es un host de demo."""
        self.assertFalse(hka_environment.is_demo_host(PROD + "/api/demo"))


class TestInspectDoesNotThrow(_Base):
    """`inspect` es para diagnóstico y para el saneo: reporta, no corta."""

    def test_incoherent_config_reports_instead_of_raising(self):
        with patch("frappe.get_site_config", return_value=_cfg(is_production_mode=1,
                                                               production_url=DEMO)):
            estado = hka_environment.inspect()
        self.assertTrue(estado["configured"])
        self.assertTrue(estado["is_production"])
        self.assertIn("PRODUCCIÓN", estado["problem"])

    def test_missing_block_reports_not_configured(self):
        with patch("frappe.get_site_config", return_value={}):
            estado = hka_environment.inspect()
        self.assertFalse(estado["configured"])
        self.assertIsNone(estado["problem"])


class TestDocTypeFieldDoesNotDecide(_Base):
    """El campo del Desk es un espejo: contradecirlo no cambia el entorno."""

    def test_environment_field_is_ignored(self):
        settings = frappe._dict(environment="Production")
        with patch("frappe.get_cached_doc", return_value=settings), \
             patch("frappe.get_site_config", return_value=_cfg(is_production_mode=0)):
            self.assertTrue(hka_environment.is_demo())
            self.assertEqual(hka_environment.environment_label(), "Demo")


class TestClientUsesTheResolver(unittest.TestCase):
    """El cliente HKA no resuelve la URL por su cuenta."""

    def _client(self, cfg: dict):
        from l10n_ve.digital_invoice.tfhka_client import TFHKAClient

        client = TFHKAClient()
        with patch("frappe.get_site_config", return_value=cfg), \
             patch("frappe.get_cached_doc", return_value=frappe._dict(enabled=1)):
            client._load_settings()
        return client

    def test_base_url_comes_from_the_resolver(self):
        cfg = _cfg(is_production_mode=1)
        cfg["digital_billing_settings"].update(username="u", password="p")
        self.assertEqual(self._client(cfg).base_url, PROD)

    def test_incoherent_config_blocks_the_client(self):
        cfg = _cfg(is_production_mode=1, production_url=DEMO)
        cfg["digital_billing_settings"].update(username="u", password="p")
        with self.assertRaises(frappe.ValidationError):
            self._client(cfg)


class TestTokenCacheIsPerEnvironment(unittest.TestCase):
    """El token dura una hora y es de UN entorno: la clave lleva la URL adentro.

    Con una clave fija, al cambiar de demo a producción se seguía mandando el token
    viejo a la URL nueva durante 60 minutos, y eso parece un problema de credenciales.
    """

    def test_cache_key_carries_the_url(self):
        import inspect as _inspect

        from l10n_ve.digital_invoice import tfhka_client

        src = _inspect.getsource(tfhka_client.TFHKAClient)
        self.assertNotIn('get_value("tfhka_jwt_token")', src)
        self.assertNotIn('set_value("tfhka_jwt_token"', src)
        self.assertIn("tfhka_jwt_token::", src)


if __name__ == "__main__":
    unittest.main()
