# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para TaxesAndTotals (l10n_ve override).

Cubre:
- get_current_tax_amount(): cálculo por tipo de cargo (VAT, ISLR, WHT, etc.)
- _recalculate_base_tax_amounts_ve(): recálculo VEF multimoneda
- set_cumulative_total(): acumulación con retenciones VE
- calculate_total_exempt(): total exento
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from unittest.mock import patch, MagicMock

from l10n_ve.tests.helpers import (
    make_mock_item,
    make_mock_tax,
    make_mock_doc,
    make_taxes_and_totals,
)


# ═══════════════════════════════════════════════════════════════════
# get_current_tax_amount()
# ═══════════════════════════════════════════════════════════════════

class TestGetCurrentTaxAmountVAT(FrappeTestCase):
    """Tests para get_current_tax_amount() — charge_type='VAT'."""

    def _calc(self, doc, item, tax) -> float:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return float(calc.get_current_tax_amount(item, tax, {}))

    def test_vat_on_taxable_item(self) -> None:
        """item.net_amount=100, tax.rate=16, VAT → 16.0."""
        item = make_mock_item(net_amount=100)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 16.0, places=2)

    def test_vat_on_exempt_item(self) -> None:
        """item.vat_exempt=True, VAT → 0.0."""
        item = make_mock_item(net_amount=100, vat_exempt=True)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertEqual(result, 0.0)

    def test_vat_large_amount(self) -> None:
        """item.net_amount=50000, rate=16 → 8000.0."""
        item = make_mock_item(net_amount=50000)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 8000.0, places=2)


class TestGetCurrentTaxAmountVATWithholding(FrappeTestCase):
    """Tests para get_current_tax_amount() — charge_type='VAT Withholding'."""

    def _calc(self, doc, item, tax) -> float:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return float(calc.get_current_tax_amount(item, tax, {}))

    def test_vat_withholding_basic(self) -> None:
        """VAT=16%, WHT=75% sobre item $100 → (100×16/100)×75/100 = 12.0."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16)
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        item = make_mock_item(net_amount=100)
        doc = make_mock_doc(items=[item], taxes=[vat_tax, wht_tax])

        result: float = self._calc(doc, item, wht_tax)

        self.assertAlmostEqual(result, 12.0, places=2)

    def test_vat_withholding_exempt_item(self) -> None:
        """item.vat_exempt=True → WHT = 0.0."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16)
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        item = make_mock_item(net_amount=100, vat_exempt=True)
        doc = make_mock_doc(items=[item], taxes=[vat_tax, wht_tax])

        result: float = self._calc(doc, item, wht_tax)

        self.assertEqual(result, 0.0)

    def test_vat_withholding_no_vat_row(self) -> None:
        """Sin fila VAT en taxes → WHT = 0.0 (break nunca ejecuta)."""
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        item = make_mock_item(net_amount=100)
        doc = make_mock_doc(items=[item], taxes=[wht_tax])

        result: float = self._calc(doc, item, wht_tax)

        self.assertEqual(result, 0.0)


