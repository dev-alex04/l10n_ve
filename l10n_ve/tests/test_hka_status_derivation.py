# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la derivación ESTRICTA de hka_status/hka_series
(l10n_ve.digital_invoice.hka_status, consumida por el reporte y por el
backfill de domina_galanet).

Semántica estricta (auditoría fiscal 2026-07): el campo solo afirma lo que
HKA registró — sin evidencia HKA el estado queda vacío, y la serie jamás se
infiere del mapping por sucursal.

Suite 100% unittest + mocks (sin BD ni FrappeTestCase): el módulo solo
importa frappe a nivel top-level, así que se importa sin arrancar el site.
"""

import json
import unittest

from frappe.utils import getdate

from l10n_ve.digital_invoice.hka_status import (
    derive_hka_series,
    derive_hka_status,
    has_hka_evidence,
)

CUTOFF = getdate("2026-04-01")

HKA_REMARKS_SAMPLE: str = json.dumps({
    "resultado": {
        "imprentaDigital": "THE FACTORY HKA VENEZUELA, C.A.",
        "serie": "MIR-01",
        "numeroDocumento": "2900",
        "numeroControl": "00-00233094",
    },
    "codigo": "200",
    "mensaje": "Documento procesado",
})

SUCCESS_LOG = {"response_received": HKA_REMARKS_SAMPLE, "payload_sent": None}


class TestHasHkaEvidence(unittest.TestCase):
    """Evidencia = log Success | bill_control formato HKA | remarks código 200."""

    def test_success_log_is_evidence(self):
        self.assertTrue(has_hka_evidence({"bill_control": ""}, SUCCESS_LOG))

    def test_hka_format_control_is_evidence(self):
        self.assertTrue(has_hka_evidence({"bill_control": "00-00233094"}, None))

    def test_hka_remarks_is_evidence(self):
        self.assertTrue(has_hka_evidence(
            {"bill_control": "", "remarks": HKA_REMARKS_SAMPLE}, None))

    def test_legacy_control_is_not_evidence(self):
        """bill_control de 5 dígitos (talonario pre-HKA) NO es evidencia."""
        self.assertFalse(has_hka_evidence(
            {"bill_control": "02422", "remarks": "No hay observaciones"}, None))

    def test_plain_text_remarks_is_not_evidence(self):
        self.assertFalse(has_hka_evidence(
            {"bill_control": "", "remarks": "Pago recibido por transferencia"}, None))


class TestDeriveHkaStatus(unittest.TestCase):
    """Precedencia estricta: Anulada(+evid) > Emitida(evid) > Error(ds=1) >
    Pendiente(ds=1, >=cutoff) > vacío."""

    def test_void_with_evidence_is_anulada(self):
        row = {"is_void": 1, "bill_control": "00-00219130", "docstatus": 2}
        self.assertEqual(derive_hka_status(row, "Success", SUCCESS_LOG, CUTOFF), "Anulada")

    def test_void_without_evidence_is_empty(self):
        """Void local legacy (void_document) sin rastro HKA -> vacío, NO Anulada."""
        row = {"is_void": 1, "bill_control": "01015", "remarks": "x", "docstatus": 2}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "")

    def test_evidence_derives_emitida_even_cancelled(self):
        """docstatus=2 sin void pero emitida ante HKA -> Emitida (HKA la conoce)."""
        row = {"is_void": 0, "bill_control": "00-00233094", "docstatus": 2}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "Emitida")

    def test_legacy_control_is_empty(self):
        """Factura del sistema anterior (control 5 dígitos, sin logs) -> vacío."""
        row = {"is_void": 0, "bill_control": "02422", "docstatus": 1,
               "remarks": "No hay observaciones", "posting_date": "2026-03-15"}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "")

    def test_legacy_control_post_cutoff_is_empty_not_pendiente(self):
        """Legacy con talonario fechada DESPUÉS del cutoff: ya tiene número
        fiscal previo -> vacío, no es un pendiente accionable."""
        row = {"is_void": 0, "bill_control": "02422", "docstatus": 1,
               "remarks": "No hay observaciones", "posting_date": "2026-04-15"}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "")

    def test_error_log_active_doc_is_error(self):
        row = {"is_void": 0, "bill_control": "", "docstatus": 1,
               "posting_date": "2026-06-01"}
        self.assertEqual(derive_hka_status(row, "Error", None, CUTOFF), "Error")

    def test_error_log_cancelled_doc_is_empty(self):
        """Cancelado con log Error: nada accionable -> vacío."""
        row = {"is_void": 0, "bill_control": "", "docstatus": 2,
               "posting_date": "2026-06-01"}
        self.assertEqual(derive_hka_status(row, "Error", None, CUTOFF), "")

    def test_post_cutoff_active_without_trace_is_pendiente(self):
        row = {"is_void": 0, "bill_control": None, "docstatus": 1,
               "posting_date": "2026-07-01"}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "Pendiente")

    def test_pre_cutoff_without_trace_is_empty(self):
        """Pre-arranque HKA: jamás se emitirá -> vacío, no Pendiente muerto."""
        row = {"is_void": 0, "bill_control": None, "docstatus": 1,
               "posting_date": "2026-03-10"}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "")

    def test_cancelled_without_trace_is_empty(self):
        row = {"is_void": 0, "bill_control": "", "docstatus": 2,
               "posting_date": "2026-07-01"}
        self.assertEqual(derive_hka_status(row, None, None, CUTOFF), "")


class TestDeriveHkaSeries(unittest.TestCase):
    """Cascada solo-evidencia: log response -> log payload -> remarks. Sin branch_map."""

    def test_serie_from_log_response(self):
        serie, source = derive_hka_series({}, SUCCESS_LOG)
        self.assertEqual((serie, source), ("MIR-01", "log_response"))

    def test_serie_from_log_payload_camelcase(self):
        """Los logs reales guardan el payload en camelCase."""
        payload = json.dumps({
            "documentoElectronico": {
                "encabezado": {"identificacionDocumento": {"serie": "MIR-03"}}
            }
        })
        log = {"response_received": json.dumps({"codigo": "200"}), "payload_sent": payload}
        serie, source = derive_hka_series({}, log)
        self.assertEqual((serie, source), ("MIR-03", "log_payload"))

    def test_serie_from_log_payload_pascalcase_variant(self):
        payload = json.dumps({
            "documentoElectronico": {
                "Encabezado": {"IdentificacionDocumento": {"Serie": "ARA-02"}}
            }
        })
        log = {"response_received": None, "payload_sent": payload}
        serie, source = derive_hka_series({}, log)
        self.assertEqual((serie, source), ("ARA-02", "log_payload"))

    def test_serie_from_remarks_without_log(self):
        row = {"remarks": HKA_REMARKS_SAMPLE, "branch": "DESIGNET"}
        serie, source = derive_hka_series(row, None)
        self.assertEqual((serie, source), ("MIR-01", "remarks"))

    def test_no_branch_fallback(self):
        """Sin fuente verificada -> vacío; la sucursal NUNCA infiere serie."""
        row = {"remarks": "No hay observaciones", "branch": "DESIGNET"}
        serie, source = derive_hka_series(row, None)
        self.assertEqual((serie, source), ("", ""))

    def test_invalid_json_does_not_raise(self):
        row = {"remarks": '{"resultado": {trunc', "branch": ""}
        log = {"response_received": "no-json", "payload_sent": "{tampoco"}
        serie, source = derive_hka_series(row, log)
        self.assertEqual((serie, source), ("", ""))


if __name__ == "__main__":
    unittest.main()
