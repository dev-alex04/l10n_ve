# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la herencia de tasa desde la factura afectada hacia NC/ND
(reemplaza la etapa 2 del retasado a tasa de emisión: decisión de gestión
23-jul-2026 — la nota fiscal usa la misma tasa con la que se certificó la
factura original, no la de su propia fecha de emisión).

Piezas cubiertas:
- _inherit_branch_from_si de NC y ND: hereda branch/debit_to y copia la
  conversion_rate/plc_conversion_rate de la SI (return_against). La tasa
  propia (get_ve_exchange_rate_for_customer) ya no se invoca.
- true_up_credit_note_fx: como las tasas coinciden, el diferencial es 0 y
  no se genera asiento de ajuste. Se mantiene el código para NC creadas a
  mano con otra tasa (regresión).
- validate_note_rate_freshness: guard de emisión fail-closed.
- Wiring en process_invoice: freshness + coherencia para NC/ND; force
  salta ambos.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.digital_invoice import emission_rerate
from l10n_ve.digital_invoice.emission_rerate import (
    RERATE_TAG,
    cancel_credit_note_fx_truing,
    true_up_credit_note_fx,
    validate_note_rate_freshness,
)
from l10n_ve.l10n_ve.doctype.ve_sales_credit_note import (
    ve_sales_credit_note as nc_module,
)
from l10n_ve.l10n_ve.doctype.ve_sales_debit_note import (
    ve_sales_debit_note as nd_module,
)

_SI_RATE = 633.3644
_NOTE_RATE = 653.9726


class FakeNote:
    def __init__(self, is_new=True, **overrides):
        defaults = {
            "doctype": "VE Sales Credit Note",
            "name": "NC-2026-00001",
            "docstatus": 1,
            "customer": "CUST-JUR",
            "company": "COMPANY-TEST",
            "currency": "USD",
            "conversion_rate": _NOTE_RATE,
            "plc_conversion_rate": _NOTE_RATE,
            "grand_total": 100.0,
            "rounded_total": 0,
            "base_grand_total": 65397.26,
            "base_rounded_total": 0,
            "posting_date": "2026-07-16",
            "due_date": None,
            "return_against": "ACC-SINV-2026-00001",
            "branch": None,
            "debit_to": None,
            "cost_center": "Principal - TEST",
            "is_return": 1,
            "is_debit_note": 0,
        }
        defaults.update(overrides)
        self.__dict__.update(defaults)
        self._is_new = is_new

    def is_new(self):
        return self._is_new

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class TestInheritSiRateNC(unittest.TestCase):
    """La NC hereda la conversion_rate de la factura afectada."""

    def _run(self, note, si_values=None):
        si_values = si_values or {
            "branch": "MIR-01",
            "debit_to": "1105001 - CxC - TEST",
            "conversion_rate": _SI_RATE,
            "plc_conversion_rate": _SI_RATE,
            "currency": "USD",
        }
        with patch(
            "frappe.get_cached_value",
            return_value=si_values,
        ) as mock_gcv, patch.object(
            nc_module, "get_ve_exchange_rate_for_customer"
        ) as mock_rate:
            nc_module.VESalesCreditNote._inherit_branch_from_si(note)
        return mock_gcv, mock_rate

    def test_inherits_si_conversion_rate(self):
        note = FakeNote(conversion_rate=0, plc_conversion_rate=0)
        _, mock_rate = self._run(note)
        self.assertEqual(note.conversion_rate, _SI_RATE)
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)
        mock_rate.assert_not_called()

    def test_still_inherits_branch_and_debit_to(self):
        note = FakeNote()
        self._run(note)
        self.assertEqual(note.branch, "MIR-01")
        self.assertEqual(note.debit_to, "1105001 - CxC - TEST")

    def test_no_return_against_is_noop(self):
        note = FakeNote(return_against=None, conversion_rate=777)
        _, mock_rate = self._run(note)
        mock_rate.assert_not_called()
        self.assertEqual(note.conversion_rate, 777)

    def test_existing_doc_keeps_user_rate(self):
        """En docs ya guardados el usuario tiene control: no se pisa la tasa."""
        note = FakeNote(is_new=False, conversion_rate=777)
        _, mock_rate = self._run(note)
        mock_rate.assert_not_called()
        self.assertEqual(note.conversion_rate, 777)

    def test_plc_fallback_to_conversion_rate(self):
        """Si la SI no trae plc_conversion_rate, hereda conversion_rate."""
        note = FakeNote(conversion_rate=0, plc_conversion_rate=0)
        self._run(
            note,
            si_values={
                "branch": "MIR-01",
                "debit_to": "1105001 - CxC - TEST",
                "conversion_rate": _SI_RATE,
                "plc_conversion_rate": 0,
                "currency": "USD",
            },
        )
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)


