# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
A qué correo se le avisa según el entorno (`hka_environment.notification_emails`).

En un sitio que no es producción, el correo del cliente no debe salir: se desvía al de
pruebas. Lo delicado no es el desvío sino que **el payload y la vista previa usen la
misma regla** — que diverjan es peor que no filtrar, porque la pantalla asegura que el
correo del cliente no sale y sale igual.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.digital_invoice.hka_environment import notification_emails

DEMO = "https://demoemisionv2.thefactoryhka.com.ve"
PROD = "https://emisionv2.thefactoryhka.com.ve"
REALES = ["cliente@empresa.com", "pagos@empresa.com"]


def _cfg(produccion, test_email=None, flag=None):
    cfg = {
        "digital_billing_settings": {
            "is_production_mode": flag if flag is not None else (1 if produccion else 0),
            "demo_url": DEMO,
            "production_url": PROD,
        }
    }
    if test_email is not None:
        cfg["l10n_ve_settings"] = {"test_email": test_email}
    return cfg


class TestNotificationEmails(unittest.TestCase):
    def _run(self, cfg, reales=REALES):
        with patch("frappe.get_site_config", return_value=cfg):
            return notification_emails(reales)

    def test_production_sends_to_the_customer(self):
        self.assertEqual(self._run(_cfg(True)), REALES)

    def test_demo_diverts_to_the_test_address(self):
        self.assertEqual(self._run(_cfg(False, "qa@domina.com.ve")), ["qa@domina.com.ve"])

    def test_the_test_address_can_be_a_list(self):
        self.assertEqual(
            self._run(_cfg(False, "qa@domina.com.ve, dev@domina.com.ve")),
            ["qa@domina.com.ve", "dev@domina.com.ve"],
        )

    def test_demo_without_a_test_address_sends_to_nobody(self):
        """Sin destinatario de pruebas no se manda a nadie, y NO se corta.

        Cortar seria fail-closed sobre el papel: en la practica rompe la vista previa y
        la emision de todo sitio de desarrollo y del CI, que no tienen `test_email`. Para
        un dato cuyo unico proposito es proteger, la lista vacia ya es el resultado
        seguro; lo que no puede pasar es que salga el del cliente.
        """
        self.assertEqual(self._run(_cfg(False)), [])

    def test_the_test_address_is_read_from_l10n_ve_settings(self):
        """No de `digital_billing_settings`, que es donde se buscó primero y no está.

        Es el mismo bloque que usan los avisos de retenciones (`tasks.py`).
        """
        cfg = _cfg(False)
        cfg["digital_billing_settings"]["test_email"] = "no-va-aca@x.com"
        self.assertEqual(self._run(cfg), [], "no debe leerse de digital_billing_settings")

    def test_a_quoted_flag_is_not_interpreted(self):
        """`"0"` es texto no vacío: con un `bool()` pelado daba producción.

        Acá sí se corta, porque el valor es ambiguo: no se sabe si el sitio es de
        pruebas o no, y de eso depende que salga el correo del cliente.
        """
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._run(_cfg(False, "qa@domina.com.ve", flag="0"))
        self.assertIn("no es 0 ni 1", str(ctx.exception))

    def test_a_site_without_hka_configured_sends_to_nobody(self):
        """Un sitio sin `digital_billing_settings` no emite a HKA: nada que proteger.

        Cortar acá rompía toda la suite de payload en un sitio recién creado --el del
        CI-- sin ganar nada.
        """
        self.assertEqual(self._run({}), [])

    def test_a_customer_without_email_is_not_an_error_in_production(self):
        self.assertEqual(self._run(_cfg(True), []), [])


class TestPreviewMirrorsThePayload(unittest.TestCase):
    """Los dos lugares que muestran el correo tienen que resolverlo igual.

    Se afirma sobre el comportamiento y no sobre el fuente: `get_invoice_preview_data`
    lo monkey-patchea `domina_isp` para agregarle zona/nodo, asi que un `getsource`
    devuelve el envoltorio y el test verificaria lo contrario de lo que dice.
    """

    def test_both_resolve_to_the_same_addresses(self):
        cfg = _cfg(False, "qa@domina.com.ve")
        with patch("frappe.get_site_config", return_value=cfg):
            del_payload = notification_emails(REALES)
            del_preview = ", ".join(notification_emails(REALES))
        self.assertEqual(del_payload, ["qa@domina.com.ve"])
        self.assertEqual(del_preview, "qa@domina.com.ve")

    def test_neither_builds_the_address_on_its_own(self):
        import inspect

        from l10n_ve.digital_invoice import payload_builder

        src = inspect.getsource(payload_builder)
        self.assertIn("notification_emails", src)
        self.assertNotIn('[e.strip() for e in self.doc.contact_email.split(",")', src)


if __name__ == "__main__":
    unittest.main()
