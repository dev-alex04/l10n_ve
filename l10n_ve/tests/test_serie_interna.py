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


def _serie(modo: str = "Internal", nombre: str = "SFD-2026-TEST") -> MagicMock:
    serie = MagicMock()
    serie.name = nombre
    serie.operation_mode = modo
    serie.serie = "MIR-01"
    serie.take_invoice_number.return_value = "7"
    return serie


def _doc(bill_no: str = "", hka_status: str = "Pendiente") -> MagicMock:
    datos = {"bill_no": bill_no, "hka_status": hka_status}
    doc = MagicMock()
    doc.doctype = "Sales Invoice"
    doc.name = "ACC-SINV-2026-00001"
    doc.get.side_effect = lambda campo, *resto: datos.get(campo)
    return doc


def _doc_simple() -> SimpleNamespace:
    return SimpleNamespace(doctype="Sales Invoice", name="ACC-SINV-2026-00001")


def _respuesta(numero_documento: str = "77") -> dict:
    return {
        "codigo": "200",
        "resultado": {"numeroControl": "00-1", "numeroDocumento": numero_documento},
    }


class TestLaAsignacionEsIdempotente(unittest.TestCase):
    """Un reintento no puede quemar otro correlativo."""

    @patch(f"{_TI}.frappe")
    def test_un_reintento_fallido_reutiliza_su_numero(self, _mock_frappe):
        serie = _serie()
        assign_bill_no_from_digital_series(_doc(bill_no="1234", hka_status="Error"), serie)
        serie.take_invoice_number.assert_not_called()

    @patch(f"{_TI}.frappe")
    def test_un_numero_del_flujo_viejo_si_se_sobreescribe(self, _mock_frappe):
        """La factura nunca pasó por HKA: su número es legacy y la serie manda."""
        serie = _serie()
        assign_bill_no_from_digital_series(_doc(bill_no="00012345", hka_status="Pendiente"), serie)
        serie.take_invoice_number.assert_called_once()

    @patch(f"{_TI}.frappe")
    def test_sin_numero_previo_se_toma_uno(self, _mock_frappe):
        serie = _serie()
        assign_bill_no_from_digital_series(_doc(bill_no="", hka_status="Error"), serie)
        serie.take_invoice_number.assert_called_once()

    @patch(f"{_TI}.frappe")
    def test_en_tercero_no_se_toma_ningun_correlativo(self, _mock_frappe):
        serie = _serie(modo="Third Party")
        assign_bill_no_from_digital_series(_doc(bill_no="1234", hka_status="Error"), serie)
        serie.take_invoice_number.assert_not_called()


class TestElNumeroSeTomaAlFinal(unittest.TestCase):
    """Un documento que no pasa la validación no debe quemar un correlativo."""

    def _correr(self, errores_de_integridad: list[str]):
        parches = {
            "_acquire_hka_send_lock": True,
            "_compute_tasa_fecha": "2026-09-16",
            "get_active_billing_series": (_serie(), "01"),
            "_build_invoice_payload": ({}, MagicMock()),
            "_validate_invoice_integrity": errores_de_integridad,
            "_validate_payload_vs_invoice": [],
        }
        with (
            patch(f"{_TI}.frappe") as mock_frappe,
            patch(f"{_TI}._ensure_bill_no") as mock_asignar,
            patch(f"{_TI}.rerate_to_emission_rate"),
            patch(f"{_TI}._validate_tasa_coherencia"),
            patch(f"{_TI}._update_fiscal_dates"),
            patch(f"{_TI}._set_hka_status"),
            patch(f"{_TI}._log_request"),
            patch(f"{_TI}._hka_log"),
            patch(f"{_TI}.TFHKAClient"),
            patch(f"{_TI}._handle_hka_response", return_value=True),
            patch.multiple(_TI, **{k: MagicMock(return_value=v) for k, v in parches.items()}),
        ):
            mock_frappe.get_doc.return_value = _doc()
            resultado = process_invoice("ACC-SINV-2026-00001")
        return resultado, mock_asignar

    def test_si_la_factura_no_pasa_la_validacion_no_se_toma_numero(self):
        resultado, mock_asignar = self._correr(["El comprobante no tiene sucursal."])
        self.assertFalse(resultado)
        mock_asignar.assert_not_called()

    def test_si_la_factura_esta_bien_si_se_toma(self):
        _resultado, mock_asignar = self._correr([])
        mock_asignar.assert_called_once()


class TestLaDivergenciaConHkaSeVe(unittest.TestCase):
    """Si HKA confirma otro número, el documento se queda con el suyo: tiene que verse."""

    def _correr(self, modo: str, numero_local: str, numero_hka: str, bill_no_guardado: str):
        def get_value(*args, **kwargs):
            if kwargs.get("as_dict"):
                return {"bill_no": bill_no_guardado, "bill_control": "00-1"}
            return numero_local

        with (
            patch(f"{_TI}.frappe") as mock_frappe,
            patch(f"{_TI}._sync_gl_entries_date"),
            patch(f"{_TI}._set_hka_status"),
            patch(f"{_TI}._log_request") as mock_log,
        ):
            mock_frappe.db.get_value.side_effect = get_value
            _handle_hka_response(
                _doc_simple(), "ACC-SINV-2026-00001", {}, _respuesta(numero_hka), _serie(modo)
            )
        return mock_frappe, mock_log

    def test_un_numero_distinto_queda_registrado(self):
        _frappe, mock_log = self._correr("Internal", "10", "77", "10")
        tipos = [llamada.args[0] for llamada in mock_log.call_args_list]
        self.assertIn("Numero divergente HKA", tipos)

    def test_si_coinciden_no_se_registra_nada_raro(self):
        _frappe, mock_log = self._correr("Internal", "77", "77", "77")
        tipos = [llamada.args[0] for llamada in mock_log.call_args_list]
        self.assertNotIn("Numero divergente HKA", tipos)

    def test_en_interno_no_se_adopta_el_numero_de_hka(self):
        """Si el nuestro quedó vacío, es que la asignación falló: no se tapa con el de HKA."""
        mock_frappe, _log = self._correr("Internal", "", "77", "")
        escrituras = [
            llamada.args[2] for llamada in mock_frappe.db.set_value.call_args_list
            if len(llamada.args) > 2 and isinstance(llamada.args[2], dict)
        ]
        self.assertFalse(
            any(valores.get("bill_no") == "77" for valores in escrituras),
            "en Interno no se debe escribir el numeroDocumento de HKA",
        )

    def test_en_tercero_si_se_adopta(self):
        mock_frappe, _log = self._correr("Third Party", "", "77", "")
        escrituras = [
            llamada.args[2] for llamada in mock_frappe.db.set_value.call_args_list
            if len(llamada.args) > 2 and isinstance(llamada.args[2], dict)
        ]
        self.assertTrue(
            any(valores.get("bill_no") == "77" for valores in escrituras),
            "en Tercero el número lo pone HKA",
        )
