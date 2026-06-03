# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests del caché Redis de get_exchange_rate (l10n_ve.utils.utils).

- La misma (fecha, moneda) se sirve desde caché: una sola consulta a la BDD.
- clear_exchange_rate_cache() invalida el caché: la siguiente consulta
  vuelve a pegar a la BDD (una vez) y re-cachea.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.utils.utils import (
    EXCHANGE_RATE_CACHE_KEY,
    get_exchange_rate,
    clear_exchange_rate_cache,
)

RATE = 554.4258


class TestExchangeRateCache(unittest.TestCase):
    def setUp(self):
        clear_exchange_rate_cache()

    def tearDown(self):
        clear_exchange_rate_cache()

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    @patch("l10n_ve.utils.utils._query_exchange_rate", return_value=RATE)
    def test_same_date_currency_hits_cache(self, mock_query, _defaults):
        """Dos consultas iguales → un solo query a la BDD."""
        first = get_exchange_rate("2026-06-01", "USD")
        second = get_exchange_rate("2026-06-01", "USD")

        self.assertEqual(first, RATE)
        self.assertEqual(second, RATE)
        mock_query.assert_called_once()

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    @patch("l10n_ve.utils.utils._query_exchange_rate", return_value=RATE)
    def test_different_keys_query_separately(self, mock_query, _defaults):
        """Fechas/monedas distintas no comparten entrada de caché."""
        get_exchange_rate("2026-06-01", "USD")
        get_exchange_rate("2026-06-02", "USD")  # otra fecha
        get_exchange_rate("2026-06-01", "EUR")  # otra moneda

        self.assertEqual(mock_query.call_count, 3)

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    @patch("l10n_ve.utils.utils._query_exchange_rate", return_value=RATE)
    def test_clear_cache_forces_requery(self, mock_query, _defaults):
        """Tras invalidar, la siguiente consulta vuelve a la BDD una vez."""
        get_exchange_rate("2026-06-01", "USD")
        get_exchange_rate("2026-06-01", "USD")
        self.assertEqual(mock_query.call_count, 1)

        clear_exchange_rate_cache()

        get_exchange_rate("2026-06-01", "USD")
        get_exchange_rate("2026-06-01", "USD")
        self.assertEqual(mock_query.call_count, 2)

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    @patch("l10n_ve.utils.utils._query_exchange_rate", return_value=RATE)
    def test_value_is_actually_stored_in_cache(self, mock_query, _defaults):
        """El valor queda persistido en el hash de caché."""
        get_exchange_rate("2026-06-01", "USD")

        cached = frappe.cache().hget(EXCHANGE_RATE_CACHE_KEY, "2026-06-01|USD|VEF")
        self.assertEqual(flt_or_none(cached), RATE)

    @patch("frappe.defaults.get_defaults", return_value={"currency": "VEF"})
    @patch("l10n_ve.utils.utils._query_exchange_rate", return_value=0)
    def test_zero_rate_is_not_cached(self, mock_query, _defaults):
        """Una fecha sin tasa (0) no se cachea: se reintenta en la próxima."""
        get_exchange_rate("2099-01-01", "USD")
        get_exchange_rate("2099-01-01", "USD")

        self.assertEqual(mock_query.call_count, 2)

    @patch("frappe.defaults.get_defaults", return_value={"currency": "USD"})
    @patch("l10n_ve.utils.utils._query_exchange_rate")
    def test_same_currency_returns_one_without_query(self, mock_query, _defaults):
        """from == to → 1.0 sin tocar BDD ni caché."""
        self.assertEqual(get_exchange_rate("2026-06-01", "USD"), 1.0)
        mock_query.assert_not_called()


def flt_or_none(value):
    from frappe.utils import flt
    return None if value is None else flt(value)
