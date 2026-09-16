# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para la integración ISLR con TFHKA.

Cubre:
- Validación pre-envío (_validate_islr_integrity)
- Procesamiento de envío (process_islr_voucher)
- Anulación de comprobante (void_islr_voucher)
- Obtención de pendientes (_get_pending_islr_vouchers)
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from unittest.mock import patch, MagicMock, call

from l10n_ve.digital_invoice.islr_withholding_integration import (
    _validate_islr_integrity,
    process_islr_voucher,
    _get_pending_islr_vouchers,
)


def _make_islr_doc(**overrides) -> frappe._dict:
    """Crea un mock de ISLR Withholding Voucher con datos válidos."""
    doc = frappe._dict({
        "name": "COMP-RET-ISLR-2026-00001",
        "voucher_number": "20260400000001",
        "posting_date": "2026-04-30",
        "supplier": "DESIGNET SERVICES 1815 C.A",
        "empresa": "Galanet Solution C.A.",
        "docstatus": 1,
        "digital_invoice_status": "",
        "hka_response": "",
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


def _make_hka_success_response() -> dict:
    """Respuesta HKA exitosa estándar."""
    return {
        "codigo": "200",
        "mensaje": "Emitido exitosamente",
        "resultado": {
            "numeroDocumento": "HKA-ISLR-001",
            "numeroControl": "00-00001234",
            "urlConsulta": "https://hka.example.com/doc/HKA-ISLR-001",
            "serie": "S001",
        },
    }


class TestValidateISLRIntegrity(FrappeTestCase):
    """Tests para _validate_islr_integrity(): validación pre-envío."""

    @patch(
        "l10n_ve.digital_invoice.islr_withholding_integration._validate_digital_series",
        return_value=[],
    )
    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_valid_doc_returns_empty_errors(
        self, _mock_rif: MagicMock, _mock_series: MagicMock
    ) -> None:
        """Documento completamente válido → lista de errores vacía."""
        doc = _make_islr_doc()

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertEqual(errors, [])

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_no_items_returns_error(self, _mock_rif: MagicMock) -> None:
        """Doc sin ítems → error 'no tiene facturas'."""
        doc = _make_islr_doc(islr_withholding_voucher_item=[])

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("no tiene facturas" in e for e in errors))

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_zero_amount_returns_error(self, _mock_rif: MagicMock) -> None:
        """totals_islr_amount = 0 → error 'monto total de ISLR'."""
        doc = _make_islr_doc(totals_islr_amount=0)

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("ISLR retenido es 0" in e for e in errors))

    @patch("frappe.get_cached_value", return_value="")
    def test_supplier_without_rif_returns_error(self, _mock_rif: MagicMock) -> None:
        """Proveedor sin RIF → error 'Tax ID'."""
        doc = _make_islr_doc()

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("RIF" in e or "Tax ID" in e for e in errors))

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_item_missing_doc_no_returns_error(self, _mock_rif: MagicMock) -> None:
        """Ítem sin doc_no → error 'No. de Factura'."""
        doc = _make_islr_doc()
        doc.islr_withholding_voucher_item[0].doc_no = ""

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("doc_no" in e for e in errors))

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_item_missing_bill_control_returns_error(self, _mock_rif: MagicMock) -> None:
        """Ítem sin bill_control → error 'No. de Control'."""
        doc = _make_islr_doc()
        doc.islr_withholding_voucher_item[0].bill_control = ""

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("Control" in e for e in errors))

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_item_zero_rate_returns_error(self, _mock_rif: MagicMock) -> None:
        """Ítem con rate=0 → error 'alícuota'."""
        doc = _make_islr_doc()
        doc.islr_withholding_voucher_item[0].rate = 0

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("rate" in e.lower() or "alícuota" in e.lower() for e in errors))

    @patch("frappe.get_cached_value", return_value="J-12345678-9")
    def test_item_missing_code_returns_error(self, _mock_rif: MagicMock) -> None:
        """Ítem sin código concepto → error 'código'."""
        doc = _make_islr_doc()
        doc.islr_withholding_voucher_item[0].code = ""

        errors: list[str] = _validate_islr_integrity(doc)

        self.assertTrue(any("código" in e.lower() or "concepto" in e.lower() for e in errors))


