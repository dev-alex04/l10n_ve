# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para TFHKAISLRPayloadBuilder.

Valida que el payload JSON generado para la API TFHKA
cumpla con la estructura requerida para comprobantes
de retención de ISLR (tipo 06).
"""


from unittest.mock import patch, MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.digital_invoice.islr_payload_builder import TFHKAISLRPayloadBuilder


def _make_islr_doc(**overrides) -> frappe._dict:
    """Crea un mock de ISLR Withholding Voucher para el builder."""
    doc = frappe._dict({
        "name": "COMP-RET-ISLR-2026-00001",
        "voucher_number": "20260400000001",
        "posting_date": "2026-04-30",
        "supplier": "DESIGNET SERVICES 1815 C.A",
        "supplier_address": "CALLE ROSCIO EDIF CENTRO EMPRESARIAL",
        "empresa": "Galanet Solution C.A.",
        "totals_grand_total": 177947.55,
        "totals_islr_base_amount": 194478.20,
        "totals_islr_amount": 9723.92,
        "islr_withholding_voucher_item": [
            frappe._dict({
                "purchase_invoice": "ACC-PINV-2026-00001",
                "doc_no": "00002318",
                "bill_control": "00-00002318",
                "posting_date": "2026-04-15",
                "rate": 5.0,
                "subtracting": 0.0,
                "islr_amount": 9723.92,
                "code": "P051",
                "islr_base_amount": 194478.20,
                "grand_total": 177947.55,
            }),
        ],
    })
    doc.update(overrides)
    return doc


def _mock_supplier(*_args, **_kwargs) -> frappe._dict:
    """Mock del proveedor para get_cached_doc."""
    return frappe._dict({
        "name": "DESIGNET SERVICES 1815 C.A",
        "supplier_name": "DESIGNET SERVICES 1815 C.A",
        "tax_id": "J-50332501-2",
    })


class TestISLRPayloadBuilder(FrappeTestCase):
    """Tests para TFHKAISLRPayloadBuilder: estructura, totales y detalles."""

    # ─────────────────────────────────────────────
    # Estructura general del payload
    # ─────────────────────────────────────────────

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_payload_structure(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """Verifica estructura raíz: documentoElectronico con encabezado y detallesRetencion."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        self.assertIn("documentoElectronico", payload)
        de: dict = payload["documentoElectronico"]
        self.assertIn("encabezado", de)
        self.assertIn("detallesRetencion", de)

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_tipo_documento_is_06(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """tipoDocumento debe ser '06' para ISLR."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        id_doc: dict = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "06")

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_transaction_id_prefix(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """transaccionId debe iniciar con 'RISLR'."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        id_doc: dict = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertTrue(id_doc["transaccionId"].startswith("RISLR"))

    # ─────────────────────────────────────────────
    # totalesRetencion
    # ─────────────────────────────────────────────

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_retention_totals_islr(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """totalISRL debe coincidir con totals_islr_amount formateado."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        totales: dict = payload["documentoElectronico"]["encabezado"]["totalesRetencion"]
        self.assertEqual(totales["totalISRL"], "9723.92")

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_retention_totals_base_imponible(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """totalBaseImponible debe coincidir con totals_islr_base_amount."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        totales: dict = payload["documentoElectronico"]["encabezado"]["totalesRetencion"]
        self.assertEqual(totales["totalBaseImponible"], "194478.20")

    # ─────────────────────────────────────────────
    # detallesRetencion (líneas individuales)
    # ─────────────────────────────────────────────

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_porcentaje_conversion(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """rate=5 → porcentaje='0.05' (HKA espera fracción decimal)."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["porcentaje"], "0.05")
        self.assertEqual(detail["porcentajeRetencion"], "0.05")

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_fecha_formato(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """fechaDocumento debe estar en formato DD/MM/YYYY."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["fechaDocumento"], "15/04/2026")

    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_whithholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_codigo_concepto(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """codigoConcepto debe mapear item.code correctamente."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["codigoConcepto"], "P051")
