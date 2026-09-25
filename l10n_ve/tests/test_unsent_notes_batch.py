# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Aviso de documentos sin enviar: las NC/ND esperan su lote (días 14 y último, 15:23).

Antes el aviso decía «no hay envío automático; se emiten a mano» para toda NC/ND sin
emitir, aunque desde el 31-ago-2026 las toma `send_pending_notes_to_hka`: mandaba a
emitir a mano, tres veces al día, notas que el lote iba a enviar.
"""

import datetime
import unittest
from unittest.mock import patch

import frappe

from l10n_ve.digital_invoice import unsent_documents as ud

_DT = datetime.datetime


class TestNextNotesBatch(unittest.TestCase):
    def test_before_the_14th_is_the_14th(self):
        self.assertEqual(ud.next_notes_batch(_DT(2026, 9, 3, 7, 0)), _DT(2026, 9, 14, 15, 23))

    def test_the_14th_before_the_run(self):
        self.assertEqual(ud.next_notes_batch(_DT(2026, 9, 14, 12, 0)), _DT(2026, 9, 14, 15, 23))

    def test_after_the_14th_is_the_last_day(self):
        self.assertEqual(ud.next_notes_batch(_DT(2026, 9, 14, 16, 0)), _DT(2026, 9, 30, 15, 23))

    def test_after_the_last_run_there_is_none(self):
        self.assertIsNone(ud.next_notes_batch(_DT(2026, 9, 30, 16, 0)))

    def test_february(self):
        self.assertEqual(ud.next_notes_batch(_DT(2027, 2, 20, 7, 0)), _DT(2027, 2, 28, 15, 23))


class TestNotesPendingReason(unittest.TestCase):
    def test_waiting_for_the_batch(self):
        code, detail = ud._notes_pending_reason(_DT(2026, 9, 25, 12, 0), True)
        self.assertEqual(code, "notes_batch_pending")
        self.assertIn("30-09-2026 15:23", detail)

    def test_batch_already_ran(self):
        self.assertEqual(ud._notes_pending_reason(_DT(2026, 9, 30, 16, 0), True)[0], "notes_batch_missed")

    def test_auto_send_off_is_manual(self):
        self.assertEqual(ud._notes_pending_reason(_DT(2026, 9, 25, 12, 0), False)[0], "manual_pending")


class TestAutoSendFlagIsParsed(unittest.TestCase):
    """`get_singles_dict` devuelve '0' como texto y bool('0') es True: el aviso creía el envío
    automático encendido estando apagado (y el banner de «apagado» nunca salía)."""

    def test_zero_as_text_is_off(self):
        with patch.object(ud.frappe.db, "get_singles_dict", return_value={"enable_auto_send": "0"}), \
             patch.object(ud, "_collect_sales_invoices", return_value=[]), \
             patch.object(ud, "_collect_sales_notes", return_value=[]) as notes, \
             patch.object(ud, "_collect_vouchers", return_value=[]), \
             patch.object(ud, "_collect_dispatch_notes", return_value=[]):
            result = ud.get_unsent_documents(_DT(2026, 9, 25, 12, 0))
        self.assertFalse(result["auto_send_enabled"])
        self.assertFalse(notes.call_args.args[4])


class TestCollectSalesNotes(unittest.TestCase):
    def _collect(self, reference, auto_send=True, logs=None):
        note = frappe._dict(name="NC-2026-00001", date=datetime.date(2026, 9, 20), party="Cliente",
                            amount=10, currency="USD", branch="Principal", modified=None)

        def sql(query, *args, **kwargs):
            return [note] if "VE Sales Credit Note" in query else []

        with patch.object(ud.frappe.db, "sql", side_effect=sql), \
             patch.object(ud, "_last_logs", return_value=logs or {}):
            return ud._collect_sales_notes(datetime.date(2026, 9, 1), reference.date(), None, reference, auto_send)

    def test_note_waits_for_the_batch(self):
        rows = self._collect(_DT(2026, 9, 25, 12, 0))
        self.assertEqual([r["reason_code"] for r in rows], ["notes_batch_pending"])

    def test_note_after_the_last_batch_asks_for_manual(self):
        rows = self._collect(_DT(2026, 9, 30, 16, 0))
        self.assertEqual([r["reason_code"] for r in rows], ["notes_batch_missed"])

    def test_failed_note_keeps_its_error(self):
        logs = {"NC-2026-00001": frappe._dict(status="Error", notes="HKA rechazó: [1006] bases")}
        rows = self._collect(_DT(2026, 9, 25, 12, 0), logs=logs)
        self.assertNotIn(rows[0]["reason_code"], ("notes_batch_pending", "notes_batch_missed"))
