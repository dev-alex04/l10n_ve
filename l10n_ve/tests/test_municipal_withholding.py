# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la Retención Municipal (ISAE).

Cubre:
1. calculate_municipal_amount(): fórmula pura de cálculo.
2. get_municipal_withholding_rate(): resolver de alícuotas (Customer rate > fallback VE Municipality Taxes > 0.0).
3. _build_municipal_tax_row(): construcción idempotente de la fila de impuesto.
"""

from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.utils.municipal import (
    calculate_municipal_amount,
    get_municipal_withholding_rate,
)
from l10n_ve.controllers.taxes_mixin import TaxesMixin


class DummySalesInvoice(TaxesMixin, frappe._dict):
    """Documento mínimo para probar los métodos del mixin de impuestos."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.doctype = "Sales Invoice"
        self.taxes = []

    def precision(self, fieldname, parentfield=None):
        return 2


class TestMunicipalWithholding(FrappeTestCase):
    """Suite de pruebas para Retención Municipal (ISAE)."""

    # ─────────────────────────────────────────────
    # 1. calculate_municipal_amount
    # ─────────────────────────────────────────────

    def test_calculate_municipal_amount_basic(self) -> None:
        """net_total=100.0, rate=3.0% → 3.0 USD."""
        amount = calculate_municipal_amount(100.0, 3.0)
        self.assertEqual(amount, 3.0)

    def test_calculate_municipal_amount_rounding(self) -> None:
        """net_total=49.35, rate=3.0% → 1.4805 → 1.48 USD."""
        amount = calculate_municipal_amount(49.35, 3.0)
        self.assertEqual(amount, 1.48)

    def test_calculate_municipal_amount_zero(self) -> None:
        """net_total=0 o rate=0 → 0.0."""
        self.assertEqual(calculate_municipal_amount(0.0, 3.0), 0.0)
        self.assertEqual(calculate_municipal_amount(100.0, 0.0), 0.0)

    # ─────────────────────────────────────────────
    # 2. get_municipal_withholding_rate
    # ─────────────────────────────────────────────

    def test_rate_direct_from_special_customer(self) -> None:
        """Cliente con is_special_taxpayer=1 y alícuota directa en customer → retorna alícuota."""
        with patch("frappe.get_cached_value") as mock_get_val:
            mock_get_val.return_value = (1, 3.5, None)

            rate = get_municipal_withholding_rate("CUST-001")
            self.assertEqual(rate, 3.5)

    def test_rate_fallback_to_municipality_tax(self) -> None:
        """Cliente especial sin alícuota directa pero con municipality_tax → lee de VE Municipality Taxes."""
        def side_effect_get_cached(dt, name, fieldname):
            if dt == "Customer":
                return (1, 0.0, "MUN-TAX-001")
            if dt == "VE Municipality Taxes" and name == "MUN-TAX-001":
                return 2.5
            return None

        with patch("frappe.get_cached_value", side_effect=side_effect_get_cached):
            rate = get_municipal_withholding_rate("CUST-002")
            self.assertEqual(rate, 2.5)

    def test_rate_zero_if_not_special_taxpayer(self) -> None:
        """Cliente no especial (is_special_taxpayer=0) → siempre retorna 0.0%."""
        with patch("frappe.get_cached_value") as mock_get_val:
            mock_get_val.return_value = (0, 3.5, "MUN-TAX-001")

            rate = get_municipal_withholding_rate("CUST-003")
            self.assertEqual(rate, 0.0)

    def test_rate_zero_if_no_customer(self) -> None:
        """Sin customer → retorna 0.0."""
        with patch("frappe.get_cached_value") as mock_get_val:
            mock_get_val.return_value = (0, None, None)

            rate = get_municipal_withholding_rate("")
            self.assertEqual(rate, 0.0)

    # ─────────────────────────────────────────────
    # 3. _build_municipal_tax_row
    # ─────────────────────────────────────────────

    def test_build_municipal_tax_row_success(self) -> None:
        """Construye correctamente la fila de retención municipal."""
        doc = DummySalesInvoice(
            customer="CUST-001",
            company="COMP-001",
            net_total=100.0,
            conversion_rate=771.0,
        )

        with patch("l10n_ve.utils.municipal.get_municipal_withholding_rate", return_value=3.0), \
             patch("frappe.get_cached_value", return_value="2.1.2.9.01 - RETENCION MUNICIPAL"):

            row = doc._build_municipal_tax_row()

            self.assertIsNotNone(row)
            self.assertEqual(row.charge_type, "Municipal Withholding")
            self.assertEqual(row.category, "Total")
            self.assertEqual(row.add_deduct_tax, "Deduct")
            self.assertEqual(row.rate, 3.0)
            self.assertEqual(row.tax_amount, 3.0)
            # base_tax_amount se inicializa en 0.0 para ser calculado por TaxesAndTotals
            self.assertEqual(row.base_tax_amount, 0.0)
            self.assertEqual(row.account_head, "2.1.2.9.01 - RETENCION MUNICIPAL")

    def test_build_municipal_tax_row_fails_closed_without_account(self) -> None:
        """Si la empresa no tiene cuenta configurada, debe lanzar frappe.ValidationError (fail-closed)."""
        doc = DummySalesInvoice(
            customer="CUST-001",
            company="COMP-001",
            net_total=100.0,
        )

        with patch("l10n_ve.utils.municipal.get_municipal_withholding_rate", return_value=3.0), \
             patch("frappe.get_cached_value", return_value=""):

            with self.assertRaises(frappe.ValidationError):
                doc._build_municipal_tax_row()

    def test_build_municipal_tax_row_returns_none_if_rate_zero(self) -> None:
        """Si la alícuota es 0, no construye la fila."""
        doc = DummySalesInvoice(
            customer="CUST-001",
            company="COMP-001",
            net_total=100.0,
        )

        with patch("l10n_ve.utils.municipal.get_municipal_withholding_rate", return_value=0.0):
            row = doc._build_municipal_tax_row()
            self.assertIsNone(row)
