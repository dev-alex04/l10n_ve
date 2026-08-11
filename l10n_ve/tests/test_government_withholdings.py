# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios de las retenciones de entes gubernamentales (timbre / ISAE / Responsabilidad Social)
en CustomPaymentEntry.

Cubre la lógica de riesgo, aislada con mocks de frappe.db:
- la automatización APAGADA (09-ago-2026): ningún tipo propone tarifa y el cobro no crea filas
  ni deducciones, aunque el cliente las tenga habilitadas en su ficha.
- _resolve_withholding_rate con la automatización reactivada: timbre por estado (+umbral),
  Responsabilidad Social flat, y el ISAE que se queda manual igual.
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


def setUpModule() -> None:
    """Aprovisiona el esquema en el site de test para no depender de un `bench migrate` previo.

    Sin el custom field `government_withholdings` en el meta de Payment Entry, `pe.set(...)` NO
    envuelve los dicts en child docs y el acceso por atributo (w.actual_amount) revienta. Se
    sincroniza además el child doctype (que trae `not_withheld`) para que las pruebas del flag
    corran en cualquier site.
    """
    from l10n_ve.setup import create_government_withholding_custom_fields

    frappe.reload_doc("l10n_ve", "doctype", "ve_payment_government_withholding")
    create_government_withholding_custom_fields()
    frappe.clear_cache(doctype="Payment Entry")


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
    """Cálculo por tipo, con la automatización reactivada a propósito.

    En producción está APAGADA (ver TestGovernmentWithholdingAutoCalculationDisabled); estos
    tests cubren la lógica que quedó preservada para cuando se reactive, sobre todo el
    fail-closed del umbral en U.T. del timbre.
    """

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(
            CustomPaymentEntry, "GOV_WITHHOLDING_AUTO_CALCULATION_ENABLED", True
        )
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def test_timbre_ut_threshold_without_active_tax_unit_fails_closed(self) -> None:
        """Umbral en U.T. sin Unidad Tributaria activa: NO debe colapsar a 0 (que aplicaría el
        timbre siempre, incluso bajo el mínimo exento). Debe bloquear con mensaje accionable."""
        pe = _new_pe()
        settings = MagicMock()
        settings.stamp_tax_rates = [
            frappe._dict(state="ST-MIR", rate=0.2, threshold=25, threshold_unit="U.T.", enabled=1),
        ]
        with patch(f"{_MOD}.db.get_value", return_value="Miranda"), \
             patch(f"{_MOD}.get_cached_doc", return_value=settings), \
             patch.object(CustomPaymentEntry, "_current_tax_unit_value", return_value=0.0):
            with self.assertRaises(frappe.ValidationError):
                pe._resolve_withholding_rate({"withholding_type": "Timbre Fiscal", "state": "ST-MIR"}, 5000.0)

    def test_isae_is_never_calculated_automatically(self) -> None:
        """El ISAE se queda manual INCLUSO con la automatización reactivada.

        Antes derivaba la tarifa de `VE Municipality Taxes`; como cada municipio trae 9 alícuotas
        (una por rubro) la sugerencia caía siempre en 0. Ahora ni siquiera se crea la fila de
        retención, y la tabla de alícuotas municipales ya no se consulta desde el pago.
        """
        pe = _new_pe()
        for aliquots in ([1.0, 1.0], [1.0, 2.5, 0.6], []):
            with self.subTest(aliquots=aliquots):
                with patch(f"{_MOD}.db.get_value", return_value="Chacao"), \
                     patch(f"{_MOD}.get_all", return_value=aliquots) as get_all:
                    rate, _ = pe._resolve_withholding_rate(
                        {"withholding_type": "ISAE", "municipality": "M-CH"}, 10000.0
                    )
                self.assertIsNone(rate)
                get_all.assert_not_called()

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
        """Sugerido 0 y sin monto real (tarifa por confirmar) no genera deducción todavía."""
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "ISAE", "jurisdiction": "Chacao", "rate": 0.0,
             "base_amount": 10000, "suggested_amount": 0.0, "actual_amount": 0.0},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        self.assertEqual(len(pe.deductions), 0)

    def test_not_withheld_flag_forces_zero(self) -> None:
        """El flag 'no retenido' fuerza 0 aunque haya un sugerido > 0 (el `or` no lo pisa)."""
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "Timbre Fiscal", "jurisdiction": "Miranda", "rate": 0.2,
             "base_amount": 10000, "suggested_amount": 20.0, "actual_amount": 0.0, "not_withheld": 1},
        ])
        pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")
        self.assertEqual(len(pe.deductions), 0)

    def test_actual_amount_capped_at_base(self) -> None:
        """Un monto real mal tecleado por encima de la base debe bloquear (no inflar el gasto)."""
        pe = _new_pe()
        pe.set("government_withholdings", [
            {"withholding_type": "ISAE", "jurisdiction": "Chacao", "rate": 1.0,
             "base_amount": 100.0, "suggested_amount": 1.0, "actual_amount": 999999.0},
        ])
        with self.assertRaises(frappe.ValidationError):
            pe._sync_withholdings_to_deductions("6.2.01.14 - Test Co")


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


