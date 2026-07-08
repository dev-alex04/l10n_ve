# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios del método de cálculo de impuestos (Venezuela Account
Settings) y su implementación en l10n_ve.controllers.taxes_and_totals.

Semántica (rediseño 2026-07): los precios SIEMPRE se cargan como base
imponible y las plantillas no cambian — el método solo decide cómo se
deriva el carril fiscal (Bs):

- "Desde la base imponible": base Bs = base USD x tasa (comportamiento
  histórico, sin cambios).
- "Desde el total de la factura": por ítem gravado se reconstruye el total
  comercial redondeado (base x 1,16 a 2 dec) y el carril Bs se ancla a ese
  total x tasa, derivando la base hacia atrás
  (_anchor_item_base_amounts_ve). El carril USD no cambia.

El guard _validate_tax_method_configured bloquea el cálculo de documentos
con impuestos si el método no está definido (sin default: elección
consciente por site).

Suite unittest + mocks (sin BD). Validación end-to-end con documentos
reales: simulación en rollback sobre domina.galanet (ver PR).
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.controllers.taxes_and_totals import TAX_FROM_TOTAL, TaxesAndTotals
from l10n_ve.tests.helpers import MockDoc, make_mock_item, make_mock_tax
_ENGINE_MOD = "l10n_ve.controllers.taxes_and_totals"

RATE = 633.3644


def _engine(items, taxes, method=TAX_FROM_TOTAL, multicurrency=True,
            conversion_rate=RATE) -> TaxesAndTotals:
    """Instancia el motor sin ejecutar __init__ (que calcularía)."""
    engine = TaxesAndTotals.__new__(TaxesAndTotals)
    # MockDoc y no frappe._dict: el acceso doc.items colisiona con dict.items()
    engine.doc = MockDoc(
        taxes=taxes,
        items=items,
        conversion_rate=conversion_rate,
    )
    engine._is_multicurrency = lambda: multicurrency
    engine._get_tax_calculation_method = lambda: method
    return engine


def _vat_tax(rate=16.0, **kw):
    return make_mock_tax(charge_type="VAT", rate=rate, **kw)


def _item(net=25.86, exempt=False, qty=1.0):
    item = make_mock_item(
        net_amount=net, amount=net, qty=qty, vat_exempt=exempt,
        base_net_amount=round(net * RATE, 2), base_amount=round(net * RATE, 2),
    )
    item.precision = lambda *a: 2
    return item


