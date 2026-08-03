# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""La tasa de un documento fiscal se ancla en HOY, nunca en la fecha del documento.

Lo que se declara ante el SENIAT es la tasa del día en que el documento se EMITE, no la
del período que factura. Si el cliente paga hoy un servicio de marzo, la factura sale a
la tasa de hoy.

    Jurídico  -> tasa del día de hoy.
    Natural   -> tasa del 1° del mes EN CURSO.

Incidente que lo motivó (2026-08-03): `ACC-SINV-2026-13754`, cliente natural. A la
función se le pasaba el `posting_date` de la factura --julio-- así que devolvía la tasa
del 1° de julio (633,3644). El documento salió ante el SENIAT con fecha de emisión 1° de
agosto y esa tasa: base imponible Bs 109.200,76 cuando a la tasa del 1° de agosto
(746,6297) correspondían Bs 128.726,43. Bs 19.526 de base y Bs 3.124 de IVA por debajo.

El parámetro `date` se conserva por compatibilidad de firma pero ya no participa de la
regla, y estos tests lo fijan: pasarle una fecha vieja no cambia el resultado.

Sin base de datos: se simulan el tipo de cliente y el catálogo de tasas.
"""

import unittest
from unittest.mock import patch

from frappe import _dict

MOD = "l10n_ve.utils.utils"

#: La función está whitelisted, y el wrapper de `frappe.whitelist` consulta
#: `local.flags.in_test` para decidir si valida tipos. Fuera de un contexto de Frappe eso
#: revienta con `AttributeError: flags`, así que se simula el mínimo: sin request y sin
#: modo test, el wrapper llama a la función y no toca nada más.
_SIN_CONTEXTO = _dict(request=None, flags=_dict(in_test=False))

#: Tasas reales de producción.
TASAS = {
    "2026-03-01": 402.1100,
    "2026-07-01": 633.3644,
    "2026-08-01": 746.6297,
    "2026-08-03": 751.2088,
}

#: Hoy, para todos los tests.
HOY = "2026-08-03"


def _tasa(customer, date, juridico):
    from l10n_ve.utils.utils import get_ve_exchange_rate_for_customer

    with patch("frappe.local", _SIN_CONTEXTO), patch(
        f"{MOD}.nowdate", return_value=HOY
    ), patch(
        f"{MOD}.is_juridical_customer", return_value=juridico
    ), patch(
        f"{MOD}.get_exchange_rate", side_effect=lambda d, _c: TASAS.get(str(d), 0.0)
    ):
        return get_ve_exchange_rate_for_customer(customer, date)


class TestVeExchangeRateForCustomer(unittest.TestCase):
    def test_a_juridical_gets_todays_rate(self):
        self.assertEqual(_tasa("PINK LOVERS C.A", HOY, True), 751.2088)

    def test_a_natural_gets_the_rate_of_the_first_of_the_current_month(self):
        self.assertEqual(_tasa("ANTONIO MARTINEZ", HOY, False), 746.6297)

    def test_the_date_argument_does_not_change_a_juridical(self):
        """Se le puede pasar cualquier fecha: la regla se ancla en hoy."""
        self.assertEqual(_tasa("PINK LOVERS C.A", "2026-03-15", True), 751.2088)

    def test_the_date_argument_does_not_change_a_natural(self):
        """El incidente de ACC-SINV-2026-13754: se le pasaba el posting_date de julio.

        Antes devolvía 633,3644 (1° de julio). Ahora devuelve la del 1° de agosto, que
        es el mes en el que el documento se está emitiendo.
        """
        self.assertEqual(_tasa("ANTONIO MARTINEZ", "2026-07-01", False), 746.6297)

    def test_a_customer_that_pays_an_old_period_gets_todays_rate(self):
        """«Si el cliente ahorita en agosto me paga marzo, la factura sale a tasa de agosto»."""
        self.assertEqual(_tasa("ANTONIO MARTINEZ", "2026-03-01", False), 746.6297)
        self.assertEqual(_tasa("PINK LOVERS C.A", "2026-03-01", True), 751.2088)

    def test_without_a_customer_it_falls_back_to_natural(self):
        """Sin cliente no se puede saber el tipo; el 1° del mes es el lado conservador."""
        self.assertEqual(_tasa("", HOY, False), 746.6297)

    def test_it_returns_zero_when_there_is_no_published_rate(self):
        """Sin tasa publicada devuelve 0.0 y el llamador decide; no inventa una."""
        from l10n_ve.utils.utils import get_ve_exchange_rate_for_customer

        with patch("frappe.local", _SIN_CONTEXTO), patch(
            f"{MOD}.nowdate", return_value="2026-12-05"
        ), patch(
            f"{MOD}.is_juridical_customer", return_value=True
        ), patch(f"{MOD}.get_exchange_rate", return_value=None):
            self.assertEqual(
                get_ve_exchange_rate_for_customer("X", "2026-12-05"), 0.0
            )
