# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la fecha de la tasa BCV que se imprime en el documento HKA.

Bug origen (jul-2026): factura de cliente jurídico generada el 01/07
(tasa 633.3644) y re-tasada al primer pago días después (tasa 653.9726,
regla jurídico = tasa del día del comprobante). El string impreso decía
"de fecha valor 01/07/2026" (inferido del posting_date) con la tasa nueva:
par tasa/fecha inconsistente ante SENIAT.

Fix: la fecha se resuelve desde la tasa misma con lookup inverso en
Currency Exchange (resolve_exchange_rate_date), no desde el posting_date.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from l10n_ve.utils.utils import resolve_exchange_rate_date
from l10n_ve.digital_invoice.tfhka_integration import _compute_tasa_fecha


def _make_invoice(**overrides):
    base = {
        "posting_date": "2026-07-01",
        "customer": "CUST-TEST",
        "conversion_rate": 653.9726,
        "currency": "USD",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestResolveExchangeRateDate(unittest.TestCase):
    @patch("frappe.db.sql", return_value=[("2026-07-02",)])
    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_date_of_matching_rate(self, _defaults, mock_sql):
        """Devuelve la fecha de la fila cuya tasa coincide con la del documento."""
        result = resolve_exchange_rate_date(653.9726, "USD")

        self.assertEqual(result, "2026-07-02")
        params = mock_sql.call_args[0][1]
        self.assertEqual(params[0], 653.9726)
        self.assertEqual(params[1], "USD")

    @patch("frappe.db.sql", return_value=[])
    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_none_when_no_row_matches(self, _defaults, _sql):
        """Sin fila coincidente → None (el caller decide el fallback)."""
        self.assertIsNone(resolve_exchange_rate_date(999.9999, "USD"))

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    def test_returns_none_for_trivial_rates(self, _defaults):
        """Tasa vacía o factura en la moneda de la empresa → None sin ir a la BDD."""
        self.assertIsNone(resolve_exchange_rate_date(0, "USD"))
        self.assertIsNone(resolve_exchange_rate_date(1.0, "VEF"))


class TestComputeTasaFecha(unittest.TestCase):
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date",
        return_value="2026-07-02",
    )
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=True,
    )
    def test_juridical_uses_real_rate_date_not_posting_date(self, _jur, mock_resolve):
        """Caso del bug: jurídico re-tasado al pagar → la fecha es la de la tasa."""
        doc = _make_invoice(posting_date="2026-07-01", conversion_rate=653.9726)

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-02")
        mock_resolve.assert_called_once_with(653.9726, "USD")

    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date",
        return_value=None,
    )
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=True,
    )
    def test_juridical_falls_back_to_posting_date(self, _jur, _resolve):
        """Tasa sin fila en Currency Exchange → conserva el comportamiento previo."""
        doc = _make_invoice(posting_date="2026-07-01")

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-01")

    @patch("l10n_ve.digital_invoice.tfhka_integration.resolve_exchange_rate_date")
    @patch(
        "l10n_ve.digital_invoice.tfhka_integration.is_juridical_customer",
        return_value=False,
    )
    def test_natural_keeps_first_of_month_without_lookup(self, _jur, mock_resolve):
        """Naturales: 1° del mes del posting_date, sin lookup inverso."""
        doc = _make_invoice(posting_date="2026-07-15")

        self.assertEqual(_compute_tasa_fecha(doc), "2026-07-01")
        mock_resolve.assert_not_called()