class TestGetCurrentTaxAmountISLR(FrappeTestCase):
    """Tests para get_current_tax_amount() — charge_type='ISLR'."""

    def _calc(self, doc, item, tax) -> float:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return float(calc.get_current_tax_amount(item, tax, {}))

    def test_islr_basic(self) -> None:
        """total=1000, percentage_base=100, rate=5, sub=0 → 50.0."""
        item = make_mock_item(net_amount=1000, idx=1)
        tax = make_mock_tax(
            charge_type="ISLR", rate=5,
            percentage_base=100, subtracting=0,
        )
        doc = make_mock_doc(total=1000, items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 50.0, places=2)

    def test_islr_with_subtracting(self) -> None:
        """total=1000, rate=34, sub=83.334 Bs a tasa 36,5 → 340 − 2,283 = 337,717.

        El sustraendo del tabulador está expresado en BOLÍVARES —su campo hermano se
        llama ``payments_greater_than_bs``—, así que se convierte a la moneda del
        documento antes de restarlo. Restarlo crudo, como si fuera USD, inflaba la
        retención: es el bug que corrigió f692fd2d.
        """
        item = make_mock_item(net_amount=1000, idx=1)
        tax = make_mock_tax(
            charge_type="ISLR", rate=34,
            percentage_base=100, subtracting=83.334,
        )
        doc = make_mock_doc(total=1000, items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 340 - (83.334 / 36.5), places=2)

    def test_islr_negative_becomes_zero(self) -> None:
        """Sustraendo > impuesto → resultado 0 (no negativo)."""
        item = make_mock_item(net_amount=10, idx=1)
        tax = make_mock_tax(
            charge_type="ISLR", rate=1,
            percentage_base=100, subtracting=100,
        )
        doc = make_mock_doc(total=10, items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertEqual(result, 0.0)

    def test_islr_only_first_item(self) -> None:
        """Solo el primer item (idx=1) genera monto ISLR; idx=2 → 0."""
        item = make_mock_item(net_amount=1000, idx=2)
        tax = make_mock_tax(
            charge_type="ISLR", rate=5,
            percentage_base=100, subtracting=0,
        )
        doc = make_mock_doc(total=1000, items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertEqual(result, 0.0)


class TestGetCurrentTaxAmountOnNetTotal(FrappeTestCase):
    """Tests para get_current_tax_amount() — charge_type='On Net Total'."""

    def _calc(self, doc, item, tax) -> float:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return float(calc.get_current_tax_amount(item, tax, {}))

    def test_on_net_total_excludes_exempt(self) -> None:
        """2 items (1 exempt, 1 taxable) → rate × solo taxable."""
        item_taxable = make_mock_item(net_amount=100, idx=1)
        item_exempt = make_mock_item(net_amount=50, vat_exempt=True, idx=2)
        tax = make_mock_tax(charge_type="On Net Total", rate=16)
        doc = make_mock_doc(
            items=[item_taxable, item_exempt],
            taxes=[tax],
            net_total=150,
        )

        result: float = self._calc(doc, item_taxable, tax)

        self.assertAlmostEqual(result, 16.0, places=2)

    def test_on_net_total_only_first_item(self) -> None:
        """Solo idx=1 genera monto; idx=2 → 0."""
        item = make_mock_item(net_amount=100, idx=2)
        tax = make_mock_tax(charge_type="On Net Total", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertEqual(result, 0.0)


class TestGetCurrentTaxAmountOther(FrappeTestCase):
    """Tests para get_current_tax_amount() — otros charge_types."""

    def _calc(self, doc, item, tax) -> float:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return float(calc.get_current_tax_amount(item, tax, {}))

    def test_actual_proportional(self) -> None:
        """Actual: tax_amount=50, item.net_amount=200, net_total=1000 → 10.0."""
        item = make_mock_item(net_amount=200)
        tax = make_mock_tax(charge_type="Actual", rate=0, tax_amount=50)
        doc = make_mock_doc(items=[item], taxes=[tax], net_total=1000)

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 10.0, places=2)

    def test_on_previous_row_amount(self) -> None:
        """Previous row tax_amount_for_current_item=16, rate=75 → 12.0."""
        prev_tax = make_mock_tax(
            charge_type="VAT", rate=16,
            tax_amount_for_current_item=16,
        )
        tax = make_mock_tax(
            charge_type="On Previous Row Amount", rate=75, row_id=1,
        )
        item = make_mock_item(net_amount=100)
        doc = make_mock_doc(items=[item], taxes=[prev_tax, tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 12.0, places=2)

    def test_on_item_quantity(self) -> None:
        """qty=5, rate=10 → 50.0."""
        item = make_mock_item(net_amount=100, qty=5)
        tax = make_mock_tax(charge_type="On Item Quantity", rate=10)
        doc = make_mock_doc(items=[item], taxes=[tax])

        result: float = self._calc(doc, item, tax)

        self.assertAlmostEqual(result, 50.0, places=2)


# ═══════════════════════════════════════════════════════════════════
# _recalculate_base_tax_amounts_ve()
# ═══════════════════════════════════════════════════════════════════

class TestRecalculateBaseTaxAmountsVE(FrappeTestCase):
    """Tests para _recalculate_base_tax_amounts_ve(): recálculo VEF multimoneda."""

    def _run_recalc(self, doc) -> None:
        calc = make_taxes_and_totals(doc)
        calc._is_multicurrency = MagicMock(return_value=True)
        calc._recalculate_item_wise_tax_detail_ve = MagicMock()
        calc._recalculate_base_tax_amounts_ve()

    def test_vat_base_recalculation(self) -> None:
        """base_net_amount=36500, rate=16 → base_tax_amount=5840."""
        item = make_mock_item(net_amount=100, base_net_amount=36500)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(
            items=[item], taxes=[tax],
            conversion_rate=365, base_net_total=36500,
        )

        self._run_recalc(doc)

        self.assertAlmostEqual(tax.base_tax_amount, 5840.0, places=2)

    def test_vat_excludes_exempt_items(self) -> None:
        """1 exempt + 1 taxable → base_tax_amount solo del taxable."""
        item_taxable = make_mock_item(
            net_amount=100, base_net_amount=36500, idx=1,
        )
        item_exempt = make_mock_item(
            net_amount=50, base_net_amount=18250,
            vat_exempt=True, idx=2,
        )
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(
            items=[item_taxable, item_exempt], taxes=[tax],
            conversion_rate=365, base_net_total=54750,
        )

        self._run_recalc(doc)

        # Solo base_net_amount del taxable: 36500 × 16% = 5840
        self.assertAlmostEqual(tax.base_tax_amount, 5840.0, places=2)

    def test_vat_withholding_base_recalculation(self) -> None:
        """VAT base_tax_amount=5840, WHT rate=75 → WHT base=4380."""
        item = make_mock_item(net_amount=100, base_net_amount=36500)
        vat_tax = make_mock_tax(
            charge_type="VAT", rate=16, base_tax_amount=5840,
        )
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        doc = make_mock_doc(
            items=[item], taxes=[vat_tax, wht_tax],
            conversion_rate=365, base_net_total=36500,
        )

        self._run_recalc(doc)

        # VAT se recalcula: 36500 × 16% = 5840, luego WHT: 5840 × 75% = 4380
        self.assertAlmostEqual(vat_tax.base_tax_amount, 5840.0, places=2)
        self.assertAlmostEqual(wht_tax.base_tax_amount, 4380.0, places=2)

    def test_islr_base_recalculation(self) -> None:
        """base_total=36500, percentage_base=100, rate=5, sub=0 → 1825."""
        item = make_mock_item(net_amount=100, base_net_amount=36500)
        tax = make_mock_tax(
            charge_type="ISLR", rate=5,
            percentage_base=100, subtracting=0,
            is_tax_withholding_account=True,
        )
        doc = make_mock_doc(
            items=[item], taxes=[tax],
            conversion_rate=365,
            base_net_total=36500, base_total=36500,
        )

        self._run_recalc(doc)

        self.assertAlmostEqual(tax.base_tax_amount, 1825.0, places=2)

    def test_on_net_total_base_recalculation(self) -> None:
        """base_taxable_vef=36500, rate=16 → 5840."""
        item = make_mock_item(net_amount=100, base_net_amount=36500)
        tax = make_mock_tax(charge_type="On Net Total", rate=16)
        doc = make_mock_doc(
            items=[item], taxes=[tax],
            conversion_rate=365, base_net_total=36500,
        )

        self._run_recalc(doc)

        self.assertAlmostEqual(tax.base_tax_amount, 5840.0, places=2)

    def test_skips_single_currency(self) -> None:
        """Moneda local = misma → sin recálculo."""
        item = make_mock_item(net_amount=100, base_net_amount=100)
        tax = make_mock_tax(charge_type="VAT", rate=16, base_tax_amount=999)
        doc = make_mock_doc(
            items=[item], taxes=[tax],
            currency="VES", conversion_rate=1,
            base_net_total=100,
        )
        calc = make_taxes_and_totals(doc)
        calc._is_multicurrency = MagicMock(return_value=False)
        calc._recalculate_base_tax_amounts_ve()

        # base_tax_amount no debería cambiar
        self.assertEqual(tax.base_tax_amount, 999)


# ═══════════════════════════════════════════════════════════════════
# set_cumulative_total()
# ═══════════════════════════════════════════════════════════════════

class TestSetCumulativeTotal(FrappeTestCase):
    """Tests para set_cumulative_total(): acumulación con retenciones VE."""

    def _run_cumulative(self, doc, row_idx, tax) -> None:
        calc = make_taxes_and_totals(doc)
        calc.get_tax_amount_if_for_valuation_or_deduction = MagicMock(
            side_effect=lambda amount, t: amount
        )
        calc.set_cumulative_total(row_idx, tax)

    def test_vat_withholding_subtracts(self) -> None:
        """WHT con charge_type='VAT Withholding' en doc VE → resta del base."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16, total=1160)
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            tax_amount_after_discount_amount=120,
            is_tax_withholding_account=True,
        )
        doc = make_mock_doc(
            doctype="Sales Invoice",
            net_total=1000, items=[], taxes=[vat_tax, wht_tax],
        )

        self._run_cumulative(doc, 1, wht_tax)

        # base=1160 (prev total), tax=120 → total = 1160 - 120 = 1040
        self.assertAlmostEqual(wht_tax.total, 1040.0, places=2)

    def test_islr_subtracts(self) -> None:
        """ISLR con charge_type='ISLR' en doc VE → resta del base."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16, total=1160)
        islr_tax = make_mock_tax(
            charge_type="ISLR", rate=5,
            tax_amount_after_discount_amount=50,
            is_tax_withholding_account=True,
        )
        doc = make_mock_doc(
            doctype="Sales Invoice",
            net_total=1000, items=[], taxes=[vat_tax, islr_tax],
        )

        self._run_cumulative(doc, 1, islr_tax)

        # base=1160 (prev total), ISLR=50 → total = 1160 - 50 = 1110
        self.assertAlmostEqual(islr_tax.total, 1110.0, places=2)

    def test_non_withholding_adds(self) -> None:
        """Impuesto normal (no retención) → suma al base."""
        vat_tax = make_mock_tax(
            charge_type="VAT", rate=16,
            tax_amount_after_discount_amount=160,
        )
        doc = make_mock_doc(net_total=1000, items=[], taxes=[vat_tax])

        self._run_cumulative(doc, 0, vat_tax)

        # base=net_total=1000, tax=160 → total = 1000 + 160 = 1160
        self.assertAlmostEqual(vat_tax.total, 1160.0, places=2)

    def test_first_row_uses_net_total(self) -> None:
        """row_idx=0 → base es net_total."""
        tax = make_mock_tax(
            charge_type="VAT", rate=16,
            tax_amount_after_discount_amount=80,
        )
        doc = make_mock_doc(net_total=500, items=[], taxes=[tax])

        self._run_cumulative(doc, 0, tax)

        self.assertAlmostEqual(tax.total, 580.0, places=2)

    def test_subsequent_row_uses_previous_total(self) -> None:
        """row_idx=1 → base es taxes[0].total."""
        first_tax = make_mock_tax(charge_type="VAT", rate=16, total=1160)
        second_tax = make_mock_tax(
            charge_type="On Net Total", rate=5,
            tax_amount_after_discount_amount=50,
        )
        doc = make_mock_doc(
            net_total=1000, items=[], taxes=[first_tax, second_tax],
        )

        self._run_cumulative(doc, 1, second_tax)

        self.assertAlmostEqual(second_tax.total, 1210.0, places=2)


# ═══════════════════════════════════════════════════════════════════
# calculate_total_exempt()
# ═══════════════════════════════════════════════════════════════════

class TestCalculateTotalExempt(FrappeTestCase):
    """Tests para calculate_total_exempt(): suma de items exentos."""

    def _run_exempt(self, doc) -> None:
        calc = make_taxes_and_totals(doc)
        calc.calculate_total_exempt()

    def test_mixed_items(self) -> None:
        """2 exempt ($50 + $30) + 1 taxable ($100) → total_exempt=80."""
        items = [
            make_mock_item(amount=50, net_amount=50, vat_exempt=True, idx=1),
            make_mock_item(amount=30, net_amount=30, vat_exempt=True, idx=2),
            make_mock_item(amount=100, idx=3),
        ]
        doc = make_mock_doc(items=items)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.total_exempt, 80.0, places=2)

    def test_all_taxable(self) -> None:
        """Todos gravables → total_exempt=0."""
        items = [
            make_mock_item(amount=100, idx=1),
            make_mock_item(amount=200, idx=2),
        ]
        doc = make_mock_doc(items=items)

        self._run_exempt(doc)

        self.assertEqual(doc.total_exempt, 0)

    def test_all_exempt(self) -> None:
        """Todos exentos → total_exempt=suma total."""
        items = [
            make_mock_item(amount=100, net_amount=100, vat_exempt=True, idx=1),
            make_mock_item(amount=200, net_amount=200, vat_exempt=True, idx=2),
        ]
        doc = make_mock_doc(items=items)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.total_exempt, 300.0, places=2)

    def test_base_total_exempt_no_discount(self) -> None:
        """Sin descuento y base_net_amount == amount → base == total_exempt."""
        items = [
            make_mock_item(amount=50, net_amount=50, base_net_amount=50, vat_exempt=True, idx=1),
            make_mock_item(amount=30, net_amount=30, base_net_amount=30, vat_exempt=True, idx=2),
            make_mock_item(amount=100, net_amount=100, base_net_amount=100, idx=3),
        ]
        doc = make_mock_doc(items=items)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.total_exempt, 80.0, places=2)
        self.assertAlmostEqual(doc.base_total_exempt, 80.0, places=2)

    def test_base_total_exempt_multicurrency(self) -> None:
        """USD: base_total_exempt sale de base_net_amount (VEF), NO de total_exempt * tasa.

        base_net_amount (1900) se fija distinto de amount * conversion_rate (50*40=2000)
        para que el test falle si se reintrodujera la fórmula vieja.
        """
        items = [
            make_mock_item(amount=50, net_amount=50, base_net_amount=1900, vat_exempt=True, idx=1),
        ]
        doc = make_mock_doc(items=items, conversion_rate=40)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.total_exempt, 50.0, places=2)
        self.assertAlmostEqual(doc.base_total_exempt, 1900.00, places=2)

    def test_base_total_exempt_with_line_discount(self) -> None:
        """Con descuento de línea, total_exempt y base_total_exempt usan el monto neto."""
        items = [
            make_mock_item(amount=50, net_amount=45, base_net_amount=45, vat_exempt=True, idx=1),
        ]
        doc = make_mock_doc(items=items, conversion_rate=1)

        self._run_exempt(doc)

        # total_exempt usa net_amount (45), no amount (50): si se revierte a bruto, falla
        self.assertAlmostEqual(doc.total_exempt, 45.0, places=2)
        self.assertAlmostEqual(doc.base_total_exempt, 45.0, places=2)

    def test_base_total_exempt_rounding(self) -> None:
        """La suma se redondea a 2 decimales (99.999 → 100.00)."""
        items = [
            make_mock_item(amount=33.333, net_amount=33.333, base_net_amount=33.333, vat_exempt=True, idx=1),
            make_mock_item(amount=33.333, net_amount=33.333, base_net_amount=33.333, vat_exempt=True, idx=2),
            make_mock_item(amount=33.333, net_amount=33.333, base_net_amount=33.333, vat_exempt=True, idx=3),
        ]
        doc = make_mock_doc(items=items)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.base_total_exempt, 100.00, places=2)

    def test_base_total_exempt_invariant(self) -> None:
        """base_net_total - base_total_exempt == suma de base_net_amount no exentas."""
        items = [
            make_mock_item(amount=50, net_amount=50, base_net_amount=2000, vat_exempt=True, idx=1),
            make_mock_item(amount=100, net_amount=100, base_net_amount=4000, idx=2),
        ]
        doc = make_mock_doc(items=items, base_net_total=6000)

        self._run_exempt(doc)

        self.assertAlmostEqual(doc.base_total_exempt, 2000.00, places=2)
        self.assertAlmostEqual(flt(doc.base_net_total) - doc.base_total_exempt, 4000.00, places=2)


