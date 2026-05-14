# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de integración para el flujo ISLR del TaxesMixin.

Cubre:
- set_islr_withholding_ve(): flujo automático en ventas
- _build_islr_tax_row(): construcción de fila ISLR para ventas (sin args)
- _build_purchase_islr_tax_row(): construcción de fila ISLR para compras (con args)
- Coexistencia: ambos métodos deben existir sin colisión de nombres

Contexto: un merge introdujo dos métodos con el mismo nombre
(_build_islr_tax_row) que Python resolvía tomando solo el último,
rompiendo el flujo de ventas. Estos tests previenen regresiones.
"""

import frappe
from frappe import _dict
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from unittest.mock import patch, MagicMock

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.tests.helpers import MockDoc, make_mock_tax


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _make_sales_mixin(**overrides) -> MockDoc:
    """Crea un mock de Sales Invoice con TaxesMixin habilitado."""
    defaults: dict = {
        "doctype": "Sales Invoice",
        "company": "Test Company",
        "customer": "CUST-001",
        "total": 1000.0,
        "taxes": [],
        "is_return": 0,
        "return_against": None,
        "is_debit_note": 0,
        "_TAX_SORT_PRIORITY": TaxesMixin._TAX_SORT_PRIORITY,
    }
    defaults.update(overrides)
    obj = MockDoc(**defaults)

    # Simular append() de frappe.Document
    def _append(table: str, row) -> None:
        current: list = getattr(obj, table, [])
        current.append(row)
        setattr(obj, table, current)

    obj.append = _append
    return obj


def _make_purchase_mixin(**overrides) -> MockDoc:
    """Crea un mock de Purchase Invoice con TaxesMixin habilitado."""
    defaults: dict = {
        "doctype": "Purchase Invoice",
        "company": "Test Company",
        "supplier": "SUPP-001",
        "total": 5000.0,
        "taxes": [],
        "_TAX_SORT_PRIORITY": TaxesMixin._TAX_SORT_PRIORITY,
    }
    defaults.update(overrides)
    obj = MockDoc(**defaults)

    def _append(table: str, row) -> None:
        current: list = getattr(obj, table, [])
        current.append(row)
        setattr(obj, table, current)

    obj.append = _append
    return obj


def _make_mock_tabulator(
    name: str = "34",
    codigo: str = "034",
    descripcion: str = "Servicios de telecomunicaciones",
) -> _dict:
    """Crea un tabulador ISLR mock."""
    return _dict({
        "name": name,
        "codigo": codigo,
        "descripcion": descripcion,
    })


def _make_mock_aliquot(
    aliquot: float = 5.0,
    percentage_base: float = 100.0,
    subtracting: float = 0.0,
    types_of_person: str = "PNR",
) -> _dict:
    """Crea una alícuota ISLR mock."""
    return _dict({
        "aliquot": aliquot,
        "percentage_base": percentage_base,
        "subtracting": subtracting,
        "types_of_person": types_of_person,
    })


# ═══════════════════════════════════════════════════════════════════
# Coexistencia de métodos (regresión)
# ═══════════════════════════════════════════════════════════════════

class TestISLRMethodCoexistence(FrappeTestCase):
    """Verifica que ambos métodos _build_islr_tax_row y
    _build_purchase_islr_tax_row coexisten sin colisión."""

    def test_sales_method_exists_without_extra_args(self) -> None:
        """_build_islr_tax_row(self) debe aceptar solo self."""
        import inspect
        sig = inspect.signature(TaxesMixin._build_islr_tax_row)
        # Solo 'self', sin parámetros adicionales requeridos
        params: list[str] = [
            p.name for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
        ]
        self.assertEqual(params, ["self"])

    def test_purchase_method_exists_with_four_args(self) -> None:
        """_build_purchase_islr_tax_row(self, ...) debe requerir 4 args extra."""
        import inspect
        sig = inspect.signature(TaxesMixin._build_purchase_islr_tax_row)
        params: list[str] = [
            p.name for p in sig.parameters.values()
            if p.default is inspect.Parameter.empty
        ]
        self.assertEqual(
            params,
            ["self", "tabulator", "aliquot_info", "islr_amount", "islr_account"]
        )

    def test_both_methods_are_different_objects(self) -> None:
        """Las funciones no deben ser el mismo objeto (colisión de nombres)."""
        self.assertIsNot(
            TaxesMixin._build_islr_tax_row,
            TaxesMixin._build_purchase_islr_tax_row,
        )


# ═══════════════════════════════════════════════════════════════════
# set_islr_withholding_ve() — Flujo ventas
# ═══════════════════════════════════════════════════════════════════

class TestSetISLRWithholdingVeSales(FrappeTestCase):
    """Tests para set_islr_withholding_ve() en Sales Invoice."""

    @patch("l10n_ve.controllers.taxes_mixin.frappe.get_cached_value")
    @patch("l10n_ve.utils.islr.get_islr_aliquot")
    @patch("l10n_ve.utils.islr.calculate_islr_amount")
    def test_adds_islr_row_for_eligible_customer(
        self,
        mock_calc: MagicMock,
        mock_aliquot: MagicMock,
        mock_cached: MagicMock,
    ) -> None:
        """Customer con ISLR configurado → se agrega fila ISLR a taxes."""
        tabulator = _make_mock_tabulator()
        aliquot = _make_mock_aliquot(aliquot=5.0, percentage_base=100.0)

        mock_aliquot.return_value = (aliquot, tabulator)
        mock_cached.return_value = "5000 - ISLR por Pagar - TC"
        mock_calc.return_value = 50.0

        obj = _make_sales_mixin(total=1000.0)
        TaxesMixin.set_islr_withholding_ve(obj)

        self.assertEqual(len(obj.taxes), 1)
        row = obj.taxes[0]
        self.assertEqual(row["charge_type"], "ISLR")
        self.assertEqual(row["tax_amount"], 50.0)
        self.assertEqual(row["account_head"], "5000 - ISLR por Pagar - TC")
        self.assertTrue(row["is_tax_withholding_account"])

    @patch("l10n_ve.controllers.taxes_mixin.frappe.get_cached_value")
    @patch("l10n_ve.utils.islr.get_islr_aliquot")
    def test_no_row_when_no_aliquot(
        self,
        mock_aliquot: MagicMock,
        mock_cached: MagicMock,
    ) -> None:
        """Customer sin ISLR configurado → no agrega fila."""
        mock_aliquot.return_value = None

        obj = _make_sales_mixin()
        TaxesMixin.set_islr_withholding_ve(obj)

        self.assertEqual(len(obj.taxes), 0)

    @patch("l10n_ve.controllers.taxes_mixin.frappe.get_cached_value")
    @patch("l10n_ve.utils.islr.get_islr_aliquot")
    def test_no_row_when_no_account(
        self,
        mock_aliquot: MagicMock,
        mock_cached: MagicMock,
    ) -> None:
        """Compañía sin cuenta ISLR → no agrega fila."""
        tabulator = _make_mock_tabulator()
        aliquot = _make_mock_aliquot()

        mock_aliquot.return_value = (aliquot, tabulator)
        mock_cached.return_value = ""

        obj = _make_sales_mixin()
        TaxesMixin.set_islr_withholding_ve(obj)

        self.assertEqual(len(obj.taxes), 0)

    @patch("l10n_ve.controllers.taxes_mixin.frappe.get_cached_value")
    @patch("l10n_ve.utils.islr.get_islr_aliquot")
    @patch("l10n_ve.utils.islr.calculate_islr_amount")
    def test_no_row_when_amount_zero(
        self,
        mock_calc: MagicMock,
        mock_aliquot: MagicMock,
        mock_cached: MagicMock,
    ) -> None:
        """Monto ISLR calculado = 0 → no agrega fila."""
        tabulator = _make_mock_tabulator()
        aliquot = _make_mock_aliquot()

        mock_aliquot.return_value = (aliquot, tabulator)
        mock_cached.return_value = "5000 - ISLR - TC"
        mock_calc.return_value = 0.0

        obj = _make_sales_mixin()
        TaxesMixin.set_islr_withholding_ve(obj)

        self.assertEqual(len(obj.taxes), 0)

    def test_skips_purchase_doctypes(self) -> None:
        """Purchase Invoice → no ejecuta lógica de ventas."""
        obj = _make_purchase_mixin()
        TaxesMixin.set_islr_withholding_ve(obj)

        # No debería agregar nada ni lanzar error
        self.assertEqual(len(obj.taxes), 0)

    @patch("l10n_ve.controllers.taxes_mixin.frappe.get_cached_value")
    @patch("l10n_ve.utils.islr.get_islr_aliquot")
    @patch("l10n_ve.utils.islr.calculate_islr_amount")
    def test_replaces_existing_islr_rows(
        self,
        mock_calc: MagicMock,
        mock_aliquot: MagicMock,
        mock_cached: MagicMock,
    ) -> None:
        """Si ya existían filas ISLR → las reemplaza con la nueva."""
        tabulator = _make_mock_tabulator()
        aliquot = _make_mock_aliquot()

        mock_aliquot.return_value = (aliquot, tabulator)
        mock_cached.return_value = "5000 - ISLR - TC"
        mock_calc.return_value = 75.0

        old_islr = make_mock_tax(charge_type="ISLR", rate=3, tax_amount=30)
        vat = make_mock_tax(charge_type="VAT", rate=16, tax_amount=160)
        obj = _make_sales_mixin(taxes=[old_islr, vat])

        TaxesMixin.set_islr_withholding_ve(obj)

        # VAT preservado + nueva ISLR = 2 filas
        self.assertEqual(len(obj.taxes), 2)
        types: list[str] = [t.get("charge_type", t["charge_type"]) for t in obj.taxes]
        self.assertIn("VAT", types)
        self.assertIn("ISLR", types)

        islr_rows = [t for t in obj.taxes if t.get("charge_type") == "ISLR"]
        self.assertEqual(len(islr_rows), 1)
        self.assertEqual(islr_rows[0]["tax_amount"], 75.0)


# ═══════════════════════════════════════════════════════════════════
# _build_purchase_islr_tax_row() — Flujo compras
# ═══════════════════════════════════════════════════════════════════

class TestBuildPurchaseISLRTaxRow(FrappeTestCase):
    """Tests para _build_purchase_islr_tax_row() con argumentos explícitos."""

    def test_builds_row_with_all_fields(self) -> None:
        """Retorna dict con todos los campos esperados para Purchase Taxes."""
        tabulator = _make_mock_tabulator(
            name="34", codigo="034", descripcion="Telecomunicaciones"
        )
        aliquot = _make_mock_aliquot(
            aliquot=5.0, percentage_base=100.0, subtracting=83.33
        )
        obj = _make_purchase_mixin()

        result: dict = TaxesMixin._build_purchase_islr_tax_row(
            obj, tabulator, aliquot, 166.67, "4100 - ISLR Compras - TC"
        )

        self.assertEqual(result["charge_type"], "ISLR")
        self.assertEqual(result["add_deduct_tax"], "Deduct")
        self.assertEqual(result["account_head"], "4100 - ISLR Compras - TC")
        self.assertEqual(result["tax_amount"], 166.67)
        self.assertAlmostEqual(result["rate"], 5.0)
        self.assertAlmostEqual(result["percentage_base"], 100.0)
        self.assertAlmostEqual(result["subtracting"], 83.33)
        self.assertEqual(result["code"], "034")
        self.assertEqual(result["tabulator_islr"], "34")
        self.assertTrue(result["is_tax_withholding_account"])

    def test_includes_purchase_specific_fields(self) -> None:
        """Verifica campos exclusivos de compras (code, tabulator_islr)."""
        tabulator = _make_mock_tabulator(name="99", codigo="099")
        aliquot = _make_mock_aliquot()
        obj = _make_purchase_mixin()

        result: dict = TaxesMixin._build_purchase_islr_tax_row(
            obj, tabulator, aliquot, 50.0, "4100 - ISLR - TC"
        )

        self.assertIn("code", result)
        self.assertIn("tabulator_islr", result)
        self.assertEqual(result["code"], "099")
        self.assertEqual(result["tabulator_islr"], "99")