class TestAnchorItemBaseAmounts(unittest.TestCase):
    """_anchor_item_base_amounts_ve: el carril Bs se ancla al total x tasa."""

    def test_taxable_item_anchored_to_rounded_total(self):
        """Base $25,86 -> total 30,00 -> Bs 19.000,93 -> base Bs 16.380,11."""
        item = _item(25.86)
        _engine([item], [_vat_tax()])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(item.base_net_amount, 16380.11)
        self.assertAlmostEqual(item.base_net_rate, 16380.11)
        self.assertAlmostEqual(item.base_amount, 16380.11)
        # cierre: base anclada x 1,16 == total comercial x tasa
        self.assertAlmostEqual(round(item.base_net_amount * 1.16, 2), 19000.93)

    def test_admin_case_35_usd_plan(self):
        """Caso administración: base 30,17 -> total 35,00 -> Bs 22.167,75."""
        item = _item(30.17)
        _engine([item], [_vat_tax()])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(round(item.base_net_amount * 1.16, 2), 22167.75)

    def test_exempt_item_untouched(self):
        """El exento no lleva impuesto: conversión directa (sin ancla)."""
        item = _item(10.0, exempt=True)
        original = item.base_net_amount
        _engine([item], [_vat_tax()])._anchor_item_base_amounts_ve()
        self.assertEqual(item.base_net_amount, original)

    def test_base_method_is_noop(self):
        """Método 'Desde la base imponible': comportamiento histórico intacto."""
        item = _item(25.86)
        original = item.base_net_amount
        _engine([item], [_vat_tax()],
                method="Desde la base imponible")._anchor_item_base_amounts_ve()
        self.assertEqual(item.base_net_amount, original)

    def test_no_vat_rows_is_noop(self):
        item = _item(25.86)
        original = item.base_net_amount
        islr = make_mock_tax(charge_type="ISLR", rate=5.0)
        _engine([item], [islr])._anchor_item_base_amounts_ve()
        self.assertEqual(item.base_net_amount, original)

    def test_withholding_and_deduct_rows_excluded_from_rate(self):
        """Retenciones y filas Deduct no cuentan para la tasa efectiva."""
        item = _item(25.86)
        wh = make_mock_tax(charge_type="VAT", rate=75.0, is_tax_withholding_account=True)
        ded = make_mock_tax(charge_type="VAT", rate=16.0, add_deduct_tax="Deduct")
        _engine([item], [_vat_tax(16.0), wh, ded])._anchor_item_base_amounts_ve()
        # factor = 1.16 (solo la fila VAT aditiva)
        self.assertAlmostEqual(item.base_net_amount, 16380.11)

    def test_single_currency_is_noop(self):
        item = _item(25.86)
        original = item.base_net_amount
        _engine([item], [_vat_tax()], multicurrency=False)._anchor_item_base_amounts_ve()
        self.assertEqual(item.base_net_amount, original)

    def test_exempt_only_with_islr_is_immune_to_method(self):
        """Documento 100% exento con solo ISLR: sin impuesto aditivo no hay
        ancla posible — ambos métodos dan lo mismo (validado en vivo con
        ACC-SINV-2026-10834 exenta: ISLR Bs 690,00 idéntico)."""
        item = _item(51.72, exempt=True)
        original = item.base_net_amount
        islr = make_mock_tax(charge_type="ISLR", rate=2.0, percentage_base=100.0)

        _engine([item], [islr])._anchor_item_base_amounts_ve()

        self.assertEqual(item.base_net_amount, original)

    def test_withholding_follows_anchored_vat_base(self):
        """La retención IVA Bs sigue al IVA del método: 75% del IVA derivado
        de la base ANCLADA (invariante fiscal: el comprobante siempre cuadra
        contra el IVA de su propia factura)."""
        item = _item(25.86)
        vat = _vat_tax(16.0)
        wh = make_mock_tax(charge_type="VAT Withholding", rate=75.0,
                           is_tax_withholding_account=True)

        engine = _engine([item], [vat, wh])
        engine._anchor_item_base_amounts_ve()          # base Bs -> 16.380,11
        engine.doc.base_net_total = item.base_net_amount
        engine._recalculate_base_tax_amounts_ve()      # deriva IVA y retención Bs

        self.assertAlmostEqual(vat.base_tax_amount, 2620.82)          # 16% de 16.380,11
        self.assertAlmostEqual(wh.base_tax_amount, 1965.62, places=2)  # 75% del IVA Bs
        self.assertAlmostEqual(
            wh.base_tax_amount, round(vat.base_tax_amount * 0.75, 2), places=2
        )


class TestVatMethodRequired(unittest.TestCase):
    """_validate_tax_method_configured: throw si el método no está definido."""

    def _engine_with(self, charge_type):
        tax = make_mock_tax(charge_type=charge_type, rate=16.0)
        engine = TaxesAndTotals.__new__(TaxesAndTotals)
        doc = frappe._dict({"taxes": [tax]})
        doc.get = lambda k, d=None: dict(doc).get(k, d)
        engine.doc = doc
        return engine

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_value", return_value=None)
    def test_throws_when_method_not_configured(self, _mock):
        with self.assertRaises(frappe.exceptions.ValidationError):
            self._engine_with("VAT")._validate_tax_method_configured()

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_value", return_value="Desde la base imponible")
    def test_passes_when_method_configured(self, _mock):
        self._engine_with("VAT")._validate_tax_method_configured()  # no lanza

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_value", return_value=None)
    def test_on_net_total_also_requires_method(self, _mock):
        with self.assertRaises(frappe.exceptions.ValidationError):
            self._engine_with("On Net Total")._validate_tax_method_configured()

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_value", return_value=None)
    def test_docs_without_price_anchored_taxes_are_not_blocked(self, mock_cached):
        self._engine_with("ISLR")._validate_tax_method_configured()
        mock_cached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
