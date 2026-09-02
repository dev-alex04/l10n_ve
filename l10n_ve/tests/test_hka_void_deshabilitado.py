# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""La anulación directa ante HKA está cerrada, y no solo en la pantalla.

HKA dejó de aceptar la anulación de facturas el 01-sep-2026 (Providencia
SNAT/2024/000121). El front ya no muestra el botón --`HKA_DIRECT_VOID_ENABLED`
en `sales_invoice.js`--, pero `void_sales_invoice` está `@frappe.whitelist()`:
sigue siendo alcanzable por API, o por un navegador con el bundle viejo cacheado.

Cerrar solo la UI deja la puerta puesta y sin llave. Estos tests fijan que la
guarda vive en el servidor y que corta ANTES de cargar el documento: si algún día
alguien mueve el `frappe.throw` debajo del `get_doc`, la primera línea de la
anulación volvería a ejecutarse contra una factura real.

Corren sin site, con `frappe` parcheado.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.overrides.sales_invoice import HKA_DIRECT_VOID_ENABLED, void_sales_invoice

MOD = "l10n_ve.overrides.sales_invoice"

ARGS = {
    "docname": "ACC-SINV-2026-20335",
    "reason": "prueba",
    "void_date": "01/09/2026",
    "void_time": "10:00:00",
}


class TestAnulacionDirectaCerrada(unittest.TestCase):
    def test_la_bandera_esta_apagada(self) -> None:
        """Si alguien la enciende sin que HKA lo habilite, las anulaciones fallan contra el proveedor."""
        self.assertFalse(HKA_DIRECT_VOID_ENABLED)

    def test_el_endpoint_no_deja_pasar(self) -> None:
        with self.assertRaises(frappe.ValidationError):
            void_sales_invoice(**ARGS)

    def test_corta_antes_de_tocar_el_documento(self) -> None:
        """La guarda va primero: no se carga la factura ni se habla con HKA.

        Es la diferencia entre una puerta cerrada y una puerta que se cierra
        después de dejar entrar.
        """
        with patch(f"{MOD}.frappe.get_doc") as get_doc:
            with self.assertRaises(frappe.ValidationError):
                void_sales_invoice(**ARGS)
        get_doc.assert_not_called()

    def test_el_mensaje_manda_a_la_nota_de_credito(self) -> None:
        """El único camino que queda tiene que estar en el texto, o el usuario se queda sin salida."""
        try:
            void_sales_invoice(**ARGS)
        except frappe.ValidationError:
            mensaje = frappe.message_log[-1] if frappe.message_log else ""
            texto = mensaje.get("message", "") if isinstance(mensaje, dict) else str(mensaje)
            self.assertIn("Nota de Crédito", texto)
        else:
            self.fail("se esperaba que la anulación fuera rechazada")
