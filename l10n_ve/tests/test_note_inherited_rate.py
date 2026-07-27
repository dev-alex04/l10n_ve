# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests de la tasa de cambio de las notas fiscales VE: NC y ND toman la tasa de
la factura afectada (24-jul-2026), reemplazando la regla de tasa propia del
16-jul-2026.

Piezas cubiertas:
- _inherit_branch_from_si de la NC: hereda branch/debit_to y fija la tasa de
  la factura como INVARIANTE (se re-aplica también sobre borradores ya
  guardados, porque el read_only de la UI no cubre API/imports).
- _inherit_branch_from_si de la ND: la tasa de la factura es solo el valor por
  defecto del borrador nuevo; el campo queda editable y cae a la tasa de la
  fecha propia si la factura no trae una utilizable.
- validate_note_rate: guard de emisión. Bloquea la NC que llegue con una tasa
  distinta a la de su factura afectada; la ND no lo activa (tasa editable por
  diseño, su par tasa/fecha lo valida _validate_tasa_coherencia).
- on_submit de la NC: ya NO postea asiento de ajuste cambiario (con la tasa
  heredada el diferencial es cero por construcción).
- cancel_credit_note_fx_truing: sigue anulando los JEs históricos que dejaron
  las NC emitidas bajo la regla de tasa propia.
- Wiring en process_invoice: guard + coherencia para NC/ND; force salta ambos.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.digital_invoice import emission_rerate
from l10n_ve.digital_invoice.emission_rerate import (
    RERATE_TAG,
    cancel_credit_note_fx_truing,
    validate_note_rate,
)
from l10n_ve.l10n_ve.doctype.ve_sales_credit_note import (
    ve_sales_credit_note as nc_module,
)
from l10n_ve.l10n_ve.doctype.ve_sales_debit_note import (
    ve_sales_debit_note as nd_module,
)

# Tasa de la factura afectada y una tasa cualquiera de otra fecha.
_SI_RATE = 633.3644
_OTHER_RATE = 653.9726

_SI_VALUES = {
    "branch": "MIR-01",
    "debit_to": "1105001 - CxC - TEST",
    "conversion_rate": _SI_RATE,
    "plc_conversion_rate": _SI_RATE,
}


class FakeNote:
    def __init__(self, is_new=True, **overrides):
        defaults = {
            "doctype": "VE Sales Credit Note",
            "name": "NC-2026-00001",
            "docstatus": 1,
            "customer": "CUST-JUR",
            "company": "COMPANY-TEST",
            "currency": "USD",
            "conversion_rate": _OTHER_RATE,
            "plc_conversion_rate": _OTHER_RATE,
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


class TestInheritRateNC(unittest.TestCase):
    def _run(self, note, si_values=None):
        with patch("frappe.get_cached_value",
                   return_value=dict(si_values or _SI_VALUES)):
            nc_module.VESalesCreditNote._inherit_branch_from_si(note)

    def test_new_note_takes_invoice_rate(self):
        note = FakeNote()
        self._run(note)
        self.assertEqual(note.conversion_rate, _SI_RATE)
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)

    def test_saved_note_rate_is_reapplied(self):
        """
        Invariante, no default: aunque el borrador ya esté guardado (y aunque
        alguien haya pisado la tasa por API), validate la devuelve a la de la
        factura afectada. Sin esto, el read_only de la UI sería el único
        control y certificaríamos una NC con diferencial contra el CxC.
        """
        note = FakeNote(is_new=False, conversion_rate=_OTHER_RATE,
                        plc_conversion_rate=_OTHER_RATE)
        self._run(note)
        self.assertEqual(note.conversion_rate, _SI_RATE)
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)

    def test_plc_falls_back_to_conversion_rate(self):
        """Factura sin plc_conversion_rate: la NC usa su conversion_rate."""
        note = FakeNote()
        self._run(note, {**_SI_VALUES, "plc_conversion_rate": 0})
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)

    def test_invoice_without_rate_keeps_current(self):
        """Factura sin tasa utilizable: no se pisa la que porta la nota."""
        note = FakeNote()
        self._run(note, {**_SI_VALUES, "conversion_rate": 0,
                         "plc_conversion_rate": 0})
        self.assertEqual(note.conversion_rate, _OTHER_RATE)

    def test_still_inherits_branch_and_debit_to(self):
        note = FakeNote()
        self._run(note)
        self.assertEqual(note.branch, "MIR-01")
        self.assertEqual(note.debit_to, "1105001 - CxC - TEST")

    def test_does_not_inherit_dates(self):
        """posting_date queda el propio (SENIAT); due_date se alinea a él."""
        note = FakeNote(posting_date="2026-07-16")
        self._run(note)
        self.assertEqual(note.posting_date, "2026-07-16")
        self.assertEqual(note.due_date, "2026-07-16")

    def test_no_return_against_is_noop(self):
        note = FakeNote(return_against=None)
        self._run(note)
        self.assertEqual(note.conversion_rate, _OTHER_RATE)


