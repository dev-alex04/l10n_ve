# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios de la herencia del carril Bs en retornos (Notas de
Crédito/Débito con factura de origen), implementada en
l10n_ve.controllers.taxes_and_totals._anchor_item_base_amounts_ve.

Motivación (fix PR #416): al cambiar el método de cálculo global, las Notas
de Crédito derivaban montos/IVA en Bs distintos a los de la factura original
(return_against), rompiendo el cuadre Débito/Crédito al someterlas. La
solución fuerza que el carril Bs del retorno herede el de la factura afectada
escalado por la proporción de monto (net_amount), de modo que:

- una devolución total espeja la base Bs del original céntimo a céntimo;
- una devolución parcial (menos cantidad) o con precio editado escala
  proporcionalmente por net_amount (captura cantidad Y precio);
- el emparejamiento usa sales_invoice_item y, en su defecto, item_code.

Suite unittest + mocks (sin BD): el padre se inyecta vía
_get_return_parent_doc, evitando get_cached_doc.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.tests.helpers import MockDoc, make_mock_item, make_mock_tax

_ENGINE_MOD = "l10n_ve.controllers.taxes_and_totals"
RATE = 633.3644


def _p_item(name, net, *, code="PLAN-A", qty=1.0):
    """Ítem de la factura de origen: carril Bs ya anclado 'Desde el total'
    (base Bs = round(round(net*1,16,2)*RATE,2)/1,16)."""
    total_bs = round(round(net * 1.16, 2) * RATE, 2)
    base_bs = round(total_bs / 1.16, 2)
    item = make_mock_item(
        net_amount=net, amount=net, qty=qty, item_code=code,
        base_net_amount=base_bs, base_amount=base_bs,
        base_net_rate=base_bs / qty, base_rate=base_bs / qty,
        price_list_rate=net, base_price_list_rate=base_bs / qty,
        name=name,
    )
    item.precision = lambda *a: 2
    return item


def _r_item(net, *, code="PLAN-A", qty=-1.0, sales_invoice_item=None, price_list_rate=None):
    """Ítem del retorno (montos/cantidad negativos por convención)."""
    item = make_mock_item(
        net_amount=net, amount=net, qty=qty, item_code=code,
        base_net_amount=0.0, base_amount=0.0,
        price_list_rate=price_list_rate if price_list_rate is not None else abs(net),
        sales_invoice_item=sales_invoice_item,
    )
    item.precision = lambda *a: 2
    return item


def _return_engine(items, parent_items, taxes=None, base_net_total=None):
    """Motor con doc de retorno y padre inyectado (sin get_cached_doc)."""
    engine = TaxesAndTotals.__new__(TaxesAndTotals)
    engine.doc = MockDoc(
        doctype="VE Sales Credit Note",
        return_against="ACC-SINV-2026-00001",
        is_return=1,
        items=items,
        taxes=taxes or [],
        conversion_rate=RATE,
    )
    if base_net_total is not None:
        engine.doc.base_net_total = base_net_total
    parent = MockDoc(items=parent_items, base_net_total=sum(i.base_net_amount for i in parent_items))
    engine._get_return_parent_doc = lambda: parent
    return engine


class TestReturnBaseInheritance(unittest.TestCase):
    """_anchor_item_base_amounts_ve: los retornos heredan el carril Bs del
    original escalado por net_amount."""

    def test_full_return_mirrors_parent_base_exactly(self):
        """Devolución total: base Bs del retorno == -base Bs del original,
        céntimo a céntimo (independiente del método global)."""
        parent = _p_item("PARENT-ITEM-1", 25.86)
        ret = _r_item(-25.86, qty=-1.0, sales_invoice_item="PARENT-ITEM-1")

        _return_engine([ret], [parent])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(ret.base_net_amount, -parent.base_net_amount)
        self.assertAlmostEqual(ret.base_amount, -parent.base_amount)
        # el rate queda positivo (monto negativo / qty negativa)
        self.assertAlmostEqual(ret.base_net_rate, parent.base_net_amount)

    def test_partial_qty_return_scales_by_amount(self):
        """Devolución parcial (mitad de la cantidad): base Bs escala a la mitad."""
        parent = _p_item("PARENT-ITEM-1", 100.0, qty=4.0)   # net 100 = 25 x 4
        ret = _r_item(-50.0, qty=-2.0, sales_invoice_item="PARENT-ITEM-1")

        _return_engine([ret], [parent])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(ret.base_net_amount, -parent.base_net_amount / 2)

    def test_price_edit_on_return_is_reflected(self):
        """Precio editado en el retorno: al cambiar net_amount, la base Bs
        escala por net_amount (no se queda pegada al precio del original)."""
        parent = _p_item("PARENT-ITEM-1", 100.0, qty=1.0)
        # misma cantidad, pero precio bajado a la mitad -> net -50
        ret = _r_item(-50.0, qty=-1.0, sales_invoice_item="PARENT-ITEM-1")

        _return_engine([ret], [parent])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(ret.base_net_amount, -parent.base_net_amount / 2)

    def test_fallback_match_by_item_code_when_no_link(self):
        """Sin sales_invoice_item, empareja por item_code (consumiendo el
        primero disponible)."""
        parent = _p_item("PARENT-ITEM-1", 25.86, code="PLAN-A")
        ret = _r_item(-25.86, qty=-1.0, code="PLAN-A", sales_invoice_item=None)

        _return_engine([ret], [parent])._anchor_item_base_amounts_ve()

        self.assertAlmostEqual(ret.base_net_amount, -parent.base_net_amount)

    def test_unmatched_item_left_untouched(self):
        """Ítem del retorno sin correspondencia en el padre: no se toca su
        base (queda como venía, sin crash)."""
        parent = _p_item("PARENT-ITEM-1", 25.86, code="PLAN-A")
        ret = _r_item(-10.0, qty=-1.0, code="PLAN-Z", sales_invoice_item=None)

        _return_engine([ret], [parent])._anchor_item_base_amounts_ve()

        self.assertEqual(ret.base_net_amount, 0.0)

    def test_non_return_falls_through(self):
        """Doc que no es retorno: _get_return_parent_doc devuelve None y el
        método sigue su curso normal sin heredar nada."""
        item = make_mock_item(net_amount=25.86, amount=25.86,
                              base_net_amount=16378.80, base_amount=16378.80)
        item.precision = lambda *a: 2
        engine = TaxesAndTotals.__new__(TaxesAndTotals)
        engine.doc = MockDoc(doctype="Sales Invoice", items=[item],
                            taxes=[make_mock_tax()], conversion_rate=RATE)
        engine._is_multicurrency = lambda: False   # corta tras el guard
        engine._get_return_parent_doc = lambda: None

        engine._anchor_item_base_amounts_ve()

        self.assertEqual(item.base_net_amount, 16378.80)  # intacto


class TestReturnParentResolution(unittest.TestCase):
    """_get_return_parent_doc: resolución del documento de origen."""

    def _return_doc(self, doctype="VE Sales Credit Note", return_against="INV-1", is_return=1):
        engine = TaxesAndTotals.__new__(TaxesAndTotals)
        engine.doc = MockDoc(doctype=doctype, return_against=return_against,
                            is_return=is_return, name="CN-1")
        return engine

    def test_none_when_not_a_return(self):
        engine = self._return_doc(return_against=None, is_return=0)
        self.assertIsNone(engine._get_return_parent_doc())

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_doc")
    def test_resolves_sales_invoice_for_sales_credit_note(self, mock_get):
        mock_get.return_value = "PARENT"
        engine = self._return_doc(doctype="VE Sales Credit Note")
        self.assertEqual(engine._get_return_parent_doc(), "PARENT")
        mock_get.assert_called_once_with("Sales Invoice", "INV-1")

    @patch(f"{_ENGINE_MOD}.frappe.get_cached_doc")
    def test_resolves_purchase_invoice_for_purchase_credit_note(self, mock_get):
        mock_get.return_value = "PARENT"
        engine = self._return_doc(doctype="VE Purchase Credit Note")
        self.assertEqual(engine._get_return_parent_doc(), "PARENT")
        mock_get.assert_called_once_with("Purchase Invoice", "INV-1")

    @patch(f"{_ENGINE_MOD}.frappe.log_error")
    @patch(f"{_ENGINE_MOD}.frappe.get_cached_doc", side_effect=Exception("boom"))
    def test_logs_and_returns_none_on_error(self, _mock_get, mock_log):
        engine = self._return_doc()
        self.assertIsNone(engine._get_return_parent_doc())
        mock_log.assert_called_once()


class TestReturnFullReversalTaxParity(unittest.TestCase):
    """Cuadre del IVA del retorno frente al original.

    Con base heredada, el IVA Bs del retorno se recalcula como base x tasa
    (metodología VE estándar; el ancla 'por diferencia' NO aplica a retornos).
    Para el método por defecto 'Desde la base imponible' esto coincide
    exactamente con el original. Para 'Desde el total' el original derivó su
    IVA por diferencia y puede diferir ±0,01 (residuo de redondeo): se
    documenta aquí como comportamiento conocido."""

    def _run(self, parent_net, parent_vat_base):
        parent = _p_item("PARENT-ITEM-1", parent_net)
        parent_vat = make_mock_tax(charge_type="VAT", rate=16.0,
                                   base_tax_amount=parent_vat_base)
        ret = _r_item(-parent_net, qty=-1.0, sales_invoice_item="PARENT-ITEM-1")
        ret_vat = make_mock_tax(charge_type="VAT", rate=16.0)

        engine = _return_engine([ret], [parent], taxes=[ret_vat])
        engine._is_multicurrency = lambda: True
        engine._anchor_item_base_amounts_ve()
        engine.doc.base_net_total = ret.base_net_amount
        engine._recalculate_base_tax_amounts_ve()
        return parent, ret, parent_vat, ret_vat

    def test_base_reversal_is_exact(self):
        """La base Bs siempre revierte exacto (el corazón del fix)."""
        parent, ret, _pv, _rv = self._run(25.86, 2620.82)
        self.assertAlmostEqual(ret.base_net_amount, -parent.base_net_amount)

    def test_iva_matches_when_no_rounding_residue(self):
        """Caso 25,86: 16% de la base anclada coincide con el IVA del
        original (2.620,82) -> reversa de IVA exacta."""
        _p, _r, parent_vat, ret_vat = self._run(25.86, 2620.82)
        self.assertAlmostEqual(ret_vat.base_tax_amount, -parent_vat.base_tax_amount)

    def test_iva_residue_documented_for_from_total(self):
        """Caso 8,62 (plan $10): el original 'Desde el total' guardó IVA por
        diferencia 873,61; el retorno lo recalcula como 16% de la base
        (873,60) -> residuo conocido de 0,01 en la reversa del IVA. Se fija
        para detectar regresiones si se decide heredar el IVA explícitamente."""
        _p, _r, parent_vat, ret_vat = self._run(8.62, 873.61)
        self.assertAlmostEqual(ret_vat.base_tax_amount, -873.60)
        self.assertAlmostEqual(
            abs(ret_vat.base_tax_amount) - parent_vat.base_tax_amount, -0.01
        )


if __name__ == "__main__":
    unittest.main()
