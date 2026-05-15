# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para calculate_islr_amount().

Valida la fórmula fiscal ISLR venezolana de forma pura (sin mocks, sin BD):
    base = total × (percentage_base / 100)
    islr = (base × aliquot / 100) − sustraendo
    resultado = max(islr, 0), redondeado a 2 decimales
"""

from frappe.tests.utils import FrappeTestCase

from l10n_ve.utils.islr import calculate_islr_amount
from l10n_ve.tests.helpers import make_mock_aliquot


class TestCalculateISLRAmount(FrappeTestCase):
    """Tests para calculate_islr_amount(): fórmula fiscal pura."""

    # ─────────────────────────────────────────────
    # Casos básicos
    # ─────────────────────────────────────────────

    def test_basic_islr(self) -> None:
        """total=1000, base=100%, alícuota=5%, sustraendo=0 → 50.0."""
        aliquot = make_mock_aliquot(100, 5, 0)

        result: float = calculate_islr_amount(1000, aliquot)

        self.assertEqual(result, 50.0)

    def test_islr_with_partial_base(self) -> None:
        """total=1000, base=50%, alícuota=5%, sustraendo=0 → 25.0."""
        aliquot = make_mock_aliquot(50, 5, 0)

        result: float = calculate_islr_amount(1000, aliquot)

        self.assertEqual(result, 25.0)

    def test_islr_with_subtracting(self) -> None:
        """total=10000, base=100%, alícuota=34%, sustraendo=583.34 → 2816.66."""
        aliquot = make_mock_aliquot(100, 34, 583.34)

        result: float = calculate_islr_amount(10000, aliquot)

        self.assertEqual(result, 2816.66)

    def test_islr_with_conversion_rate(self) -> None:
        """total=100 USD, base=100%, alícuota=34%, sustraendo=583.34 VEF, tasa=50.0.
        sustraendo_ref = 583.34 / 50.0 = 11.6668
        islr = (100 * 34%) - 11.6668 = 34 - 11.6668 = 22.3332 -> 22.33"""
        aliquot = make_mock_aliquot(100, 34, 583.34)

        result: float = calculate_islr_amount(100, aliquot, conversion_rate=50.0)

        self.assertEqual(result, 22.33)

    # ─────────────────────────────────────────────
    # Edge cases
    # ─────────────────────────────────────────────

    def test_islr_floor_at_zero(self) -> None:
        """Sustraendo mayor que impuesto calculado → resultado 0 (no negativo)."""
        aliquot = make_mock_aliquot(100, 1, 50)

        result: float = calculate_islr_amount(100, aliquot)

        self.assertEqual(result, 0)

    def test_islr_zero_total(self) -> None:
        """total=0 → 0 independientemente de alícuota."""
        aliquot = make_mock_aliquot(100, 5, 0)

        result: float = calculate_islr_amount(0, aliquot)

        self.assertEqual(result, 0)

    def test_islr_precision_rounding(self) -> None:
        """total=999.99, base=100%, alícuota=5% → 50.0 (redondeado a 2 dec)."""
        aliquot = make_mock_aliquot(100, 5, 0)

        result: float = calculate_islr_amount(999.99, aliquot)

        self.assertEqual(result, 50.0)

    def test_islr_percentage_base_zero(self) -> None:
        """base=0% → 0 independientemente de total y alícuota."""
        aliquot = make_mock_aliquot(0, 5, 0)

        result: float = calculate_islr_amount(1000, aliquot)

        self.assertEqual(result, 0)

    # ─────────────────────────────────────────────
    # Escenarios reales de producción
    # ─────────────────────────────────────────────

    def test_islr_real_scenario_p051(self) -> None:
        """Escenario real P051: total=194478.20, base=100%, alícuota=5% → 9723.91."""
        aliquot = make_mock_aliquot(100, 5, 0)

        result: float = calculate_islr_amount(194478.20, aliquot)

        self.assertEqual(result, 9723.91)