# ═══════════════════════════════════════════════════════════════════
# get_current_tax_and_net_amount() — ERPNext v15.121+ compat
# ═══════════════════════════════════════════════════════════════════

class TestGetCurrentTaxAndNetAmount(FrappeTestCase):
    """Tests para get_current_tax_and_net_amount() (compatibilidad ERPNext v15.121+)."""

    def _calc(self, doc, item, tax) -> tuple[float, float]:
        calc = make_taxes_and_totals(doc)
        calc._get_tax_rate = MagicMock(return_value=flt(tax.rate))
        return calc.get_current_tax_and_net_amount(item, tax, {})

    def test_vat_taxable_item(self) -> None:
        """item gravable: net_amount=100, IVA 16% -> (100.0, 16.0)."""
        item = make_mock_item(net_amount=100)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        net, amount = self._calc(doc, item, tax)

        self.assertAlmostEqual(net, 100.0, places=2)
        self.assertAlmostEqual(amount, 16.0, places=2)

    def test_vat_exempt_item(self) -> None:
        """item exento: net_amount=100, vat_exempt=True -> (0.0, 0.0)."""
        item = make_mock_item(net_amount=100, vat_exempt=True)
        tax = make_mock_tax(charge_type="VAT", rate=16)
        doc = make_mock_doc(items=[item], taxes=[tax])

        net, amount = self._calc(doc, item, tax)

        self.assertEqual(net, 0.0)
        self.assertEqual(amount, 0.0)

    def test_vat_withholding_taxable_item(self) -> None:
        """item gravable: net_amount=100, IVA 16%, WHT 75% -> (16.0, 12.0)."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16)
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        item = make_mock_item(net_amount=100)
        doc = make_mock_doc(items=[item], taxes=[vat_tax, wht_tax])

        net, amount = self._calc(doc, item, wht_tax)

        self.assertAlmostEqual(net, 16.0, places=2)
        self.assertAlmostEqual(amount, 12.0, places=2)

    def test_vat_withholding_exempt_item(self) -> None:
        """item exento: vat_exempt=True -> (0.0, 0.0)."""
        vat_tax = make_mock_tax(charge_type="VAT", rate=16)
        wht_tax = make_mock_tax(
            charge_type="VAT Withholding", rate=75,
            is_tax_withholding_account=True,
        )
        item = make_mock_item(net_amount=100, vat_exempt=True)
        doc = make_mock_doc(items=[item], taxes=[vat_tax, wht_tax])

        net, amount = self._calc(doc, item, wht_tax)

        self.assertEqual(net, 0.0)
        self.assertEqual(amount, 0.0)

