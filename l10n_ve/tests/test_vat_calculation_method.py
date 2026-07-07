# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios del método de cálculo del IVA (Venezuela Account Settings)
y sus extensiones del motor en l10n_ve.controllers.taxes_and_totals:

- get_current_tax_fraction: el charge_type VE 'VAT' participa del modo
  IVA-incluido (included_in_print_rate), que el core no contempla.
- determine_exclusive_rate: a los ítems exentos se les inyecta tasa 0
  temporal para que no se les extraiga IVA que su precio no contiene.
- _anchor_base_leg_on_inclusive_amount: el carril Bs se re-ancla al total
  con IVA (base_amount) para que total Bs == total USD x tasa exacto.
- Venezuela Account Settings._sync_vat_calculation_method: sincroniza el
  flag nativo en las plantillas de venta al cambiar el método.

Suite unittest + mocks (sin BD). Validación end-to-end con documentos
reales: simulación en rollback sobre domina.galanet (ver PR).
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.tests.helpers import make_mock_item, make_mock_tax
from l10n_ve.l10n_ve.doctype.venezuela_account_settings.venezuela_account_settings import (
    VenezuelaAccountSettings,
)

_SETTINGS_MOD = "l10n_ve.l10n_ve.doctype.venezuela_account_settings.venezuela_account_settings"


def _engine(doc=None) -> TaxesAndTotals:
    """Instancia el motor sin ejecutar __init__ (que calcularía)."""
    engine = TaxesAndTotals.__new__(TaxesAndTotals)
    if doc is not None:
        engine.doc = doc
    return engine


class TestVatInclusiveFraction(unittest.TestCase):
    """get_current_tax_fraction con charge_type 'VAT'."""

    def test_vat_inclusive_returns_rate_fraction(self):
        tax = make_mock_tax(charge_type="VAT", rate=16.0, included_in_print_rate=1)
        fraction, per_qty = _engine().get_current_tax_fraction(tax, {})
        self.assertAlmostEqual(fraction, 0.16)
        self.assertEqual(per_qty, 0)

    def test_vat_exclusive_stays_zero(self):
        """Sin el flag, el modo actual queda intacto (fracción 0)."""
        tax = make_mock_tax(charge_type="VAT", rate=16.0, included_in_print_rate=0)
        fraction, _ = _engine().get_current_tax_fraction(tax, {})
        self.assertEqual(fraction, 0)

    def test_vat_inclusive_deduct_negates(self):
        tax = make_mock_tax(
            charge_type="VAT", rate=16.0,
            included_in_print_rate=1, add_deduct_tax="Deduct",
        )
        fraction, _ = _engine().get_current_tax_fraction(tax, {})
        self.assertAlmostEqual(fraction, -0.16)

    def test_item_tax_map_overrides_rate(self):
        """La tasa por ítem (item_tax_rate) manda sobre la de la fila."""
        tax = make_mock_tax(
            charge_type="VAT", rate=16.0,
            included_in_print_rate=1, account_head="IVA-CUENTA",
        )
        engine = _engine(doc=frappe._dict({"precision": lambda *a: 2}))
        engine.doc.precision = lambda *a: 2
        fraction, _ = engine.get_current_tax_fraction(tax, {"IVA-CUENTA": 0.0})
        self.assertEqual(fraction, 0)


class TestExemptInjection(unittest.TestCase):
    """determine_exclusive_rate: tasa 0 temporal para ítems exentos."""

    def _run(self, items, taxes):
        doc = frappe._dict({"taxes": taxes, "items": items})
        doc.get = lambda k, d=None: dict(doc).get(k, d)
        engine = _engine(doc=doc)

        seen_during_core: dict = {}

        def fake_core(self_engine):
            for it in items:
                seen_during_core[it.item_code] = it.item_tax_rate

        with patch.object(calculate_taxes_and_totals, "determine_exclusive_rate", fake_core), \
             patch.object(TaxesAndTotals, "_anchor_base_leg_on_inclusive_amount"):
            engine.determine_exclusive_rate()
        return seen_during_core

    def test_exempt_item_gets_zero_map_and_restores(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0,
                            included_in_print_rate=1, account_head="IVA-CUENTA")
        exempt = make_mock_item(vat_exempt=True, item_code="EXENTO", item_tax_rate="{}")
        normal = make_mock_item(vat_exempt=False, item_code="NORMAL", item_tax_rate="{}")

        seen = self._run([exempt, normal], [vat])

        self.assertIn("IVA-CUENTA", seen["EXENTO"])   # tasa 0 inyectada durante el core
        self.assertEqual(seen["NORMAL"], "{}")         # el gravado no se toca
        self.assertEqual(exempt.item_tax_rate, "{}")   # restaurado al salir

    def test_no_injection_when_not_inclusive(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0, included_in_print_rate=0)
        exempt = make_mock_item(vat_exempt=True, item_code="EXENTO", item_tax_rate="{}")

        seen = self._run([exempt], [vat])
        self.assertEqual(seen["EXENTO"], "{}")

    def test_existing_item_map_is_respected(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0,
                            included_in_print_rate=1, account_head="IVA-CUENTA")
        own_map = '{"OTRA-CUENTA": 8.0}'
        exempt = make_mock_item(vat_exempt=True, item_code="EXENTO", item_tax_rate=own_map)

        seen = self._run([exempt], [vat])
        self.assertEqual(seen["EXENTO"], own_map)


