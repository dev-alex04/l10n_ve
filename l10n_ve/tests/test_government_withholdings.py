# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios de las retenciones de entes gubernamentales (timbre / ISAE / Responsabilidad Social)
en CustomPaymentEntry.

Cubre la lógica de riesgo, aislada con mocks de frappe.db:
- _resolve_withholding_rate: timbre por estado (+umbral), ISAE por municipio (única vs varias
  alícuotas), Responsabilidad Social flat.
- _sync_withholdings_to_deductions: construye deductions desde las retenciones, prioriza el monto
  real sobre el sugerido, respeta otras deducciones, y es fail-closed (throw sin cuenta).
- _government_withholding_base: prelación de bases.

Se construye un Payment Entry en memoria (frappe.get_doc) para disponer de get/set/append reales;
las consultas a BD se parchean. Requiere que los custom fields/doctypes existan (bench migrate).
"""

from unittest.mock import patch, MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.overrides.payment_entry import CustomPaymentEntry

_MOD = "l10n_ve.overrides.payment_entry.frappe"


def _new_pe(**kwargs) -> CustomPaymentEntry:
    doc = frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": kwargs.get("payment_type", "Receive"),
        "party_type": kwargs.get("party_type", "Customer"),
        "party": kwargs.get("party", "CUST-GOV"),
        "company": kwargs.get("company", "Test Co"),
    })
    return doc


class TestResolveWithholdingRate(FrappeTestCase):
    def test_timbre_rate_from_state(self) -> None:
        pe = _new_pe()
        settings = MagicMock()
        settings.stamp_tax_rates = [
            frappe._dict(state="ST-DC", rate=0.1, threshold=0, threshold_unit="Sin umbral", enabled=1),
        ]
        with patch(f"{_MOD}.db.get_value", return_value="Distrito Capital"), \
             patch(f"{_MOD}.get_cached_doc", return_value=settings):
            rate, label = pe._resolve_withholding_rate({"withholding_type": "Timbre Fiscal", "state": "ST-DC"}, 10000.0)
        self.assertEqual(rate, 0.1)
        self.assertEqual(label, "Distrito Capital")

    def test_timbre_below_threshold_skips(self) -> None:
        pe = _new_pe()
        settings = MagicMock()
        settings.stamp_tax_rates = [
            frappe._dict(state="ST-MIR", rate=0.2, threshold=25, threshold_unit="U.T.", enabled=1),
        ]
        # UT = 40 VEF -> umbral = 25*40 = 1000; base 500 < 1000 -> None
        with patch(f"{_MOD}.db.get_value", return_value="Miranda"), \
             patch(f"{_MOD}.get_cached_doc", return_value=settings), \
             patch.object(CustomPaymentEntry, "_current_tax_unit_value", return_value=40.0):
            rate, label = pe._resolve_withholding_rate({"withholding_type": "Timbre Fiscal", "state": "ST-MIR"}, 500.0)
        self.assertIsNone(rate)

    def test_timbre_above_threshold_applies(self) -> None:
        pe = _new_pe()
        settings = MagicMock()
        settings.stamp_tax_rates = [
            frappe._dict(state="ST-MIR", rate=0.2, threshold=25, threshold_unit="U.T.", enabled=1),
        ]
        with patch(f"{_MOD}.db.get_value", return_value="Miranda"), \
             patch(f"{_MOD}.get_cached_doc", return_value=settings), \
             patch.object(CustomPaymentEntry, "_current_tax_unit_value", return_value=40.0):
            rate, _ = pe._resolve_withholding_rate({"withholding_type": "Timbre Fiscal", "state": "ST-MIR"}, 5000.0)
        self.assertEqual(rate, 0.2)

    def test_isae_single_aliquot(self) -> None:
        pe = _new_pe()
        with patch(f"{_MOD}.db.get_value", return_value="Chacao"), \
             patch(f"{_MOD}.get_all", return_value=[1.0, 1.0]):
            rate, label = pe._resolve_withholding_rate({"withholding_type": "ISAE", "municipality": "M-CH"}, 10000.0)
        self.assertEqual(rate, 1.0)
        self.assertEqual(label, "Chacao")

    def test_isae_multiple_aliquots_returns_zero(self) -> None:
        """Varias alícuotas por rubro -> no sugerir (0); el comprobante manda."""
        pe = _new_pe()
        with patch(f"{_MOD}.db.get_value", return_value="Chacao"), \
             patch(f"{_MOD}.get_all", return_value=[1.0, 2.5, 0.6]):
            rate, _ = pe._resolve_withholding_rate({"withholding_type": "ISAE", "municipality": "M-CH"}, 10000.0)
        self.assertEqual(rate, 0.0)

    def test_isae_no_rates_skips(self) -> None:
        pe = _new_pe()
        with patch(f"{_MOD}.db.get_value", return_value="X"), \
             patch(f"{_MOD}.get_all", return_value=[]):
            rate, _ = pe._resolve_withholding_rate({"withholding_type": "ISAE", "municipality": "M-X"}, 10000.0)
        self.assertIsNone(rate)

    def test_responsibility_social_flat(self) -> None:
        pe = _new_pe()
        with patch(f"{_MOD}.db.get_single_value", return_value=3.0):
            rate, label = pe._resolve_withholding_rate({"withholding_type": "Responsabilidad Social"}, 10000.0)
        self.assertEqual(rate, 3.0)
        self.assertEqual(label, "Nacional")


class TestSyncWithholdingsToDeductions(FrappeTestCase):
    def test_builds_deduction_from_suggested(self) -> None:
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "Timbre Fiscal", "jurisdiction": "Miranda", "rate": 0.2,
             "base_amount": 10000, "suggested_amount": 20.0, "actual_amount": 0.0},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        self.assertEqual(len(pe.deductions), 1)
        self.assertEqual(flt_(pe.deductions[0].amount), 20.0)
        self.assertTrue(pe.deductions[0].description.startswith(CustomPaymentEntry.GOV_WITHHOLDING_MARKER))

    def test_actual_amount_overrides_suggested(self) -> None:
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "ISAE", "jurisdiction": "Chacao", "rate": 1.0,
             "base_amount": 10000, "suggested_amount": 100.0, "actual_amount": 98.5},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        self.assertEqual(flt_(pe.deductions[0].amount), 98.5)

    def test_preserves_other_deductions(self) -> None:
        pe = _new_pe()
        pe.set("deductions", [{"account": "Bank Charges", "amount": 5.0, "description": "Comisión banco"}])
        pe.set("government_withholdings", [
            {"withholding_type": "Timbre Fiscal", "jurisdiction": "Miranda", "rate": 0.2,
             "base_amount": 10000, "suggested_amount": 20.0, "actual_amount": 0.0},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        descs = [d.description for d in pe.deductions]
        self.assertIn("Comisión banco", descs)
        self.assertEqual(len(pe.deductions), 2)

    def test_fail_closed_without_account(self) -> None:
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "Timbre Fiscal", "jurisdiction": "Miranda", "rate": 0.2,
             "base_amount": 10000, "suggested_amount": 20.0, "actual_amount": 0.0},
        ])
        with self.assertRaises(frappe.ValidationError):
            pe._sync_withholdings_to_deductions(None)

    def test_zero_amount_skipped(self) -> None:
        """Sugerido 0 y sin monto real (ej. ISAE ambiguo) no genera deducción todavía."""
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "ISAE", "jurisdiction": "Chacao", "rate": 0.0,
             "base_amount": 10000, "suggested_amount": 0.0, "actual_amount": 0.0},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        self.assertEqual(len(pe.deductions), 0)


class TestGovernmentWithholdingBase(FrappeTestCase):
    def test_prefers_allocated_references(self) -> None:
        pe = _new_pe()
        pe.append("references", {"allocated_amount": 1000})
        pe.source_exchange_rate = 1
        self.assertEqual(pe._government_withholding_base(), 1000)

    def test_falls_back_to_paid_amount(self) -> None:
        pe = _new_pe()
        pe.paid_amount = 990
        pe.source_exchange_rate = 1
        self.assertEqual(pe._government_withholding_base(), 990)

    def test_applies_source_exchange_rate(self) -> None:
        pe = _new_pe()
        pe.append("references", {"allocated_amount": 100})
        pe.source_exchange_rate = 40
        self.assertEqual(pe._government_withholding_base(), 4000)


def flt_(v) -> float:
    from frappe.utils import flt
    return flt(v, 2)