class TestInheritSiRateND(unittest.TestCase):
    def test_nd_inherits_si_conversion_rate(self):
        note = FakeNote(
            doctype="VE Sales Debit Note",
            conversion_rate=0,
            plc_conversion_rate=0,
        )
        with patch(
            "frappe.get_cached_value",
            return_value={
                "branch": "MIR-01",
                "debit_to": "1105001 - CxC - TEST",
                "conversion_rate": _SI_RATE,
                "plc_conversion_rate": _SI_RATE,
                "currency": "USD",
            },
        ), patch.object(nd_module, "get_ve_exchange_rate_for_customer") as mock_rate:
            nd_module.VESalesDebitNote._inherit_branch_from_si(note)

        self.assertEqual(note.conversion_rate, _SI_RATE)
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)
        self.assertEqual(note.due_date, "2026-07-16")
        mock_rate.assert_not_called()


class TestTrueUpCreditNoteFx(unittest.TestCase):
    def _run(self, note, si_rate=_SI_RATE, si_docstatus=1,
             company_currency="VEF", je_exists=False):
        with patch("frappe.get_cached_value", return_value=company_currency), \
             patch("frappe.db.get_value",
                   return_value=SimpleNamespace(conversion_rate=si_rate,
                                                docstatus=si_docstatus)), \
             patch("frappe.db.exists", return_value=je_exists), \
             patch.object(emission_rerate, "make_fx_adjustment_je") as mock_je:
            true_up_credit_note_fx(note)
        return mock_je

    def test_full_return_rate_up_debits_receivable(self):
        """
        NC de 100 USD a 653.9726 sobre SI a 633.3644: la NC acredita
        2060.82 Bs de más contra la SI → delta = −2060.82 (débito al CxC,
        contrapartida ganancia — la elige make_fx_adjustment_je por signo).
        """
        mock_je = self._run(FakeNote())

        mock_je.assert_called_once()
        kwargs = mock_je.call_args[1]
        self.assertAlmostEqual(kwargs["delta"], -2060.82, places=2)
        self.assertEqual(kwargs["reference_invoice"], "ACC-SINV-2026-00001")
        self.assertIn(RERATE_TAG, kwargs["remark"])
        self.assertIn("NC-2026-00001", kwargs["remark"])

    def test_rate_down_credits_receivable(self):
        """NC a tasa menor acredita de menos → delta positivo (crédito/pérdida)."""
        note = FakeNote(conversion_rate=622.2135, base_grand_total=62221.35)
        mock_je = self._run(note)
        self.assertAlmostEqual(mock_je.call_args[1]["delta"], 1115.09, places=2)

    def test_partial_return_proportional(self):
        note = FakeNote(grand_total=50.0, base_grand_total=32698.63)
        mock_je = self._run(note)
        # 50 USD × (653.9726 − 633.3644) = 1030.41 de sobre-crédito.
        self.assertAlmostEqual(mock_je.call_args[1]["delta"], -1030.41, places=2)

    def test_equal_rates_no_je(self):
        """Naturales intra-mes (misma tasa del 1°): delta 0, sin asiento."""
        note = FakeNote(conversion_rate=_SI_RATE, base_grand_total=63336.44)
        mock_je = self._run(note)
        mock_je.assert_not_called()

    def test_native_currency_no_je(self):
        note = FakeNote(currency="VEF", conversion_rate=1.0)
        mock_je = self._run(note)
        mock_je.assert_not_called()

    def test_draft_affected_invoice_no_je(self):
        mock_je = self._run(FakeNote(), si_docstatus=0)
        mock_je.assert_not_called()

    def test_no_return_against_no_je(self):
        mock_je = self._run(FakeNote(return_against=None))
        mock_je.assert_not_called()

    def test_existing_je_skips_duplicate(self):
        """Amend/reintento: si ya hay un JE vigente de esta NC, no se duplica."""
        mock_je = self._run(FakeNote(), je_exists=True)
        mock_je.assert_not_called()