class TestAnchorBaseLeg(unittest.TestCase):
    """_anchor_base_leg_on_inclusive_amount: total Bs == total x tasa."""

    def _engine_for(self, items, taxes, multicurrency=True):
        doc = frappe._dict({"taxes": taxes, "items": items})
        doc.get = lambda k, d=None: dict(doc).get(k, d)
        engine = _engine(doc=doc)
        engine.discount_amount_applied = False
        engine._is_multicurrency = lambda: multicurrency
        return engine

    def test_base_leg_reanchored_to_inclusive_total(self):
        """35 USD x 633.3644 = 22167.75 Bs -> base 19110.13 (no 19108.60)."""
        vat = make_mock_tax(charge_type="VAT", rate=16.0,
                            included_in_print_rate=1, account_head="IVA-CUENTA")
        item = make_mock_item(qty=1, item_tax_rate="{}", base_amount=22167.75)
        item.precision = lambda *a: 2

        self._engine_for([item], [vat])._anchor_base_leg_on_inclusive_amount()

        self.assertAlmostEqual(item.base_net_amount, 19110.13)
        self.assertAlmostEqual(item.base_net_rate, 19110.13)

    def test_exempt_item_not_reanchored(self):
        """Fracción 0 (mapa de tasa 0 del exento) -> base intacta."""
        vat = make_mock_tax(charge_type="VAT", rate=16.0,
                            included_in_print_rate=1, account_head="IVA-CUENTA")
        item = make_mock_item(qty=1, base_amount=22167.75, base_net_amount=22167.75,
                              item_tax_rate='{"IVA-CUENTA": 0.0}')
        item.precision = lambda *a: 2
        engine = self._engine_for([item], [vat])
        engine.doc.precision = lambda *a: 2

        engine._anchor_base_leg_on_inclusive_amount()
        self.assertEqual(item.base_net_amount, 22167.75)

    def test_single_currency_untouched(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0,
                            included_in_print_rate=1, account_head="IVA-CUENTA")
        item = make_mock_item(qty=1, base_amount=116.0, base_net_amount=116.0,
                              item_tax_rate="{}")
        self._engine_for([item], [vat], multicurrency=False)._anchor_base_leg_on_inclusive_amount()
        self.assertEqual(item.base_net_amount, 116.0)

    def test_exclusive_mode_untouched(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0, included_in_print_rate=0)
        item = make_mock_item(qty=1, base_amount=19108.60, base_net_amount=19108.60,
                              item_tax_rate="{}")
        self._engine_for([item], [vat])._anchor_base_leg_on_inclusive_amount()
        self.assertEqual(item.base_net_amount, 19108.60)


class TestSettingsSync(unittest.TestCase):
    """_sync_vat_calculation_method: sincroniza el flag en plantillas."""

    def _settings(self, value, changed=True):
        doc = VenezuelaAccountSettings.__new__(VenezuelaAccountSettings)
        doc.vat_calculation_method = value
        doc.has_value_changed = lambda f: changed
        return doc

    @patch(f"{_SETTINGS_MOD}.frappe")
    def test_from_total_sets_inclusive_flag(self, mock_frappe):
        mock_frappe.get_all.return_value = ["fila-1", "fila-2"]
        self._settings("Desde el total de la factura")._sync_vat_calculation_method()

        writes = [c.args for c in mock_frappe.db.set_value.call_args_list]
        self.assertEqual(len(writes), 2)
        for args in writes:
            self.assertEqual(args[2:], ("included_in_print_rate", 1))
        mock_frappe.msgprint.assert_called_once()

    @patch(f"{_SETTINGS_MOD}.frappe")
    def test_from_base_clears_inclusive_flag(self, mock_frappe):
        mock_frappe.get_all.return_value = ["fila-1"]
        self._settings("Desde la base imponible")._sync_vat_calculation_method()

        args = mock_frappe.db.set_value.call_args.args
        self.assertEqual(args[2:], ("included_in_print_rate", 0))

    @patch(f"{_SETTINGS_MOD}.frappe")
    def test_no_change_is_noop(self, mock_frappe):
        self._settings("Desde la base imponible", changed=False)._sync_vat_calculation_method()
        mock_frappe.get_all.assert_not_called()
        mock_frappe.db.set_value.assert_not_called()


class TestVatMethodRequired(unittest.TestCase):
    """_validate_vat_method_configured: throw si el método no está definido."""

    def _engine_with_vat(self):
        vat = make_mock_tax(charge_type="VAT", rate=16.0)
        doc = frappe._dict({"taxes": [vat]})
        doc.get = lambda k, d=None: dict(doc).get(k, d)
        return _engine(doc=doc)

    @patch("l10n_ve.controllers.taxes_and_totals.frappe.get_cached_value", return_value=None)
    def test_throws_when_method_not_configured(self, _mock):
        with self.assertRaises(frappe.exceptions.ValidationError):
            self._engine_with_vat()._validate_vat_method_configured()

    @patch("l10n_ve.controllers.taxes_and_totals.frappe.get_cached_value",
           return_value="Desde la base imponible")
    def test_passes_when_method_configured(self, _mock):
        self._engine_with_vat()._validate_vat_method_configured()  # no lanza

    @patch("l10n_ve.controllers.taxes_and_totals.frappe.get_cached_value", return_value=None)
    def test_docs_without_vat_are_not_blocked(self, mock_cached):
        """Documentos sin fila VAT (p. ej. exentos puros) no consultan ni bloquean."""
        tax = make_mock_tax(charge_type="On Net Total", rate=5.0)
        doc = frappe._dict({"taxes": [tax]})
        doc.get = lambda k, d=None: dict(doc).get(k, d)
        _engine(doc=doc)._validate_vat_method_configured()
        mock_cached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