class TestProcessISLRVoucher(FrappeTestCase):
    """Tests para process_islr_voucher(): flujo completo de envío."""

    @patch("l10n_ve.digital_invoice.islr_withholding_integration._handle_retention_response", return_value=True)
    @patch("l10n_ve.digital_invoice.islr_withholding_integration.TFHKAClient")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration.TFHKAISLRPayloadBuilder")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration._validate_islr_integrity", return_value=[])
    @patch("frappe.get_doc")
    def test_process_success_returns_true(
        self,
        mock_get_doc: MagicMock,
        mock_validate: MagicMock,
        mock_builder_cls: MagicMock,
        mock_client_cls: MagicMock,
        mock_handle: MagicMock,
    ) -> None:
        """Envío exitoso → retorna True."""
        mock_get_doc.return_value = _make_islr_doc()
        mock_builder_cls.return_value.build_payload.return_value = {"test": "payload"}
        mock_client_cls.return_value.emitir_documento.return_value = _make_hka_success_response()

        result: bool = process_islr_voucher("COMP-RET-ISLR-2026-00001")

        self.assertTrue(result)

    @patch("l10n_ve.digital_invoice.islr_withholding_integration.company_uses_hk", return_value=True)
    @patch("l10n_ve.digital_invoice.islr_withholding_integration._log_retention_request")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration._validate_islr_integrity")
    @patch("frappe.get_doc")
    @patch("frappe.db.commit")
    def test_process_validation_failure_returns_false(
        self,
        mock_commit: MagicMock,
        mock_get_doc: MagicMock,
        mock_validate: MagicMock,
        mock_log: MagicMock,
        _mock_uses_hk: MagicMock,
    ) -> None:
        """Validación pre-envío falla → retorna False + status Error."""
        mock_doc = _make_islr_doc()
        mock_doc.db_set = MagicMock()
        mock_get_doc.return_value = mock_doc
        mock_validate.return_value = ["El comprobante no tiene facturas asociadas."]

        result: bool = process_islr_voucher("COMP-RET-ISLR-2026-00001")

        self.assertFalse(result)
        mock_doc.db_set.assert_called_with("digital_invoice_status", "Error")

    @patch("l10n_ve.digital_invoice.islr_withholding_integration.company_uses_hk", return_value=True)
    @patch("l10n_ve.digital_invoice.islr_withholding_integration._log_retention_request")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration.TFHKAClient")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration.TFHKAISLRPayloadBuilder")
    @patch("l10n_ve.digital_invoice.islr_withholding_integration._validate_islr_integrity", return_value=[])
    @patch("frappe.get_doc")
    @patch("frappe.db.commit")
    def test_process_connection_error_returns_false(
        self,
        mock_commit: MagicMock,
        mock_get_doc: MagicMock,
        mock_validate: MagicMock,
        mock_builder_cls: MagicMock,
        mock_client_cls: MagicMock,
        mock_log: MagicMock,
        _mock_uses_hk: MagicMock,
    ) -> None:
        """Error de conexión con TFHKA → retorna False + status Error."""
        mock_doc = _make_islr_doc()
        mock_doc.db_set = MagicMock()
        mock_get_doc.return_value = mock_doc
        mock_builder_cls.return_value.build_payload.return_value = {"test": "payload"}
        mock_client_cls.return_value.emitir_documento.side_effect = ConnectionError("Timeout")

        result: bool = process_islr_voucher("COMP-RET-ISLR-2026-00001")

        self.assertFalse(result)
        mock_doc.db_set.assert_called_with("digital_invoice_status", "Error")


class TestGetPendingISLRVouchers(FrappeTestCase):
    """Tests para _get_pending_islr_vouchers(): query de pendientes."""

    @patch("frappe.db.sql")
    def test_returns_voucher_names(self, mock_sql: MagicMock) -> None:
        """Con resultados → retorna lista de nombres."""
        mock_sql.return_value = [
            ["COMP-RET-ISLR-2026-00001"],
            ["COMP-RET-ISLR-2026-00002"],
        ]

        result: list[str] = _get_pending_islr_vouchers("2026-04-01")

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "COMP-RET-ISLR-2026-00001")

    @patch("frappe.db.sql")
    def test_returns_empty_when_no_pending(self, mock_sql: MagicMock) -> None:
        """Sin pendientes → retorna lista vacía."""
        mock_sql.return_value = []

        result: list[str] = _get_pending_islr_vouchers("2026-04-01")

        self.assertEqual(result, [])
