# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests for the daily notice of documents that never reached HKA
(l10n_ve.tasks.build_unsent_hka_documents_email / send_unsent_hka_documents_notice).

The classifier has its own suite; what is protected here is the delivery contract:
when the notice must NOT be sent, that a traceback never leaks into the message, and
that the copy is escaped. The rows are injected, so no database is involved.
"""

import datetime
import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.tasks import build_unsent_hka_documents_email, send_unsent_hka_documents_notice

NOW = datetime.datetime(2026, 8, 9, 7, 0, 0)

PERIOD = {"from": datetime.date(2026, 8, 1), "to": datetime.date(2026, 8, 9), "as_of": NOW}


def _row(**over) -> dict:
    row = {
        "doctype": "Sales Invoice",
        "name": "ACC-SINV-2026-15344",
        "date": datetime.date(2026, 8, 1),
        "party": "MIGUEL SEQUERA",
        "amount": 30.0,
        "currency": "USD",
        "branch": "GUARENAS",
        "reason_code": "rate_mismatch",
        "reason": "Tasa incoherente",
        "action": "Corrija la tasa del documento.",
        "detail": "La tasa del documento no corresponde.",
    }
    row.update(over)
    return row


def _result(rows, auto_send=True) -> dict:
    return {"rows": rows, "period": PERIOD, "auto_send_enabled": auto_send}


class TestBuildNotice(unittest.TestCase):
    def _build(self, result):
        with patch(
            "l10n_ve.digital_invoice.unsent_documents.get_unsent_documents",
            return_value=result,
        ):
            return build_unsent_hka_documents_email(NOW)

    def test_no_rows_returns_none(self):
        """Sin novedades no se arma nada: el llamador no envía."""
        self.assertIsNone(self._build(_result([])))

    def test_subject_carries_the_count(self):
        subject, _ = self._build(_result([_row(), _row(name="ACC-SINV-2026-15839")]))
        self.assertIn("2 documento(s)", subject)

    def test_rows_are_grouped_and_action_shown_once(self):
        """La acción es por motivo: repetirla en cada fila es ruido."""
        rows = [_row(), _row(name="B"), _row(name="C")]
        _, html = self._build(_result(rows))
        self.assertEqual(html.count("Corrija la tasa del documento."), 1)
        self.assertIn("Tasa incoherente — 3", html)

    def test_two_reasons_produce_two_groups(self):
        rows = [
            _row(),
            _row(name="NC-1", reason_code="manual_pending", reason="Sin emitir", action="A mano."),
        ]
        _, html = self._build(_result(rows))
        self.assertIn("Tasa incoherente — 1", html)
        self.assertIn("Sin emitir — 1", html)

    def test_autosend_off_shows_banner(self):
        _, html = self._build(_result([_row()], auto_send=False))
        self.assertIn("desactivado", html)

    def test_autosend_on_hides_banner(self):
        _, html = self._build(_result([_row()], auto_send=True))
        self.assertNotIn("desactivado", html)

    def test_technical_error_leaks_no_traceback(self):
        """El clasificador vacía el detalle de un traceback; acá se confirma la salida."""
        rows = [_row(reason_code="technical_error", reason="Error técnico", detail="")]
        _, html = self._build(_result(rows))
        self.assertNotIn("Traceback", html)

    def test_party_name_is_escaped(self):
        _, html = self._build(_result([_row(party="ACME <script>x</script>")]))
        self.assertNotIn("<script>", html)

    def test_missing_amount_does_not_break_the_row(self):
        """Los comprobantes de retención no traen monto."""
        _, html = self._build(_result([_row(amount=None, currency="")]))
        self.assertIn("ACC-SINV-2026-15344", html)


class TestSendNotice(unittest.TestCase):
    """Cuándo NO se envía, que es lo que más importa proteger."""

    def _run(self, recipients, built):
        settings = MagicMock()
        settings.get_notification_recipients.return_value = recipients
        with patch("frappe.get_doc", return_value=settings), patch(
            "l10n_ve.tasks.build_unsent_hka_documents_email", return_value=built
        ), patch("frappe.sendmail") as sendmail:
            send_unsent_hka_documents_notice()
            return sendmail

    def test_no_recipients_sends_nothing(self):
        sendmail = self._run([], ("asunto", "<p>algo</p>"))
        sendmail.assert_not_called()

    def test_no_rows_sends_nothing(self):
        sendmail = self._run(["conta@galanet.com.ve"], None)
        sendmail.assert_not_called()

    def test_sends_once_to_every_recipient(self):
        sendmail = self._run(["a@x.com", "b@y.com"], ("asunto", "<p>algo</p>"))
        sendmail.assert_called_once()
        self.assertEqual(sendmail.call_args.kwargs["recipients"], ["a@x.com", "b@y.com"])

    def test_delivery_failure_is_logged_not_raised(self):
        """Una alerta que no se puede entregar no debe tumbar el cron, pero sí dejar rastro."""
        settings = MagicMock()
        settings.get_notification_recipients.return_value = ["a@x.com"]
        with patch("frappe.get_doc", return_value=settings), patch(
            "l10n_ve.tasks.build_unsent_hka_documents_email", return_value=("s", "<p>x</p>")
        ), patch("frappe.sendmail", side_effect=Exception("smtp caído")), patch(
            "frappe.log_error"
        ) as log_error:
            send_unsent_hka_documents_notice()
            log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
