# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Los JS y CSS globales de l10n_ve (`app_include_js` / `app_include_css`) llevan la versión
de la app en la URL.

nginx sirve /assets/* con un año de caché y Frappe solo versiona la URL de los
`*.bundle.*`: con una ruta fija, quien ya abrió el Desk sigue con el archivo viejo
después de un deploy hasta que haga Ctrl+Shift+R. Pasó con los filtros Desde/Hasta de
Cuentas por Pagar (#714): estaban en producción y no se veían.

También se exige que cada ruta exista: una ruta mal escrita es un 404 mudo en el Desk.
"""

import os
import unittest

import l10n_ve
from l10n_ve import hooks

PUBLIC_DIR = os.path.join(os.path.dirname(l10n_ve.__file__), "public")
URL_PREFIX = "/assets/l10n_ve/"


def global_assets() -> list[str]:
    return [*hooks.app_include_js, *hooks.app_include_css]


class TestGlobalAssetsVersioned(unittest.TestCase):
    def test_app_version_is_usable_in_a_url(self):
        self.assertRegex(l10n_ve.__version__, r"^v?\d+\.\d+\.\d+$")

    def test_every_global_asset_carries_the_app_version(self):
        expected_query = "v=" + l10n_ve.__version__.lstrip("v")
        for url in global_assets():
            with self.subTest(url=url):
                self.assertEqual(url.partition("?")[2], expected_query)

    def test_every_global_asset_exists(self):
        for url in global_assets():
            path = url.partition("?")[0]
            with self.subTest(url=url):
                self.assertTrue(path.startswith(URL_PREFIX))
                self.assertTrue(
                    os.path.isfile(
                        os.path.join(PUBLIC_DIR, path.removeprefix(URL_PREFIX))
                    )
                )
