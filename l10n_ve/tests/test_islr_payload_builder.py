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


_GET_SERIES = "l10n_ve.digital_invoice.tfhka_integration.get_active_billing_series"


def _resolve_series(**_kwargs):
    """Serie resuelta, tal como la devuelve get_active_billing_series."""
    return frappe._dict({"serie": "GAL-01"}), "01"


def _make_islr_doc(**overrides) -> frappe._dict:
    """Crea un mock de ISLR Withholding Voucher para el builder."""
    doc = frappe._dict({
        "name": "COMP-RET-ISLR-2026-00001",
        "voucher_number": "20260400000001",
        "creation": "2026-04-30 09:15:00",
        "posting_date": "2026-04-30",
        "supplier": "DESIGNET SERVICES 1815 C.A",
        "supplier_address": "CALLE ROSCIO EDIF CENTRO EMPRESARIAL",
        "empresa": "Galanet Solution C.A.",
        # Un comprobante sin sucursal no llega hasta acá: crearlo desde la factura
        # ya está bloqueado (test_branchless_invoice_blocked_before_creating_voucher)
        # y resolver la serie sin sucursal falla cerrado. El fixture lo refleja.
        "branch": "GALANET HQ",
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

    def setUp(self) -> None:
        super().setUp()
        # La serie se resuelve en el constructor del builder y hoy es obligatoria:
        # sin ella build_payload corta. Se mockea acá, una vez, porque lo que estos
        # tests miran es la forma del payload, no de dónde sale la serie --eso lo
        # cubre test_retention_series_fail_closed.
        patcher = patch(_GET_SERIES, side_effect=_resolve_series)
        self.addCleanup(patcher.stop)
        patcher.start()

    # ─────────────────────────────────────────────
    # Estructura general del payload
    # ─────────────────────────────────────────────

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_payload_structure(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """Verifica estructura raíz: documentoElectronico con encabezado y detallesRetencion."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        self.assertIn("documentoElectronico", payload)
        de: dict = payload["documentoElectronico"]
        self.assertIn("encabezado", de)
        self.assertIn("detallesRetencion", de)

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_tipo_documento_is_06(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """tipoDocumento debe ser '06' para ISLR."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        id_doc: dict = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "06")

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_transaction_id_prefix(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """transaccionId = 'RISLR' + número + fecha de creación (AAMMDDHHMMSS), único en el tiempo."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        id_doc: dict = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertTrue(id_doc["transaccionId"].startswith("RISLR"))
        # creation "2026-04-30 09:15:00" → sufijo 260430091500 (evita choque HKA 201 si el name se recicla)
        self.assertEqual(id_doc["transaccionId"], "RISLR20260400000001260430091500")

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_serie_and_branch_reach_the_payload(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """La serie resuelta viaja al payload: es el dato que HKA imprime y no se
        puede deshacer, así que se pinnea que llega y no queda en el camino."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        id_doc: dict = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["serie"], "GAL-01")
        self.assertEqual(id_doc["sucursal"], "01")

    # ─────────────────────────────────────────────
    # totalesRetencion
    # ─────────────────────────────────────────────

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_retention_totals_islr(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """totalISRL debe coincidir con totals_islr_amount formateado."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        totales: dict = payload["documentoElectronico"]["encabezado"]["totalesRetencion"]
        self.assertEqual(totales["totalISRL"], "9723.92")

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
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

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_porcentaje_conversion(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """rate=5 → porcentaje='0.05' (HKA espera fracción decimal)."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["porcentaje"], "0.05")
        self.assertEqual(detail["porcentajeRetencion"], "0.05")

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_fecha_formato(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """fechaDocumento debe estar en formato DD/MM/YYYY."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["fechaDocumento"], "15/04/2026")

    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.db.get_value", return_value=None)
    @patch("l10n_ve.digital_invoice.base_withholding_builder.frappe.get_cached_doc", side_effect=_mock_supplier)
    def test_detail_codigo_concepto(self, _mock_doc: MagicMock, _mock_db: MagicMock) -> None:
        """codigoConcepto debe mapear item.code correctamente."""
        doc = _make_islr_doc()
        builder = TFHKAISLRPayloadBuilder(doc)
        payload: dict = builder.build_payload()

        detail: dict = payload["documentoElectronico"]["detallesRetencion"][0]
        self.assertEqual(detail["codigoConcepto"], "P051")
