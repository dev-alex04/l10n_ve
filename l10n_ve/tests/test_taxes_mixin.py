# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para TaxesMixin.

Cubre:
- validate_tax_structure(): limpieza de taxes cuando todo es exento o sin VAT
- _sort_and_reindex_taxes(): ordenamiento fiscal (VAT → WHT → ISLR)
- calculate_total_withholding(): suma de retenciones
- _set_base_total_with_vat(): asignación de base_total_with_vat
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from l10n_ve.tests.helpers import make_mock_tax, MockDoc
from l10n_ve.controllers.taxes_mixin import TaxesMixin


def _make_mixin_instance(**overrides) -> MockDoc:
    """Crea un objeto mock que simula un doc con TaxesMixin.

    Usa MockDoc para evitar conflicto con dict.items(), e incluye
    _TAX_SORT_PRIORITY de TaxesMixin para los tests de ordenamiento.
    """
    defaults = {
        "items": [],
        "taxes": [],
        "taxes_and_charges": "Test Tax Template",
        "apply_tds": 0,
        "base_net_total": 0.0,
        "base_total_with_vat": 0.0,
        "_TAX_SORT_PRIORITY": TaxesMixin._TAX_SORT_PRIORITY,
    }
    defaults.update(overrides)
    obj = MockDoc(**defaults)

    def _set(field: str, value) -> None:
        setattr(obj, field, value)

    obj.set = _set
    return obj


# ═══════════════════════════════════════════════════════════════════
# validate_tax_structure()
# ═══════════════════════════════════════════════════════════════════

class TestValidateTaxStructure(FrappeTestCase):
    """Tests para validate_tax_structure(): limpieza fiscal."""

    def _validate(self, obj) -> None:
        from l10n_ve.controllers.taxes_mixin import TaxesMixin
        TaxesMixin.validate_tax_structure(obj)

    def test_clears_taxes_when_all_exempt(self) -> None:
        """Todos items exentos + template asignado → taxes=[], apply_tds=0."""
        obj = _make_mixin_instance(
            items=[
                frappe._dict({"vat_exempt": True}),
                frappe._dict({"vat_exempt": True}),
            ],
            taxes=[make_mock_tax(charge_type="VAT", rate=16)],
            taxes_and_charges="IVA 16%",
            apply_tds=1,
        )

        self._validate(obj)

        self.assertEqual(obj.taxes, [])
        self.assertEqual(obj.apply_tds, 0)
        self.assertIsNone(obj.taxes_and_charges)

    def test_preserves_taxes_when_taxable(self) -> None:
        """Al menos 1 item gravable → taxes preservados."""
        vat = make_mock_tax(charge_type="VAT", rate=16)
        obj = _make_mixin_instance(
            items=[
                frappe._dict({"vat_exempt": False}),
                frappe._dict({"vat_exempt": True}),
            ],
            taxes=[vat],
            taxes_and_charges="IVA 16%",
            apply_tds=1,
        )

        self._validate(obj)

        self.assertEqual(len(obj.taxes), 1)
        self.assertEqual(obj.apply_tds, 1)

    def test_clears_tds_when_no_vat(self) -> None:
        """apply_tds=1 pero sin fila VAT → taxes=[], apply_tds=0."""
        non_vat = make_mock_tax(charge_type="On Net Total", rate=10)
        obj = _make_mixin_instance(
            items=[frappe._dict({"vat_exempt": False})],
            taxes=[non_vat],
            taxes_and_charges="",
            apply_tds=1,
        )

        self._validate(obj)

        self.assertEqual(obj.taxes, [])
        self.assertEqual(obj.apply_tds, 0)

    def test_no_change_when_valid(self) -> None:
        """Item gravable + VAT + apply_tds=1 → sin cambio."""
        vat = make_mock_tax(charge_type="VAT", rate=16)
        obj = _make_mixin_instance(
            items=[frappe._dict({"vat_exempt": False})],
            taxes=[vat],
            taxes_and_charges="IVA 16%",
            apply_tds=1,
        )

        self._validate(obj)

        self.assertEqual(len(obj.taxes), 1)
        self.assertEqual(obj.apply_tds, 1)


# ═══════════════════════════════════════════════════════════════════
# _sort_and_reindex_taxes()
# ═══════════════════════════════════════════════════════════════════

