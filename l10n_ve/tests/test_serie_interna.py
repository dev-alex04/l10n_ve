# Copyright (c) 2026, Galanet Solution and contributors
# See license.txt
"""El modo de operación Interno de la serie digital: el número es nuestro.

En Interno el número de factura sale del correlativo de la serie, no de HKA. Eso trae tres
obligaciones que el código no cumplía, y que estos tests fijan:

- un reintento no puede tomar otro correlativo y dejar quemado el anterior;
- un documento que ni se va a enviar no debe quemar ninguno;
- si HKA confirma un número distinto al nuestro, tiene que verse.

Suite unittest con mocks, sin base: se parchea el `frappe` del módulo bajo prueba.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from l10n_ve.digital_invoice.tfhka_integration import (
    _handle_hka_response,
    assign_bill_no_from_digital_series,
    process_invoice,
)

_TI = "l10n_ve.digital_invoice.tfhka_integration"


def _series(mode: str = "Internal", name: str = "SFD-2026-TEST") -> MagicMock:
    series = MagicMock()
    series.name = name
    series.operation_mode = mode
    series.series = "MIR-01"
    series.take_invoice_number.return_value = "7"
    return series


def _doc(bill_no: str = "", hka_status: str = "Pendiente") -> MagicMock:
    data = {"bill_no": bill_no, "hka_status": hka_status}
    doc = MagicMock()
    doc.doctype = "Sales Invoice"
    doc.name = "ACC-SINV-2026-00001"
    doc.get.side_effect = lambda field, *rest: data.get(field)
    return doc


def _simple_doc() -> SimpleNamespace:
    return SimpleNamespace(doctype="Sales Invoice", name="ACC-SINV-2026-00001")


def _response(document_number: str = "77") -> dict:
    return {
        "codigo": "200",
        "resultado": {"numeroControl": "00-1", "numeroDocumento": document_number},
    }


class TestAssignmentIsIdempotent(unittest.TestCase):
    """Un reintento no puede quemar otro correlativo."""

    @patch(f"{_TI}.frappe")
    def test_failed_retry_reuses_its_number(self, _mock_frappe):
        series = _series()
        assign_bill_no_from_digital_series(_doc(bill_no="1234", hka_status="Error"), series)
        series.take_invoice_number.assert_not_called()

    @patch(f"{_TI}.frappe")
    def test_legacy_number_is_overwritten(self, _mock_frappe):
        """La factura nunca pasó por HKA: su número es legacy y la serie manda."""
        series = _series()
        assign_bill_no_from_digital_series(_doc(bill_no="00012345", hka_status="Pendiente"), series)
        series.take_invoice_number.assert_called_once()

    @patch(f"{_TI}.frappe")
    def test_without_previous_number_one_is_taken(self, _mock_frappe):
        series = _series()
        assign_bill_no_from_digital_series(_doc(bill_no="", hka_status="Error"), series)
        series.take_invoice_number.assert_called_once()

    @patch(f"{_TI}.frappe")
    def test_third_party_takes_no_counter(self, _mock_frappe):
        series = _series(mode="Third Party")
        assign_bill_no_from_digital_series(_doc(bill_no="1234", hka_status="Error"), series)
        series.take_invoice_number.assert_not_called()


class TestNumberIsTakenLast(unittest.TestCase):
    """Un documento que no pasa la validación no debe quemar un correlativo."""

    def _run(self, integrity_errors: list[str]):
        patches = {
            "_acquire_hka_send_lock": True,
            "_compute_tasa_fecha": "2026-09-16",
            "get_active_billing_series": (_series(), "01"),
            "_build_invoice_payload": ({}, MagicMock()),
            "_validate_invoice_integrity": integrity_errors,
            "_validate_payload_vs_invoice": [],
        }
        with (
            patch(f"{_TI}.frappe") as mock_frappe,
            patch(f"{_TI}._ensure_bill_no") as mock_assign,
            patch(f"{_TI}.rerate_to_emission_rate"),
            patch(f"{_TI}._validate_tasa_coherencia"),
            patch(f"{_TI}._update_fiscal_dates"),
            patch(f"{_TI}._set_hka_status"),
            patch(f"{_TI}._log_request"),
            patch(f"{_TI}._hka_log"),
            patch(f"{_TI}.TFHKAClient"),
            patch(f"{_TI}._handle_hka_response", return_value=True),
            patch.multiple(_TI, **{k: MagicMock(return_value=v) for k, v in patches.items()}),
        ):
            mock_frappe.get_doc.return_value = _doc()
            result = process_invoice("ACC-SINV-2026-00001")
        return result, mock_assign

    def test_no_number_is_taken_when_validation_fails(self):
        result, mock_assign = self._run(["El comprobante no tiene sucursal."])
        self.assertFalse(result)
        mock_assign.assert_not_called()

    def test_number_is_taken_when_invoice_is_valid(self):
        _result, mock_assign = self._run([])
        mock_assign.assert_called_once()


class TestDivergenceFromHkaIsVisible(unittest.TestCase):
    """Si HKA confirma otro número, el documento se queda con el suyo: tiene que verse."""

    def _run(self, mode: str, local_number: str, hka_number: str, saved_bill_no: str):
        def get_value(*args, **kwargs):
            if kwargs.get("as_dict"):
                return {"bill_no": saved_bill_no, "bill_control": "00-1"}
            return local_number

        with (
            patch(f"{_TI}.frappe") as mock_frappe,
            patch(f"{_TI}._sync_gl_entries_date"),
            patch(f"{_TI}._set_hka_status"),
            patch(f"{_TI}._log_request") as mock_log,
        ):
            mock_frappe.db.get_value.side_effect = get_value
            _handle_hka_response(
                _simple_doc(), "ACC-SINV-2026-00001", {}, _response(hka_number), _series(mode)
            )
        return mock_frappe, mock_log

    def test_divergent_number_is_logged(self):
        _frappe, mock_log = self._run("Internal", "10", "77", "10")
        kinds = [call.args[0] for call in mock_log.call_args_list]
        self.assertIn("Numero divergente HKA", kinds)

    def test_matching_numbers_log_nothing(self):
        _frappe, mock_log = self._run("Internal", "77", "77", "77")
        kinds = [call.args[0] for call in mock_log.call_args_list]
        self.assertNotIn("Numero divergente HKA", kinds)

    def test_internal_does_not_adopt_hka_number(self):
        """Si el nuestro quedó vacío, es que la asignación falló: no se tapa con el de HKA."""
        mock_frappe, _log = self._run("Internal", "", "77", "")
        writes = [
            call.args[2] for call in mock_frappe.db.set_value.call_args_list
            if len(call.args) > 2 and isinstance(call.args[2], dict)
        ]
        self.assertFalse(
            any(values.get("bill_no") == "77" for values in writes),
            "en Interno no se debe escribir el numeroDocumento de HKA",
        )

    def test_third_party_adopts_hka_number(self):
        mock_frappe, _log = self._run("Third Party", "", "77", "")
        writes = [
            call.args[2] for call in mock_frappe.db.set_value.call_args_list
            if len(call.args) > 2 and isinstance(call.args[2], dict)
        ]
        self.assertTrue(
            any(values.get("bill_no") == "77" for values in writes),
            "en Tercero el número lo pone HKA",
        )
