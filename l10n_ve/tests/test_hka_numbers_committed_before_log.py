# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Los números que devuelve HKA se confirman antes del log y del asiento.

Si después falla el log (esquema sin migrar entre deploy y migrate) o hay un deadlock en el
asiento, el rollback no debe deshacer los números de un documento que HKA ya emitió: el
reintento recibiría el 201 de duplicado y el documento quedaría sin control en el ERP.
Pasó con una guía de despacho en HKA demo el 24-sep; el mismo hueco estaba en la factura
(también NC y ND) y en los comprobantes de retención.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.digital_invoice import retention_integration, tfhka_integration

_OK = {"codigo": "200", "resultado": {"numeroDocumento": "5", "numeroControl": "00-00000013", "serie": ""}}


class TestInvoiceNumbersCommittedBeforeLog(unittest.TestCase):
    def test_commit_between_numbers_and_log(self):
        order: list[str] = []
        doc = frappe._dict(doctype="Sales Invoice", name="ACC-SINV-0001")
        series = frappe._dict(operation_mode="Third Party")
        # `today()` lee la zona horaria de System Settings; con la caché fría (tras un
        # migrate) la carga pasaría por el `get_value` falso de abajo y rompería la Meta.
        frappe.utils.today()
        with patch.object(tfhka_integration.frappe.db, "set_value",
                          side_effect=lambda *a, **k: order.append("set_value")), \
             patch.object(tfhka_integration.frappe.db, "get_value",
                          side_effect=lambda *a, **k: frappe._dict(bill_no="5", bill_control="00-00000013")
                          if k.get("as_dict") else "5"), \
             patch.object(tfhka_integration.frappe.db, "commit", side_effect=lambda: order.append("commit")), \
             patch.object(tfhka_integration, "_sync_gl_entries_date", side_effect=lambda *a, **k: order.append("gl")), \
             patch.object(tfhka_integration, "_log_request", side_effect=lambda *a, **k: order.append("log")), \
             patch.dict(frappe.flags, {"in_test": False}):
            tfhka_integration._handle_hka_response(doc, doc.name, {}, _OK, series)

        self.assertIn("commit", order)
        first_commit = order.index("commit")
        self.assertEqual(order[:first_commit], ["set_value", "set_value"])
        self.assertLess(first_commit, order.index("gl"))
        self.assertLess(first_commit, order.index("log"))


class TestRetentionNumbersCommittedBeforeLog(unittest.TestCase):
    def test_commit_between_numbers_and_log(self):
        order: list[str] = []
        doc = MagicMock()
        doc.name = "COMP-RET-IVA-0001"
        doc.db_set.side_effect = lambda *a, **k: order.append("db_set")
        with patch.object(retention_integration.frappe.db, "commit", side_effect=lambda: order.append("commit")), \
             patch.object(retention_integration, "_log_retention_request",
                          side_effect=lambda *a, **k: order.append("log")), \
             patch.dict(frappe.flags, {"in_test": False}):
            self.assertTrue(retention_integration._handle_retention_response(doc, {}, _OK, False))

        self.assertEqual(order, ["db_set", "commit", "log"])