class TestInheritRateND(unittest.TestCase):
    def _run(self, note, si_values=None, own_rate=_OTHER_RATE):
        with patch("frappe.get_cached_value",
                   return_value=dict(si_values or _SI_VALUES)), \
             patch.object(nd_module, "get_ve_exchange_rate_for_customer",
                          return_value=own_rate) as mock_rate:
            nd_module.VESalesDebitNote._inherit_branch_from_si(note)
        return mock_rate

    def test_new_note_defaults_to_invoice_rate(self):
        note = FakeNote(doctype="VE Sales Debit Note", is_debit_note=1,
                        is_return=0)
        mock_rate = self._run(note)
        self.assertEqual(note.conversion_rate, _SI_RATE)
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)
        self.assertEqual(note.due_date, "2026-07-16")
        mock_rate.assert_not_called()

    def test_saved_note_keeps_user_rate(self):
        """La ND es editable: en borradores guardados no se pisa la tasa."""
        note = FakeNote(doctype="VE Sales Debit Note", is_new=False,
                        conversion_rate=_OTHER_RATE)
        self._run(note)
        self.assertEqual(note.conversion_rate, _OTHER_RATE)

    def test_falls_back_to_own_rate_when_invoice_has_none(self):
        """
        Regresión de la escalera elif: el fallback por posting_date colgaba
        del plc de la factura, así que una factura con plc y sin
        conversion_rate dejaba la ND sin tasa.
        """
        note = FakeNote(doctype="VE Sales Debit Note")
        mock_rate = self._run(note, {**_SI_VALUES, "conversion_rate": 0})
        mock_rate.assert_called_once_with("CUST-JUR", "2026-07-16")
        self.assertEqual(note.conversion_rate, _OTHER_RATE)
        self.assertEqual(note.plc_conversion_rate, _OTHER_RATE)

    def test_plc_falls_back_to_conversion_rate(self):
        note = FakeNote(doctype="VE Sales Debit Note")
        self._run(note, {**_SI_VALUES, "plc_conversion_rate": 0})
        self.assertEqual(note.plc_conversion_rate, _SI_RATE)


class TestValidateNoteRate(unittest.TestCase):
    def _run(self, note, si_rate=_SI_RATE):
        with patch("frappe.get_cached_value", return_value="VEF"), \
             patch("frappe.db.get_value", return_value=si_rate):
            validate_note_rate(note)

    def test_nc_with_invoice_rate_passes(self):
        self._run(FakeNote(conversion_rate=_SI_RATE))

    def test_nc_with_other_rate_blocks(self):
        """
        La NC llegó a la emisión con una tasa que no es la de su factura:
        certificarla dejaría diferencial en Bs contra el CxC de la factura.
        Regenerar la nota la corrige, porque la herencia vuelve a leer la
        tasa vigente de la factura.
        """
        with self.assertRaises(frappe.ValidationError):
            self._run(FakeNote(conversion_rate=_OTHER_RATE))

    def test_nd_is_not_checked(self):
        """La ND tiene tasa editable por diseño: este guard no le aplica."""
        self._run(FakeNote(doctype="VE Sales Debit Note",
                           conversion_rate=_OTHER_RATE))

    def test_native_currency_passes(self):
        self._run(FakeNote(currency="VEF", conversion_rate=1.0))

    def test_no_return_against_passes(self):
        self._run(FakeNote(return_against=None, conversion_rate=_OTHER_RATE))

    def test_invoice_without_rate_defers_to_coherencia(self):
        self._run(FakeNote(conversion_rate=_OTHER_RATE), si_rate=0)


class TestSameMonthValidation(unittest.TestCase):
    """
    Guard intra-mes reparado: consultaba self.doctype (la nota) en vez de
    la factura original → None → pasaba en silencio; y las notas VE nunca
    lo invocaban.
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


class TestNoTruingOnSubmit(unittest.TestCase):
    """
    Con la tasa heredada, la NC acredita el CxC exactamente a la tasa de la
    factura: el diferencial es cero por construcción y el asiento de ajuste
    sobra. Solo quedaría disparándose por ruido de redondeo.
    """

    def test_on_submit_does_not_post_truing_entry(self):
        import inspect

        src = inspect.getsource(nc_module.VESalesCreditNote.on_submit)
        self.assertNotIn("_post_fx_truing_entry", src)

    def test_true_up_helper_is_gone(self):
        self.assertFalse(hasattr(emission_rerate, "true_up_credit_note_fx"))


class TestCancelCreditNoteFxTruing(unittest.TestCase):
    """Los JEs históricos (NC emitidas con tasa propia) siguen anulándose."""

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


class TestNoteEmissionWiring(unittest.TestCase):
    class _Sentinel(frappe.ValidationError):
        pass

    def _run_process_invoice(self, force):
        from l10n_ve.digital_invoice import tfhka_integration

        doc = FakeNote()
        doc.add_comment = MagicMock()
        note_rate_mock = MagicMock()
        rerate_mock = MagicMock(return_value=False)
        with patch("frappe.get_doc", return_value=doc), \
             patch.object(tfhka_integration, "validate_note_rate",
                          note_rate_mock), \
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
        return note_rate_mock, rerate_mock, coherencia_mock

    def test_nc_gets_rate_guard_and_coherencia_not_rerate(self):
        """NC sin force: guard de tasa + coherencia corren; el retasado NO."""
        note_rate, rerate, coherencia = self._run_process_invoice(force=False)
        note_rate.assert_called_once()
        rerate.assert_not_called()
        coherencia.assert_called_once()

    def test_force_skips_rate_guard_and_coherencia(self):
        note_rate, rerate, coherencia = self._run_process_invoice(force=True)
        note_rate.assert_not_called()
        rerate.assert_not_called()
        coherencia.assert_not_called()


if __name__ == "__main__":
    unittest.main()
