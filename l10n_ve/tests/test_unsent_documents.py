# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del clasificador de documentos no enviados a HKA
(l10n_ve.digital_invoice.unsent_documents).

Se prueba la lógica de decisión, que es donde están las reglas: cómo se traduce el
texto de un log a un motivo, qué se muestra y qué no, y cuándo un documento cuenta
como trabado. La recolección por SQL se valida aparte contra la copia de producción.

Suite unittest con datos armados a mano: sin BD y sin reloj real — la hora entra por
parámetro justamente para que esto sea reproducible.
"""

import datetime
import unittest

from l10n_ve.digital_invoice.unsent_documents import (
    REASONS,
    _classify_log_notes,
    _is_stalled,
    _safe_detail,
)

AHORA = datetime.datetime(2026, 8, 9, 7, 0, 0)
CORTE = AHORA - datetime.timedelta(minutes=30)  # 06:30


class TestClassifyLogNotes(unittest.TestCase):
    """El motivo sale del texto del último log."""

    def test_rate_message_is_rate_mismatch(self):
        notes = ("La tasa del documento (746.6297, del 2026-07-31) no corresponde a su "
                 "fecha de emisión 2026-08-01 (tasa 748.7864).")
        self.assertEqual(_classify_log_notes(notes), "rate_mismatch")

    def test_range_message_is_range_exhausted(self):
        notes = "Mensaje: Documento no procesado\nValidaciones: No posee rango de numeración disponible"
        self.assertEqual(_classify_log_notes(notes), "range_exhausted")

    def test_range_message_without_accent(self):
        """HKA no siempre acentúa; la constante compartida cubre las dos formas."""
        self.assertEqual(
            _classify_log_notes("No posee rango de numeracion disponible"), "range_exhausted"
        )

    def test_traceback_wins_over_everything(self):
        """Un volcado puede mencionar 'tasa' de paso; primero se descarta que sea técnico."""
        notes = "Traceback with variables (most recent call last):\n  tasa = 746.62"
        self.assertEqual(_classify_log_notes(notes), "technical_error")

    def test_unknown_message_is_hka_rejected(self):
        self.assertEqual(_classify_log_notes("Documento duplicado"), "hka_rejected")

    def test_empty_notes_is_hka_rejected(self):
        self.assertEqual(_classify_log_notes(""), "hka_rejected")
        self.assertEqual(_classify_log_notes(None), "hka_rejected")


class TestSafeDetail(unittest.TestCase):
    """Lo que se muestra: nunca un traceback."""

    def test_traceback_shows_nothing(self):
        notes = "Traceback with variables (most recent call last):\n  File 'apps/l10n_ve/...'"
        self.assertEqual(_safe_detail(notes, "technical_error"), "")

    def test_message_is_collapsed_to_one_line(self):
        self.assertEqual(
            _safe_detail("La tasa\n  no   corresponde", "rate_mismatch"),
            "La tasa no corresponde",
        )

    def test_long_message_is_truncated(self):
        self.assertEqual(len(_safe_detail("x" * 900, "hka_rejected")), 300)


class TestIsStalled(unittest.TestCase):
    """Trabado = ya era enviable antes del corte y sigue sin salir."""

    def test_moved_after_deadline_is_not_stalled(self):
        """Se volvió enviable a las 06:45: está legítimamente en vuelo."""
        doc = {"modified": datetime.datetime(2026, 8, 9, 6, 45)}
        self.assertFalse(_is_stalled(doc, None, CORTE))

    def test_moved_before_deadline_is_stalled(self):
        doc = {"modified": datetime.datetime(2026, 8, 9, 5, 0)}
        self.assertTrue(_is_stalled(doc, None, CORTE))

    def test_recent_attempt_beats_old_modified(self):
        """Si el cron lo intentó hace un rato, el ancla es el intento, no el modified."""
        doc = {"modified": datetime.datetime(2026, 8, 1, 3, 0)}
        log = {"creation": datetime.datetime(2026, 8, 9, 6, 50)}
        self.assertFalse(_is_stalled(doc, log, CORTE))

    def test_old_attempt_and_old_modified_is_stalled(self):
        doc = {"modified": datetime.datetime(2026, 8, 8, 10, 0)}
        log = {"creation": datetime.datetime(2026, 8, 8, 11, 0)}
        self.assertTrue(_is_stalled(doc, log, CORTE))

    def test_no_timestamps_is_stalled(self):
        """Sin ninguna marca no se puede afirmar que sea reciente: se reporta."""
        self.assertTrue(_is_stalled({}, None, CORTE))


class TestReasonsCatalogue(unittest.TestCase):
    def test_every_reason_has_label_and_action(self):
        for code, (label, action) in REASONS.items():
            self.assertTrue(label, f"{code} sin etiqueta")
            self.assertTrue(action, f"{code} sin acción sugerida")

    def test_codes_produced_by_the_classifier_exist(self):
        for code in ("rate_mismatch", "range_exhausted", "technical_error", "hka_rejected"):
            self.assertIn(code, REASONS)


if __name__ == "__main__":
    unittest.main()
