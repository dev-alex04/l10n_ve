# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""El inlineado de CSS del PDF no puede leer fuera de `sites/assets`.

Regresion: `_sanitize_html_for_wkhtmltopdf` incrusta las hojas de estilo del HTML antes
de mandarlo a wkhtmltopdf. La guarda era `clean_href.startswith("/assets/")`, medida
sobre el TEXTO del href, y `os.path.join` no normaliza. Un href de la forma
``/assets/../../../../../etc/passwd`` la pasaba y terminaba leyendo fuera del bench; el
contenido volvia embebido en un ``<style>`` dentro del PDF, o sea que el archivo se le
entregaba a quien descargara el documento. Alcanzaba `/etc/passwd`, el
`site_config.json` del sitio --con `db_password` y `encryption_key`-- y `~/.ssh/id_rsa`.

Pesa mas de lo que parece porque `monkey_patches.py` reemplaza `report_to_pdf`
GLOBALMENTE: alcanza toda impresion de PDF del sitio, no un reporte puntual.

Los dos sentidos importan y por eso van juntos: el arreglo original usaba `realpath` y
bloqueaba tambien el CSS legitimo, porque cada `sites/assets/<app>` es un symlink al
`public/` de esa app y resolverlo saca la ruta del directorio. Un test que solo probara
el ataque habria dado verde con las hojas de estilo rotas.
"""

import os
import unittest

import frappe

from l10n_ve.utils.pdf_utils import _sanitize_html_for_wkhtmltopdf


def _link(href: str) -> str:
    return f'<link rel="stylesheet" href="{href}">'


class TestElCssDelPdfNoSaleDeAssets(unittest.TestCase):
    def test_no_lee_un_archivo_del_sistema(self):
        salida = _sanitize_html_for_wkhtmltopdf(_link("/assets/../../../../../etc/passwd"))
        self.assertNotIn("root:x:", salida, "el contenido de /etc/passwd entro al PDF")
        self.assertNotIn("<style>", salida)

    def test_no_lee_el_site_config(self):
        ruta = "/assets/../" + frappe.local.site + "/site_config.json"
        salida = _sanitize_html_for_wkhtmltopdf(_link(ruta))
        for secreto in ("db_password", "encryption_key", "db_name"):
            self.assertNotIn(secreto, salida, f"{secreto} entro al PDF")

    def test_no_lee_una_clave_privada(self):
        salida = _sanitize_html_for_wkhtmltopdf(_link("/assets/../../../../../../root/.ssh/id_rsa"))
        self.assertNotIn("PRIVATE KEY", salida)
        self.assertNotIn("<style>", salida)

    def test_el_css_legitimo_sigue_entrando(self):
        """Sin esto, un arreglo que bloquee TODO pasaria los tres tests de arriba."""
        base = os.path.join(frappe.local.sites_path, "assets")
        real = None
        for app in sorted(os.listdir(base)):
            d = os.path.join(base, app, "css")
            if os.path.isdir(d):
                for f in sorted(os.listdir(d)):
                    if f.endswith(".css") and os.path.getsize(os.path.join(d, f)) > 0:
                        real = f"/assets/{app}/css/{f}"
                        break
            if real:
                break
        if not real:
            self.skipTest("no hay ningun css compilado en sites/assets")

        salida = _sanitize_html_for_wkhtmltopdf(_link(real))
        self.assertIn("<style>", salida, f"se bloqueo una hoja de estilo legitima: {real}")
        self.assertNotIn("<link", salida, "el <link> deberia haberse reemplazado por el <style>")

    def test_un_solo_nivel_no_se_cuela_por_el_symlink(self):
        """`sites/assets/<app>` es un symlink al `public/` de la app, o sea que su ruta
        REAL esta un nivel mas profunda que su posicion lexica. Con eso,
        `/assets/l10n_ve/../hooks.py` normaliza a `sites/assets/hooks.py` --que esta
        adentro y pasa la guarda-- pero un `open()` sin normalizar sigue el symlink y
        lee `apps/l10n_ve/l10n_ve/hooks.py`: el paquete de la app, no su `public/`.
        Con dos `..` ya se rechazaba; este es el escape de un solo nivel.
        """
        salida = _sanitize_html_for_wkhtmltopdf(_link("/assets/l10n_ve/../hooks.py"))
        self.assertNotIn("app_name", salida, "se leyo el hooks.py de la app")
        self.assertNotIn("<style>", salida)

    def test_un_prefijo_parecido_no_alcanza(self):
        """`sites/assets-evil/` comparte prefijo con `sites/assets` pero no es lo mismo."""
        salida = _sanitize_html_for_wkhtmltopdf(_link("/assets../secreto.css"))
        self.assertNotIn("<style>", salida)