class TestSameMonthValidation(unittest.TestCase):
    """
    Guard intra-mes reparado: consultaba self.doctype (la nota) en vez de
    la factura original → None → pasaba en silencio; y las notas VE nunca
    lo invocaban. La coincidencia de tasa de naturales (1° del mes)
    depende de este guard.
    """

    @patch("frappe.db.get_value", return_value="2026-07-01")
    def test_cross_month_note_blocks(self, mock_get_value):
        from l10n_ve.utils.utils import validate_return_in_same_month

        note = FakeNote(posting_date="2026-08-05")
        with self.assertRaises(frappe.ValidationError):
            validate_return_in_same_month(note)
        # La consulta va contra la factura ORIGINAL, no el doctype de la
        # nota (primera llamada: frappe.throw dispara otras internas).
        self.assertEqual(mock_get_value.call_args_list[0][0][0], "Sales Invoice")

    @patch("frappe.db.get_value", return_value="2026-07-01")
    def test_same_month_passes(self, _get_value):
        from l10n_ve.utils.utils import validate_return_in_same_month

        validate_return_in_same_month(FakeNote(posting_date="2026-07-16"))

    def test_nc_and_nd_validate_invoke_the_guard(self):
        """Regresión: las notas VE deben invocar el guard en validate()."""
        import inspect

        nc_src = inspect.getsource(nc_module.VESalesCreditNote.validate)
        nd_src = inspect.getsource(nd_module.VESalesDebitNote.validate)
        self.assertIn("validate_return_in_same_month(self)", nc_src)
        self.assertIn("validate_return_in_same_month(self)", nd_src)


class TestOnCancelSingleDefinition(unittest.TestCase):
    """
    Regresión del on_cancel duplicado: Python se queda con la ÚLTIMA
    definición, así que un duplicado deja muerta la primera (pasó con el
    hook de anulación de JEs de ajuste).
    """

    def test_module_has_single_on_cancel(self):
        import inspect

        module_src = inspect.getsource(nc_module)
        self.assertEqual(module_src.count("def on_cancel("), 1)

    def test_live_on_cancel_cancels_truing_and_updates_parent(self):
        import inspect

        src = inspect.getsource(nc_module.VESalesCreditNote.on_cancel)
        self.assertIn("_cancel_fx_truing_entries", src)
        self.assertIn("_update_parent_invoice_status", src)
        self.assertIn("is_void", src)  # el manejo de anulación HKA sigue ahí


class TestCancelCreditNoteFxTruing(unittest.TestCase):
    @patch("frappe.get_doc")
    @patch("frappe.get_all", return_value=["JE-0001"])
    def test_cancels_tagged_jes(self, mock_get_all, mock_get_doc):
        je = MagicMock()
        mock_get_doc.return_value = je

        cancel_credit_note_fx_truing(FakeNote())

        remark_filter = mock_get_all.call_args[1]["filters"]["user_remark"]
        self.assertEqual(remark_filter[0], "like")
        self.assertTrue(remark_filter[1].startswith(
            f"{RERATE_TAG} Ajuste cambiario por NC NC-2026-00001:"
        ))
        self.assertTrue(je.flags.ignore_permissions)
        je.cancel.assert_called_once()

    @patch("frappe.get_doc")
    @patch("frappe.get_all", return_value=[])
    def test_noop_without_jes(self, _get_all, mock_get_doc):
        cancel_credit_note_fx_truing(FakeNote())
        mock_get_doc.assert_not_called()


