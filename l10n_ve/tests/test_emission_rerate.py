# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Tests del retasado a tasa de emisión para clientes jurídicos.

Decisión (9-10 jul 2026, hilo "TASA- FACTURA FISCAL CARACAS"): la factura
fiscal HKA de un jurídico debe expresarse en Bs a la tasa BCV vigente en la
fecha de emisión del documento, no a la del pago. El flujo pagada→cron puede
emitir días después: emission_rerate retasa la Sales Invoice submitted a la
tasa del día antes de construir el payload.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import frappe

from l10n_ve.digital_invoice import emission_rerate
from l10n_ve.digital_invoice.emission_rerate import (
    RERATE_TAG,
    _blocking_condition,
    _get_target_rate,
    _persist_recalculated_fields,
    _post_fx_difference,
    _regenerate_voucher_ledger,
    rerate_to_emission_rate,
)

_OLD_RATE = 633.3644
_NEW_RATE = 653.9726


class FakeChildRow(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db_update = MagicMock()

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class FakeDoc:
    def __init__(self, **overrides):
        defaults = {
            "doctype": "Sales Invoice",
            "name": "ACC-SINV-2026-00001",
            "docstatus": 1,
            "customer": "CUST-JUR",
            "company": "COMPANY-TEST",
            "currency": "USD",
            "conversion_rate": _OLD_RATE,
            "plc_conversion_rate": _OLD_RATE,
            "grand_total": 100.0,
            "rounded_total": 0,
            "posting_date": "2026-07-10",
            "debit_to": "1105001 - CxC - TEST",
            "branch": "MIR-01",
            "cost_center": "Principal - TEST",
            "bill_control": "",
            "advances": [],
            "items": [],
            "taxes": [],
            "payment_schedule": [],
        }
        defaults.update(overrides)
        self.__dict__.update(defaults)
        self.meta = SimpleNamespace(has_field=lambda field: True)
        self.calculate_taxes_and_totals = MagicMock()
        self.set_total_in_words = MagicMock()
        self.force_set_against_income_account = MagicMock()
        self.make_gl_entries = MagicMock()
        self.add_comment = MagicMock()
        self.reload = MagicMock()
        self.set_status = MagicMock()

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


class FakeJournalEntry:
    def __init__(self):
        self.rows = []
        self.flags = SimpleNamespace()
        self.meta = SimpleNamespace(has_field=lambda field: True)
        self.insert = MagicMock()
        self.submit = MagicMock()

    def append(self, table, row):
        self.rows.append(row)

    def __setattr__(self, key, value):
        object.__setattr__(self, key, value)


def _patch_gate(juridical=True, today_rate=_NEW_RATE,
                current_date="2026-07-10", target_date="2026-07-14"):
    """Parchea los helpers del gate en el namespace del módulo."""
    return [
        patch.object(emission_rerate, "is_juridical_customer",
                     return_value=juridical),
        # El gate resuelve la tasa objetivo con get_ve_exchange_rate_for_customer,
        # no con get_exchange_rate: la regla fiscal (jurídico a hoy, natural al 1° del
        # mes en curso) se centralizó ahí. Parchear la función vieja dejaba correr la
        # real, que sin datos devolvía 0 y hacía que el gate saliera por None.
        patch.object(emission_rerate, "get_ve_exchange_rate_for_customer",
                     return_value=today_rate),
        patch.object(emission_rerate, "resolve_exchange_rate_date",
                     side_effect=lambda rate, currency: (
                         current_date if abs(rate - _OLD_RATE) < 0.001
                         else target_date
                     )),
        patch.object(emission_rerate, "today", return_value="2026-07-14"),
        patch("frappe.get_cached_value", return_value="VEF"),
    ]


class TestGetTargetRate(unittest.TestCase):
    def _run(self, doc, **gate_kwargs):
        patches = _patch_gate(**gate_kwargs)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return _get_target_rate(doc)

    def test_skips_draft(self):
        """Borradores no se retasan aquí: los cubre _sync_invoice_with_rate."""
        self.assertIsNone(self._run(FakeDoc(docstatus=0)))

    def test_skips_certified(self):
        """Con bill_control HKA ya certificó: la tasa quedó sellada."""
        self.assertIsNone(self._run(FakeDoc(bill_control="00-00123456")))

    def test_skips_native_currency_invoice(self):
        """Factura en VEF (moneda de la Company): no hay carril Bs que retasar."""
        doc = FakeDoc(currency="VEF", conversion_rate=1.0)
        self.assertIsNone(self._run(doc))

    def test_rerates_natural_customer_too(self):
        """El natural TAMBIÉN se retasa: excluirlo era el bug que arregló el PR #534.

        Una factura de julio emitida el 1° de agosto salía con la tasa del 1° de
        julio porque el gate saltaba a los naturales. La regla fiscal —a qué fecha
        corresponde la tasa de cada tipo— vive en get_ve_exchange_rate_for_customer,
        no acá: este gate sólo decide SI hay que retasar.
        """
        self.assertEqual(self._run(FakeDoc(), juridical=False), _NEW_RATE)

    def test_skips_when_no_rate_for_today(self):
        """Sin tasa BCV disponible hoy no se puede retasar (fail-safe)."""
        self.assertIsNone(self._run(FakeDoc(), today_rate=0.0))

    def test_noop_when_same_effective_date(self):
        """Misma fecha efectiva (jitter entre filas del mismo día): no-op."""
        self.assertIsNone(
            self._run(FakeDoc(), current_date="2026-07-14",
                      target_date="2026-07-14")
        )

    def test_rerates_when_rate_date_differs(self):
        """Jurídico submitted con tasa de otra fecha → retorna la tasa de hoy."""
        self.assertEqual(self._run(FakeDoc()), _NEW_RATE)

    def test_skips_other_doctypes(self):
        """Etapa 1 solo cubre Sales Invoice (NC/ND van en etapa 2)."""
        self.assertIsNone(self._run(FakeDoc(doctype="VE Sales Credit Note")))


class TestBlockingCondition(unittest.TestCase):
    def setUp(self):
        # Cliente habilitado por defecto para todos los tests de la clase.
        patcher = patch("frappe.get_cached_value", return_value=0)
        self.mock_cached = patcher.start()
        self.addCleanup(patcher.stop)

    def test_blocks_disabled_customer(self):
        """Cliente deshabilitado: regenerar su GL revienta en PartyDisabled."""
        self.mock_cached.return_value = 1
        reason = _blocking_condition(FakeDoc())
        self.assertIn("deshabilitado", reason)

    @patch("frappe.get_all", return_value=[])
    def test_advances_do_not_block(self, _mock_get_all):
        """Anticipos aplicados: YA NO bloquean.

        El bloqueo original temía que make_gl_entries duplicara los JEs de
        gain/loss contra los PEs de anticipo. Medido sobre datos de producción
        (retasado real con rollback, 5 facturas con anticipos): crea CERO
        asientos extra y el diferencial queda posteado una sola vez, el de
        _post_fx_difference. through_repost_accounting_ledger ya neutraliza el
        asiento de ERPNext. Quitarlo lleva de 29 a 72 las facturas jurídicas
        represadas que se emiten con la tasa correcta.
        """
        self.assertIsNone(_blocking_condition(FakeDoc(advances=[SimpleNamespace()])))

    def test_blocks_deferred_revenue(self):
        doc = FakeDoc(items=[FakeChildRow(enable_deferred_revenue=1)])
        reason = _blocking_condition(doc)
        self.assertIn("diferido", reason)

    @patch("frappe.db.get_value")
    @patch("frappe.get_all")
    def test_blocks_payment_deductions(self, mock_get_all, mock_get_value):
        """Retenciones registradas como deducción del pago: no retasar."""
        mock_get_all.return_value = ["ACC-PAY-0001"]  # PEs que asignan
        mock_get_value.return_value = "ACC-PAY-0001"  # tiene deducciones

        reason = _blocking_condition(FakeDoc())

        self.assertIn("deducciones", reason)
        # El filtro busca deducciones cuyo parent sea uno de esos PEs.
        filters = mock_get_value.call_args[0][1]
        self.assertEqual(filters["parent"], ("in", ["ACC-PAY-0001"]))
        self.assertEqual(mock_get_value.call_args[0][0],
                         "Payment Entry Deduction")

    @patch("frappe.db.get_value")
    @patch("frappe.get_all")
    def test_blocks_foreign_credit(self, mock_get_all, mock_get_value):
        """Un JE manual (sin tag) contra la factura invalida la aritmética."""
        mock_get_all.side_effect = [
            [],  # _get_allocating_payment_entries
            [SimpleNamespace(voucher_type="Journal Entry",
                             voucher_no="JE-0001")],
        ]
        mock_get_value.return_value = "Ajuste manual de contabilidad"
        reason = _blocking_condition(FakeDoc())
        self.assertIn("Journal Entry JE-0001", reason)

    @patch("frappe.db.get_value")
    @patch("frappe.get_all")
    def test_allows_own_tagged_je(self, mock_get_all, mock_get_value):
        """Los JEs de retasados anteriores (con tag) no bloquean el reintento."""
        mock_get_all.side_effect = [
            [],
            [SimpleNamespace(voucher_type="Journal Entry",
                             voucher_no="JE-0002")],
        ]
        mock_get_value.return_value = f"{RERATE_TAG} Diferencial cambiario..."
        self.assertIsNone(_blocking_condition(FakeDoc()))


class TestPersistRecalculatedFields(unittest.TestCase):
    @patch("frappe.db.set_value")
    def test_parent_persist_is_selective(self, mock_set_value):
        """
        El padre se persiste con lista explícita: jamás outstanding_amount
        ni status (calculate_taxes_and_totals los deja corruptos en memoria
        porque ignora los Payment Entries reconciliados).
        """
        item = FakeChildRow(base_amount=0)
        tax = FakeChildRow(base_tax_amount=0)
        schedule = FakeChildRow(payment_amount=100, base_payment_amount=0)
        doc = FakeDoc(items=[item], taxes=[tax], payment_schedule=[schedule],
                      base_grand_total=65397.26, base_net_total=56377.0,
                      base_in_words="...", outstanding_amount=65397.26,
                      status="Unpaid")

        _persist_recalculated_fields(doc)

        item.db_update.assert_called_once()
        tax.db_update.assert_called_once()
        schedule.db_update.assert_called_once()

        values = mock_set_value.call_args[0][2]
        self.assertNotIn("outstanding_amount", values)
        self.assertNotIn("status", values)
        for field in ("conversion_rate", "base_grand_total", "base_net_total",
                      "base_total_exempt", "base_total_with_vat"):
            self.assertIn(field, values)
        self.assertFalse(mock_set_value.call_args[1]["update_modified"])


class TestRegenerateVoucherLedger(unittest.TestCase):
    @patch("frappe.db.delete")
    @patch("frappe.db.table_exists", return_value=True)
    def test_delete_pattern_and_regen_order(self, _exists, mock_delete):
        """Patrón delete de Repost: GL + PLE + Advance PLE, luego regenerar."""
        doc = FakeDoc()
        frappe.flags.through_repost_accounting_ledger = False

        _regenerate_voucher_ledger(doc)

        deleted = [c[0][0] for c in mock_delete.call_args_list]
        self.assertEqual(
            deleted,
            ["GL Entry", "Payment Ledger Entry", "Advance Payment Ledger Entry"],
        )
        for c in mock_delete.call_args_list:
            self.assertEqual(
                c[1]["filters"],
                {"voucher_type": "Sales Invoice",
                 "voucher_no": "ACC-SINV-2026-00001"},
            )
        doc.force_set_against_income_account.assert_called_once()
        doc.make_gl_entries.assert_called_once()
        self.assertFalse(frappe.flags.through_repost_accounting_ledger)


class TestPostFxDifference(unittest.TestCase):
    def _run(self, doc, allocations, outstanding_vef, pe_rate=_OLD_RATE,
             new_rate=_NEW_RATE):
        je = FakeJournalEntry()
        with patch("frappe.get_all", return_value=allocations), \
             patch("frappe.db.get_value", return_value=pe_rate), \
             patch("frappe.db.sql", return_value=[[outstanding_vef]]), \
             patch("frappe.get_cached_value",
                   return_value=("8101011 - Perdida en Cambio - TEST",
                                 "7101005 - Ganancia en Cambio - TEST")), \
             patch("frappe.new_doc", return_value=je) as mock_new_doc, \
             patch.object(emission_rerate, "today",
                          return_value="2026-07-14"):
            _post_fx_difference(doc, _OLD_RATE, new_rate)
        return je, mock_new_doc

    @staticmethod
    def _alloc(amount_vef):
        return SimpleNamespace(
            voucher_no="ACC-PAY-0001",
            amount_in_account_currency=-amount_vef,
            account_currency="VEF",
        )

    def test_paid_rate_up_posts_loss(self):
        """
        Pagada 100 USD a 633.3644 y retasada a 653.9726: el CxC quedó
        inflado en Bs → crédito al CxC por el delta contra la PÉRDIDA.
        """
        je, _ = self._run(
            FakeDoc(),
            allocations=[self._alloc(63336.44)],
            outstanding_vef=65397.26 - 63336.44,  # nueva base − cobrado
        )

        je.insert.assert_called_once()
        je.submit.assert_called_once()
        self.assertEqual(je.voucher_type, "Exchange Gain Or Loss")
        self.assertIn(RERATE_TAG, je.user_remark)

        cxc_row, counter_row = je.rows
        self.assertEqual(cxc_row["account"], "1105001 - CxC - TEST")
        self.assertEqual(cxc_row["party"], "CUST-JUR")
        self.assertEqual(cxc_row["reference_name"], "ACC-SINV-2026-00001")
        self.assertAlmostEqual(cxc_row["credit_in_account_currency"],
                               2060.82, places=2)
        self.assertEqual(counter_row["account"],
                         "8101011 - Perdida en Cambio - TEST")
        self.assertAlmostEqual(counter_row["debit_in_account_currency"],
                               2060.82, places=2)

    def test_rate_down_posts_gain(self):
        """Tasa bajó: débito al CxC contra la cuenta de GANANCIA (por signo)."""
        je, _ = self._run(
            FakeDoc(),
            allocations=[self._alloc(63336.44)],
            outstanding_vef=62221.35 - 63336.44,  # nueva base menor
            new_rate=622.2135,
        )

        cxc_row, counter_row = je.rows
        self.assertAlmostEqual(cxc_row["debit_in_account_currency"],
                               1115.09, places=2)
        self.assertEqual(counter_row["account"],
                         "7101005 - Ganancia en Cambio - TEST")
        self.assertAlmostEqual(counter_row["credit_in_account_currency"],
                               1115.09, places=2)

    def test_partial_payment_delta_only_over_paid(self):
        """
        Pago parcial de 50 USD: el delta cubre solo lo cobrado; el saldo
        impago queda re-expresado a la tasa nueva (lo gobierna la política
        de cobro, no este asiento).
        """
        je, _ = self._run(
            FakeDoc(),
            allocations=[self._alloc(31668.22)],  # 50 USD a la tasa vieja
            outstanding_vef=65397.26 - 31668.22,
        )

        cxc_row = je.rows[0]
        # 50 USD × (653.9726 − 633.3644) = 1030.41
        self.assertAlmostEqual(cxc_row["credit_in_account_currency"],
                               1030.41, places=2)

    def test_no_je_without_payments(self):
        """Sin cobros no hay diferencial: el saldo completo va a tasa nueva."""
        with patch("frappe.get_all", return_value=[]), \
             patch("frappe.new_doc") as mock_new_doc:
            _post_fx_difference(FakeDoc(), _OLD_RATE, _NEW_RATE)
        mock_new_doc.assert_not_called()

    def test_idempotent_when_prior_je_closed_the_gap(self):
        """
        Reintento tras retasado previo: el outstanding ya incluye el JE del
        día anterior → delta ≈ 0 → no se duplica el asiento.
        """
        _, mock_new_doc = self._run(
            FakeDoc(),
            allocations=[self._alloc(63336.44)],
            outstanding_vef=0.0,
        )
        mock_new_doc.assert_not_called()


class TestRerateOrchestration(unittest.TestCase):
    def _patch_all(self, doc, target_rate=_NEW_RATE, blocking=None):
        patches = [
            patch.object(emission_rerate, "_get_target_rate",
                         return_value=target_rate),
            patch.object(emission_rerate, "_blocking_condition",
                         return_value=blocking),
            patch.object(emission_rerate, "_apply_rate_in_memory"),
            patch.object(emission_rerate, "_persist_recalculated_fields"),
            patch.object(emission_rerate, "_regenerate_voucher_ledger"),
            patch.object(emission_rerate, "_post_fx_difference"),
            patch.object(emission_rerate, "_close_outstanding_and_status"),
            patch("frappe.db.get_value", return_value=""),
            patch("frappe.db.savepoint"),
            patch("frappe.db.rollback"),
        ]
        started = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        return started

    def test_happy_path_returns_true_and_comments(self):
        doc = FakeDoc()
        self._patch_all(doc)
        self.assertTrue(rerate_to_emission_rate(doc))
        doc.add_comment.assert_called_once()

    def test_noop_when_gate_says_no(self):
        doc = FakeDoc()
        mocks = self._patch_all(doc, target_rate=None)
        self.assertFalse(rerate_to_emission_rate(doc))
        mocks[2].assert_not_called()  # _apply_rate_in_memory

    @patch.object(emission_rerate, "_log_skip")
    def test_blocking_condition_skips_and_logs(self, mock_log_skip):
        """Guard activo: no retasa, la emisión sigue, queda rastro en el log."""
        doc = FakeDoc()
        mocks = self._patch_all(doc, blocking="tiene anticipos aplicados")
        self.assertFalse(rerate_to_emission_rate(doc))
        mock_log_skip.assert_called_once()
        mocks[2].assert_not_called()

    def test_lock_recheck_aborts_if_already_certified(self):
        """Carrera cron vs botón: si otro proceso certificó, abortar."""
        doc = FakeDoc()
        mocks = self._patch_all(doc)
        # El lock (get_value for_update) devuelve bill_control: otro proceso
        # ganó la carrera y certificó → no-op sin mutar nada.
        mocks[7].return_value = "00-00123456"
        self.assertFalse(rerate_to_emission_rate(doc))
        mocks[2].assert_not_called()  # _apply_rate_in_memory

    def test_failure_rolls_back_and_raises_validation_error(self):
        """
        Fallo a mitad (GL borrado sin regenerar): rollback al savepoint y
        ValidationError — cae en el `raise` de process_invoice y evita el
        commit del except genérico que dejaría contabilidad rota.
        """
        doc = FakeDoc()
        with patch.object(emission_rerate, "_get_target_rate",
                          return_value=_NEW_RATE), \
             patch.object(emission_rerate, "_blocking_condition",
                          return_value=None), \
             patch.object(emission_rerate, "_apply_rate_in_memory"), \
             patch.object(emission_rerate, "_persist_recalculated_fields"), \
             patch.object(emission_rerate, "_regenerate_voucher_ledger",
                          side_effect=Exception("deadlock")), \
             patch("frappe.db.get_value", return_value=""), \
             patch("frappe.db.savepoint") as mock_savepoint, \
             patch("frappe.db.rollback") as mock_rollback, \
             patch("frappe.get_traceback", return_value="tb"):
            with self.assertRaises(frappe.ValidationError):
                rerate_to_emission_rate(doc)

        mock_savepoint.assert_called_once_with("hka_rerate")
        mock_rollback.assert_called_once_with(save_point="hka_rerate")


class TestProcessInvoiceWiring(unittest.TestCase):
    class _Sentinel(frappe.ValidationError):
        pass

    def _run_process_invoice(self, force):
        from l10n_ve.digital_invoice import tfhka_integration

        doc = FakeDoc()
        rerate_mock = MagicMock(return_value=False)
        with patch("frappe.get_doc", return_value=doc), \
             patch.object(tfhka_integration, "rerate_to_emission_rate",
                          rerate_mock), \
             patch.object(tfhka_integration, "_compute_tasa_fecha",
                          side_effect=self._Sentinel("stop-no-force")), \
             patch.object(tfhka_integration, "_update_fiscal_dates",
                          side_effect=self._Sentinel("stop-force")), \
             patch.object(tfhka_integration, "_validate_tasa_coherencia"), \
             patch.object(tfhka_integration, "getdate",
                          return_value="2026-07-14"):
            with self.assertRaises(self._Sentinel):
                tfhka_integration.process_invoice(
                    "ACC-SINV-2026-00001", force=force
                )
        return rerate_mock

    def test_rerate_runs_before_tasa_fecha(self):
        """Sin force: el retasado corre antes de calcular tasa_fecha."""
        rerate_mock = self._run_process_invoice(force=False)
        rerate_mock.assert_called_once()

    def test_force_skips_rerate(self):
        """force (solo Administrator) respeta la tasa que porta el documento."""
        rerate_mock = self._run_process_invoice(force=True)
        rerate_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
