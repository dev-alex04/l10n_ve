# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la derivación de hka_status/hka_series del backfill
(l10n_ve.scripts.backfill_hka_status).

Suite 100% unittest + mocks (sin BD ni FrappeTestCase): el módulo solo
importa frappe a nivel top-level, así que se importa sin arrancar el site.
"""

import json
import unittest

from l10n_ve.scripts.backfill_hka_status import (
    derive_hka_series,
    derive_hka_status,
)

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


class TestDeriveHkaStatus(unittest.TestCase):
    """Precedencia: Anulada > Emitida > Error > Pendiente."""

    def test_void_wins_over_emitida(self):
        """is_void=1 con datos HKA previos -> Anulada (la anulación domina)."""
        row = {"is_void": 1, "bill_control": "00-00233094"}
        self.assertEqual(derive_hka_status(row, "Success"), "Anulada")

    def test_bill_control_derives_emitida(self):
        """bill_control no vacío -> Emitida, incluso sin log (dedup histórico)."""
        row = {"is_void": 0, "bill_control": "00-00233094"}
        self.assertEqual(derive_hka_status(row, None), "Emitida")

    def test_error_log_without_control_derives_error(self):
        """Sin bill_control y último log Error -> Error."""
        row = {"is_void": 0, "bill_control": ""}
        self.assertEqual(derive_hka_status(row, "Error"), "Error")

    def test_no_trace_derives_pendiente(self):
        """Sin bill_control, sin log -> Pendiente."""
        row = {"is_void": 0, "bill_control": None}
        self.assertEqual(derive_hka_status(row, None), "Pendiente")

    def test_cancelled_without_void_keeps_derivation(self):
        """docstatus=2 SIN is_void no fuerza Anulada (deriva normal)."""
        row = {"is_void": 0, "bill_control": "00-1", "docstatus": 2}
        self.assertEqual(derive_hka_status(row, None), "Emitida")

    def test_success_log_without_control_is_pendiente(self):
        """Log Success pero sin bill_control (persistencia parcial) -> Pendiente
        (lo repara el cron de reconciliación, no el backfill)."""
        row = {"is_void": 0, "bill_control": ""}
        self.assertEqual(derive_hka_status(row, "Success"), "Pendiente")


class TestDeriveHkaSeries(unittest.TestCase):
    """Cascada: log response -> log payload -> remarks -> branch map."""

    def test_serie_from_log_response(self):
        log = {"response_received": HKA_REMARKS_SAMPLE, "payload_sent": None}
        serie, source = derive_hka_series({}, log, {})
        self.assertEqual((serie, source), ("MIR-01", "log_response"))

    def test_serie_from_log_payload_when_response_lacks_it(self):
        payload = json.dumps({
            "documentoElectronico": {
                "Encabezado": {"IdentificacionDocumento": {"Serie": "ARA-02"}}
            }
        })
        log = {"response_received": json.dumps({"codigo": "200"}), "payload_sent": payload}
        serie, source = derive_hka_series({}, log, {})
        self.assertEqual((serie, source), ("ARA-02", "log_payload"))

    def test_serie_from_remarks_without_log(self):
        row = {"remarks": HKA_REMARKS_SAMPLE, "branch": "MIR-01"}
        serie, source = derive_hka_series(row, None, {"MIR-01": "OTRA"})
        self.assertEqual((serie, source), ("MIR-01", "remarks"))

    def test_serie_from_branch_map_as_last_resort(self):
        row = {"remarks": "Pago recibido por transferencia", "branch": "DC-01"}
        serie, source = derive_hka_series(row, None, {"DC-01": "DC-01"})
        self.assertEqual((serie, source), ("DC-01", "branch_map"))

    def test_invalid_json_does_not_raise(self):
        """remarks/response con JSON roto o texto plano -> cae en cascada sin lanzar."""
        row = {"remarks": '{"resultado": {trunc', "branch": ""}
        log = {"response_received": "no-json", "payload_sent": "{tampoco"}
        serie, source = derive_hka_series(row, log, {})
        self.assertEqual((serie, source), ("", ""))


if __name__ == "__main__":
    unittest.main()