class TestCalculateGovernmentWithholdings(FrappeTestCase):
    """Orquestador: idempotencia (preserva el comprobante y no duplica) y limpieza al no aplicar."""

    def test_rerun_preserves_actual_amount_and_does_not_duplicate(self) -> None:
        pe = _new_pe()
        pe.cost_center = "CC-Test"  # evita el lookup de cost center de la compañía
        pe.append("references", {"allocated_amount": 10000})
        pe.source_exchange_rate = 1
        # side_effect: solo intercepta la consulta de la cuenta (Company); el resto delega al
        # get_value real para no romper el lookup de DocType que hace self.set() al envolver filas.
        real_gv = frappe.db.get_value

        def gv(*a, **k):
            if a and a[0] == "Company":
                return "6.2.01.14 - Test Co"
            return real_gv(*a, **k)

        with patch.object(CustomPaymentEntry, "_get_customer_withholding_config",
                          return_value=[{"withholding_type": "Timbre Fiscal", "state": "ST", "municipality": None}]), \
             patch.object(CustomPaymentEntry, "_resolve_withholding_rate", return_value=(0.2, "Miranda")), \
             patch(f"{_MOD}.db.get_value", side_effect=gv):
            pe.calculate_government_withholdings()
            self.assertEqual(len(pe.government_withholdings), 1)
            self.assertEqual(flt_(pe.government_withholdings[0].suggested_amount), 20.0)
            # el operador captura el monto real del comprobante
            pe.government_withholdings[0].actual_amount = 18.0
            # segunda pasada de validate (re-guardar)
            pe.calculate_government_withholdings()
        self.assertEqual(len(pe.government_withholdings), 1, "no debe duplicar filas")
        self.assertEqual(flt_(pe.government_withholdings[0].actual_amount), 18.0, "preserva el comprobante")
        self.assertEqual(flt_(pe.deductions[0].amount), 18.0, "la deducción usa el monto real")

    def test_switch_to_pay_clears_rows_and_gov_deductions(self) -> None:
        pe = _new_pe(payment_type="Pay")
        pe.set("government_withholdings", [
            {"withholding_type": "Timbre Fiscal", "jurisdiction": "Miranda", "rate": 0.2,
             "base_amount": 10000, "suggested_amount": 20.0, "actual_amount": 0.0},
        ])
        pe.set("deductions", [
            {"account": "6.2.01.14 - Test Co", "amount": 20.0,
             "description": CustomPaymentEntry.GOV_WITHHOLDING_MARKER + " Timbre Fiscal - Miranda"},
            {"account": "Bank Charges", "amount": 5.0, "description": "Comisión banco"},
        ])
        pe.calculate_government_withholdings()
        self.assertEqual(len(pe.government_withholdings), 0, "sin cliente Government no hay filas")
        self.assertEqual([d.description for d in pe.deductions], ["Comisión banco"],
                         "solo se retira la deducción gubernamental, se respeta la otra")


class TestGovernmentWithholdingAutoCalculationDisabled(FrappeTestCase):
    """Estado REAL del módulo: la automatización está apagada y el pago no propone nada."""

    def test_switch_is_off(self) -> None:
        self.assertFalse(CustomPaymentEntry.GOV_WITHHOLDING_AUTO_CALCULATION_ENABLED)

    def test_no_type_resolves_a_rate(self) -> None:
        pe = _new_pe()
        for cfg in (
            {"withholding_type": "Timbre Fiscal", "state": "ST-DC"},
            {"withholding_type": "ISAE", "municipality": "M-CH"},
            {"withholding_type": "Responsabilidad Social"},
        ):
            with self.subTest(tipo=cfg["withholding_type"]):
                rate, _ = pe._resolve_withholding_rate(cfg, 10000.0)
                self.assertIsNone(rate)

    def test_configured_customer_gets_no_rows_nor_deductions(self) -> None:
        """Con las tres retenciones habilitadas en la ficha, el cobro no crea fila ni deducción."""
        pe = _new_pe()
        pe.cost_center = "CC-Test"
        pe.append("references", {"allocated_amount": 10000})
        pe.source_exchange_rate = 1
        real_gv = frappe.db.get_value

        def gv(*a, **k):
            if a and a[0] == "Company":
                return "6.2.01.14 - Test Co"
            return real_gv(*a, **k)

        config = [
            {"withholding_type": "Timbre Fiscal", "state": "ST", "municipality": None},
            {"withholding_type": "ISAE", "state": None, "municipality": "M-CH"},
            {"withholding_type": "Responsabilidad Social", "state": None, "municipality": None},
        ]
        with patch.object(CustomPaymentEntry, "_get_customer_withholding_config", return_value=config), \
             patch(f"{_MOD}.db.get_value", side_effect=gv):
            pe.calculate_government_withholdings()

        self.assertEqual(len(pe.government_withholdings), 0)
        gov_deductions = [
            d for d in (pe.get("deductions") or [])
            if (d.description or "").startswith(CustomPaymentEntry.GOV_WITHHOLDING_MARKER)
        ]
        self.assertEqual(gov_deductions, [])


def flt_(v) -> float:
    from frappe.utils import flt
    return flt(v, 2)