class TestValidateNoteRateFreshness(unittest.TestCase):
    def _run(self, note, expected_rate=_NOTE_RATE,
             current_date="2026-07-10", target_date="2026-07-16"):
        with patch("frappe.get_cached_value", return_value="VEF"), \
             patch.object(emission_rerate, "get_ve_exchange_rate_for_customer",
                          return_value=expected_rate), \
             patch.object(emission_rerate, "today",
                          return_value="2026-07-16"), \
             patch.object(emission_rerate, "resolve_exchange_rate_date",
                          side_effect=lambda rate, currency: (
                              current_date if abs(rate - _SI_RATE) < 0.001
                              else target_date
                          )):
            validate_note_rate_freshness(note)

    def test_stale_juridical_note_blocks(self):
        """Nota con tasa de otra fecha: bloquea con instrucción de regenerar."""
        note = FakeNote(conversion_rate=_SI_RATE)
        with self.assertRaises(frappe.ValidationError):
            self._run(note)

    def test_fresh_note_passes(self):
        note = FakeNote(conversion_rate=_NOTE_RATE)
        self._run(note, current_date="2026-07-16", target_date="2026-07-16")

    def test_native_currency_passes(self):
        note = FakeNote(currency="VEF", conversion_rate=1.0)
        self._run(note)

    def test_no_rate_available_defers_to_coherencia(self):
        note = FakeNote(conversion_rate=_SI_RATE)
        self._run(note, expected_rate=0.0)


class TestNoteEmissionWiring(unittest.TestCase):
    class _Sentinel(frappe.ValidationError):
        pass

    def _run_process_invoice(self, force):
        from l10n_ve.digital_invoice import tfhka_integration

        doc = FakeNote()
        doc.add_comment = MagicMock()
        freshness_mock = MagicMock()
        rerate_mock = MagicMock(return_value=False)
        with patch("frappe.get_doc", return_value=doc), \
             patch.object(tfhka_integration, "validate_note_rate_freshness",
                          freshness_mock), \
             patch.object(tfhka_integration, "rerate_to_emission_rate",
                          rerate_mock), \
             patch.object(tfhka_integration, "_compute_tasa_fecha",
                          return_value="2026-07-16"), \
             patch.object(tfhka_integration, "_validate_tasa_coherencia",
                          side_effect=self._Sentinel("stop-coherencia")) \
                as coherencia_mock, \
             patch.object(tfhka_integration, "_update_fiscal_dates",
                          side_effect=self._Sentinel("stop-force")), \
             patch.object(tfhka_integration, "getdate",
                          return_value="2026-07-16"):
            with self.assertRaises(self._Sentinel):
                tfhka_integration.process_invoice(
                    "NC-2026-00001", doctype="VE Sales Credit Note",
                    force=force,
                )
        return freshness_mock, rerate_mock, coherencia_mock

    def test_nc_gets_freshness_and_coherencia_not_rerate(self):
        """NC sin force: frescura + coherencia corren; el retasado NO."""
        freshness, rerate, coherencia = self._run_process_invoice(force=False)
        freshness.assert_called_once()
        rerate.assert_not_called()
        coherencia.assert_called_once()

    def test_force_skips_freshness_and_coherencia(self):
        freshness, rerate, coherencia = self._run_process_invoice(force=True)
        freshness.assert_not_called()
        rerate.assert_not_called()
        coherencia.assert_not_called()


if __name__ == "__main__":
    unittest.main()
