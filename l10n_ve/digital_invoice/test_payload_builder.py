import unittest
from unittest.mock import patch

import frappe
from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.tests.helpers import MockDoc


def _make_base_doc(**overrides) -> MockDoc:
    """Construye un mock de Sales Invoice con los campos mínimos requeridos."""
    data = {
        "name": "INV-00001",
        "is_return": 0,
        "is_debit_note": 0,
        "posting_date": "2026-03-24",
        "posting_time": "14:30:00",
        "due_date": "2026-03-24",
        "is_pos": 0,
        "customer": "Customer A",
        "customer_name": "Customer A",
        "company": "Test Company",
        "currency": "USD",
        "conversion_rate": 1.0,
        "address_display": "Av Principal, Caracas",
        "contact_mobile": "0412-1234567",
        "contact_email": "test@example.com",
        "bill_no": "00001",
        "credit_note_no": None,
        "debit_note_no": None,
        "return_against": None,
        "net_total": 100.0,
        "base_total_taxes_and_charges": 16.0,
        "total_taxes_and_charges": 16.0,
        "grand_total": 116.0,
        "base_grand_total": 116.0,
        "discount_amount": 0.0,
        "base_discount_amount": 0.0,
        "taxes": [
            frappe._dict({
                "account_head": "IVA 16% - TC",
                "description": "IVA 16%",
                "rate": 16.0,
            })
        ],
        "items": [
            frappe._dict({
                "item_code": "ITEM-1",
                "item_name": "Test Item",
                "item_group": "Products",
                "qty": 1,
                "rate": 100.0,
                "amount": 100.0,
                "discount_amount": 0.0,
                "is_exempt": 0,
            })
        ],
        "payments": [],
    }
    data.update(overrides)
    return MockDoc(**data)


def _mock_customer(*_args, **_kwargs):
    return frappe._dict({
        "tax_id": "J-12345678-9",
        "customer_name": "Customer A",
        "territory": "Zona Test",
        "internet_services": [],
    })


class TestTFHKAPayloadBuilder(unittest.TestCase):
    """Tests unitarios para el constructor de payloads TFHKA."""

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_factura_basica_estructura(self, _mock_val, _mock_doc):
        """Verifica la estructura general del payload y que las keys estén en camelCase."""
        doc = _make_base_doc()
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        self.assertIn("documentoElectronico", payload)
        de = payload["documentoElectronico"]
        self.assertIn("encabezado", de)
        self.assertIn("detallesItems", de)

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_factura_basica_totales(self, _mock_val, _mock_doc):
        """Verifica los totales de una factura simple: 100 USD + 16% IVA = 116."""
        doc = _make_base_doc()
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        totales = payload["documentoElectronico"]["encabezado"]["totales"]
        self.assertEqual(totales["subtotal"], "100.00")
        self.assertEqual(totales["totalIVA"], "16.00")
        self.assertEqual(totales["montoTotalConIVA"], "116.00")
        self.assertEqual(totales["totalAPagar"], "116.00")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_factura_identificacion_documento(self, _mock_val, _mock_doc):
        """Verifica tipo de documento y número para factura regular."""
        doc = _make_base_doc()
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "01")
        self.assertEqual(id_doc["numeroDocumento"], "00001")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_nota_credito_tipo_documento(self, _mock_val, _mock_doc):
        """Verifica que una nota de crédito genera tipo '02'."""
        doc = _make_base_doc(is_return=1, credit_note_no="NC-00001", bill_no=None, reason="Devolución de mercancía")
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "02")
        self.assertEqual(id_doc["numeroDocumento"], "NC-00001")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_nota_debito_tipo_documento(self, _mock_val, _mock_doc):
        """Verifica que una nota de débito genera tipo '03'."""
        doc = _make_base_doc(is_debit_note=1, debit_note_no="ND-00001", bill_no=None, reason="Ajuste de precio")
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "03")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_factura_exenta(self, _mock_val, _mock_doc):
        """Verifica que un ítem exento va al monto exento total, no al gravado."""
        doc = _make_base_doc(
            base_total_taxes_and_charges=0.0,
            taxes=[],
            items=[
                frappe._dict({
                    "item_code": "ITEM-EX",
                    "item_name": "Servicio Exento",
                    "item_group": "Services",
                    "qty": 1,
                    "rate": 50.0,
                    "amount": 50.0,
                    "is_exempt": 1,
                })
            ],
        )
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        totales = payload["documentoElectronico"]["encabezado"]["totales"]
        self.assertEqual(totales["montoExentoTotal"], "50.00")
        self.assertEqual(totales["montoGravadoTotal"], "0.00")
        self.assertEqual(totales["totalIVA"], "0.00")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="VEF")
    def test_factura_multimoneda_totales_otra_moneda(self, _mock_val, _mock_doc):
        """Verifica que TotalesOtraMoneda se genera cuando currency != company_currency."""
        doc = _make_base_doc(conversion_rate=36.5)
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        otra_moneda = payload["documentoElectronico"]["encabezado"].get("totalesOtraMoneda")
        self.assertIsNotNone(otra_moneda)
        self.assertEqual(otra_moneda["moneda"], "USD")
        self.assertEqual(otra_moneda["subtotal"], "100.00")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_formas_pago_credito(self, _mock_val, _mock_doc):
        """Sin payments = crédito (forma 99)."""
        doc = _make_base_doc(payments=[])
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        formas = payload["documentoElectronico"]["encabezado"]["totales"]["formasPago"]
        self.assertEqual(len(formas), 1)
        self.assertEqual(formas[0]["forma"], "99")

    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc", side_effect=_mock_customer)
    @patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value", return_value="USD")
    def test_formas_pago_con_pagos(self, _mock_val, _mock_doc):
        """Con payments = se genera una forma de pago por cada línea."""
        doc = _make_base_doc(
            payments=[
                frappe._dict({"mode_of_payment": "Transferencia Banco A", "amount": 116.0}),
            ]
        )
        builder = TFHKAPayloadBuilder(doc)
        payload = builder.build_payload()

        formas = payload["documentoElectronico"]["encabezado"]["totales"]["formasPago"]
        self.assertEqual(len(formas), 1)
        self.assertEqual(formas[0]["monto"], "116.00")

    def test_parse_tax_id_con_guion(self):
        """RIF con guión: J-12345678-9."""
        tipo, num = TFHKAPayloadBuilder._parse_tax_id("J-12345678-9")
        self.assertEqual(tipo, "J")
        self.assertEqual(num, "123456789")

    def test_parse_tax_id_sin_guion(self):
        """RIF sin guión: V12345678."""
        tipo, num = TFHKAPayloadBuilder._parse_tax_id("V12345678")
        self.assertEqual(tipo, "V")
        self.assertEqual(num, "12345678")

    def test_parse_tax_id_vacio(self):
        """RIF vacío retorna valores por defecto."""
        tipo, num = TFHKAPayloadBuilder._parse_tax_id("")
        self.assertEqual(tipo, "V")
        self.assertEqual(num, "000000000")

    def test_parse_tax_id_gobierno(self):
        """RIF de gobierno: G-20000001-0."""
        tipo, num = TFHKAPayloadBuilder._parse_tax_id("G-20000001-0")
        self.assertEqual(tipo, "G")
        self.assertEqual(num, "200000010")