class TestSortAndReindexTaxes(FrappeTestCase):
    """Tests para _sort_and_reindex_taxes(): ordenamiento fiscal."""

    def _sort(self, obj) -> None:
        from l10n_ve.controllers.taxes_mixin import TaxesMixin
        TaxesMixin._sort_and_reindex_taxes(obj)

    def test_sort_vat_before_withholding_before_islr(self) -> None:
        """[ISLR, WHT, VAT] → [VAT, WHT, ISLR]."""
        islr = make_mock_tax(charge_type="ISLR", rate=5)
        wht = make_mock_tax(charge_type="VAT Withholding", rate=75)
        vat = make_mock_tax(charge_type="VAT", rate=16)
        obj = _make_mixin_instance(taxes=[islr, wht, vat])

        self._sort(obj)

        self.assertEqual(obj.taxes[0].charge_type, "VAT")
        self.assertEqual(obj.taxes[1].charge_type, "VAT Withholding")
        self.assertEqual(obj.taxes[2].charge_type, "ISLR")

    def test_reindex_assigns_sequential_idx(self) -> None:
        """Después de ordenar, idx = [1, 2, 3]."""
        vat = make_mock_tax(charge_type="VAT", rate=16)
        wht = make_mock_tax(charge_type="VAT Withholding", rate=75)
        islr = make_mock_tax(charge_type="ISLR", rate=5)
        obj = _make_mixin_instance(taxes=[vat, wht, islr])

        self._sort(obj)

        for i, tax in enumerate(obj.taxes, start=1):
            self.assertEqual(tax.idx, i)

    def test_empty_taxes_no_error(self) -> None:
        """taxes=[] → sin error."""
        obj = _make_mixin_instance(taxes=[])

        self._sort(obj)

        self.assertEqual(obj.taxes, [])

    def test_same_priority_preserves_order(self) -> None:
        """[On Net Total, VAT, Actual] → todos prioridad 0, orden relativo preservado."""
        ont = make_mock_tax(charge_type="On Net Total", rate=10)
        vat = make_mock_tax(charge_type="VAT", rate=16)
        actual = make_mock_tax(charge_type="Actual", rate=0, tax_amount=50)
        obj = _make_mixin_instance(taxes=[ont, vat, actual])

        self._sort(obj)

        # Todos tienen prioridad 0, Python sort es estable
        types: list[str] = [t.charge_type for t in obj.taxes]
        self.assertEqual(types, ["On Net Total", "VAT", "Actual"])


# ═══════════════════════════════════════════════════════════════════
# calculate_total_withholding()
# ═══════════════════════════════════════════════════════════════════

class TestCalculateTotalWithholding(FrappeTestCase):
    """Tests para calculate_total_withholding(): suma de retenciones."""

    def _calc(self, obj) -> None:
        from l10n_ve.controllers.taxes_mixin import TaxesMixin
        TaxesMixin.calculate_total_withholding(obj)

    def test_sums_only_withholding_taxes(self) -> None:
        """WHT=100 + ISLR=50 + VAT=16 → total_withholding=150."""
        obj = _make_mixin_instance(
            total_withholding=0.0,
            taxes=[
                make_mock_tax(
                    charge_type="VAT Withholding", rate=75,
                    tax_amount=100, is_tax_withholding_account=True,
                ),
                make_mock_tax(
                    charge_type="ISLR", rate=5,
                    tax_amount=50, is_tax_withholding_account=True,
                ),
                make_mock_tax(
                    charge_type="VAT", rate=16, tax_amount=16,
                ),
            ],
        )

        self._calc(obj)

        self.assertAlmostEqual(obj.total_withholding, 150.0, places=2)

    def test_zero_when_no_withholding(self) -> None:
        """Solo taxes normales → total_withholding=0."""
        obj = _make_mixin_instance(
            total_withholding=0.0,
            taxes=[
                make_mock_tax(charge_type="VAT", rate=16, tax_amount=160),
            ],
        )

        self._calc(obj)

        self.assertEqual(obj.total_withholding, 0.0)

    def test_empty_taxes(self) -> None:
        """taxes=[] → total_withholding=0."""
        obj = _make_mixin_instance(total_withholding=0.0, taxes=[])

        self._calc(obj)

        self.assertEqual(obj.total_withholding, 0.0)


# ═══════════════════════════════════════════════════════════════════
# _set_base_total_with_vat()
# ═══════════════════════════════════════════════════════════════════

class TestSetBaseTotalWithVat(FrappeTestCase):
    """Tests para _set_base_total_with_vat(): base imponible + IVA."""

    def _set_base(self, obj) -> None:
        from l10n_ve.controllers.taxes_mixin import TaxesMixin
        TaxesMixin._set_base_total_with_vat(obj)

    def test_uses_vat_base_total(self) -> None:
        """Tax VAT con base_total=42340 → base_total_with_vat=42340."""
        obj = _make_mixin_instance(
            base_net_total=36500,
            base_total_with_vat=0.0,
            taxes=[
                make_mock_tax(
                    charge_type="VAT", rate=16,
                    base_total=42340,
                ),
            ],
        )

        self._set_base(obj)

        self.assertAlmostEqual(obj.base_total_with_vat, 42340.0, places=2)

    def test_fallback_to_base_net_total(self) -> None:
        """Sin fila VAT → base_total_with_vat = base_net_total."""
        obj = _make_mixin_instance(
            base_net_total=36500,
            base_total_with_vat=0.0,
            taxes=[
                make_mock_tax(charge_type="On Net Total", rate=10),
            ],
        )

        self._set_base(obj)

        self.assertAlmostEqual(obj.base_total_with_vat, 36500.0, places=2)

    def test_empty_taxes_uses_base_net_total(self) -> None:
        """taxes=[] → base_total_with_vat = base_net_total."""
        obj = _make_mixin_instance(
            base_net_total=1000,
            base_total_with_vat=0.0,
            taxes=[],
        )

        self._set_base(obj)

        self.assertAlmostEqual(obj.base_total_with_vat, 1000.0, places=2)
