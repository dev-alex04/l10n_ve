# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios de las transiciones de hka_status en el flujo de emisión HKA
(_handle_hka_response de l10n_ve.digital_invoice.tfhka_integration).

Suite unittest + mocks: se parchea el frappe del módulo bajo test, sin BD.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from l10n_ve.digital_invoice.tfhka_integration import (
    HKARangeExhausted,
    _handle_hka_response,
)

_TI = "l10n_ve.digital_invoice.tfhka_integration"


def _doc() -> SimpleNamespace:
    return SimpleNamespace(doctype="Sales Invoice", name="ACC-SINV-2026-00001")


def _series(serie: str = "MIR-01", mode: str = "Third Party") -> SimpleNamespace:
    return SimpleNamespace(serie=serie, operation_mode=mode)


def _hka_status_writes(mock_frappe) -> list[dict]:
    """Extrae los dicts escritos vía set_value que incluyen hka_status."""
    writes = []
    for call in mock_frappe.db.set_value.call_args_list:
        values = call.args[2] if len(call.args) > 2 else None
        if isinstance(values, dict) and "hka_status" in values:
            writes.append(values)
    return writes


class TestHandleHkaResponseTransitions(unittest.TestCase):

    @patch(f"{_TI}._log_request")
    @patch(f"{_TI}._sync_gl_entries_date")
    @patch(f"{_TI}.frappe")
    def test_success_sets_emitida_with_series(self, mock_frappe, _sync, mock_log):
        """Respuesta 200 -> True, hka_status=Emitida + hka_series de la serie usada."""
        response = {
            "codigo": "200",
            "resultado": {"numeroControl": "00-1", "numeroDocumento": "123"},
        }
        ok = _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, response, _series())

        self.assertTrue(ok)
        writes = _hka_status_writes(mock_frappe)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["hka_status"], "Emitida")
        self.assertEqual(writes[0]["hka_series"], "MIR-01")
        self.assertEqual(mock_log.call_args.args[4], "Success")

    @patch(f"{_TI}._log_request")
    @patch(f"{_TI}.frappe")
    def test_null_response_sets_error(self, mock_frappe, mock_log):
        """Respuesta nula (timeout) -> False, hka_status=Error, sin AttributeError."""
        ok = _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, None, _series())

        self.assertFalse(ok)
        writes = _hka_status_writes(mock_frappe)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["hka_status"], "Error")
        self.assertEqual(mock_log.call_args.args[4], "Error")

    @patch(f"{_TI}._log_request")
    @patch(f"{_TI}.frappe")
    def test_rejection_sets_error(self, mock_frappe, mock_log):
        """HKA rechaza (400 + validaciones) -> False, hka_status=Error."""
        response = {
            "codigo": "400",
            "validaciones": ["El RIF del receptor no es válido"],
            "mensaje": "Documento rechazado",
        }
        ok = _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, response, _series())

        self.assertFalse(ok)
        writes = _hka_status_writes(mock_frappe)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["hka_status"], "Error")

    @patch(f"{_TI}._log_request")
    @patch(f"{_TI}.frappe")
    def test_range_exhausted_writes_error_before_raising(self, mock_frappe, _log):
        """Serie agotada -> lanza HKARangeExhausted, pero el Error queda escrito antes."""
        response = {
            "codigo": "400",
            "mensaje": "No hay rango de numeración disponible para la serie",
        }
        with self.assertRaises(HKARangeExhausted):
            _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, response, _series())

        writes = _hka_status_writes(mock_frappe)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["hka_status"], "Error")

    @patch(f"{_TI}._log_request")
    @patch(f"{_TI}._sync_gl_entries_date")
    @patch(f"{_TI}.frappe")
    def test_retry_after_error_reaches_emitida(self, mock_frappe, _sync, _log):
        """Error -> reintento exitoso -> Emitida (transición legal del cron)."""
        _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, None, _series())
        response = {"codigo": "200", "resultado": {"numeroControl": "00-2"}}
        ok = _handle_hka_response(_doc(), "ACC-SINV-2026-00001", {}, response, _series())

        self.assertTrue(ok)
        statuses = [w["hka_status"] for w in _hka_status_writes(mock_frappe)]
        self.assertEqual(statuses, ["Error", "Emitida"])


if __name__ == "__main__":
    unittest.main()
