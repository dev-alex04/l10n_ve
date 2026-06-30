import unittest
from unittest.mock import patch

import frappe
from l10n_ve.digital_invoice.payload_builder import (
    TFHKAPayloadBuilder,
    resolve_zone_from_address,
)
from l10n_ve.tests.helpers import MockDoc

_PB = "l10n_ve.digital_invoice.payload_builder"


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
        "base_net_total": 100.0,
        "base_total_taxes_and_charges": 16.0,
        "total_taxes_and_charges": 16.0,
        "grand_total": 116.0,
        "base_grand_total": 116.0,
        "discount_amount": 0.0,
        "base_discount_amount": 0.0,
        "tax_id": "J-12345678-9",
        "subscription": "SUB-00001",
        "taxes": [
            frappe._dict({
                "account_head": "IVA 16% - TC",
                "description": "IVA 16%",
                "rate": 16.0,
                "charge_type": "VAT",
                "tax_amount": 16.0,
                "base_tax_amount": 16.0,
                "add_deduct_tax": "Add",
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


def _make_series_doc() -> MockDoc:
    """Mock mínimo de VE Digital Billing Series."""
    return MockDoc(serie="SERIE01", operation_mode="Internal")


class TestTFHKAPayloadBuilder(unittest.TestCase):
    """Tests unitarios para el constructor de payloads TFHKA."""

    _COMMON_PATCHES = {
        "get_cached_doc": patch(
            "l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc",
            side_effect=_mock_customer,
        ),
        "get_cached_value": patch(
            "l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value",
            return_value="USD",
        ),
        "zona_nodo": patch.object(
            TFHKAPayloadBuilder,
            "_resolve_zona_and_nodo",
            return_value=("Zona Test", "NODO-01"),
        ),
        "tfhka_code": patch.object(
            TFHKAPayloadBuilder,
            "_resolve_tfhka_code",
            return_value="CODE01",
        ),
    }

    def _build(self, **doc_overrides) -> dict:
        """Helper: crea doc, builder y ejecuta build_payload con todos los patches."""
        doc = _make_base_doc(**doc_overrides)
        builder = TFHKAPayloadBuilder(doc, series_doc=_make_series_doc())
        return builder.build_payload()

    # ── Estructura ────────────────────────────────────────────────

    def test_factura_basica_estructura(self):
        """Verifica la estructura general del payload y que las keys estén en camelCase."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build()

        self.assertIn("documentoElectronico", payload)
        de = payload["documentoElectronico"]
        self.assertIn("encabezado", de)
        self.assertIn("detallesItems", de)

    # ── Totales ───────────────────────────────────────────────────

    def test_factura_basica_totales(self):
        """Verifica los totales de una factura simple: 100 USD + 16% IVA = 116."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build()

        totales = payload["documentoElectronico"]["encabezado"]["totales"]
        self.assertEqual(totales["subtotal"], "100.00")
        self.assertEqual(totales["totalIVA"], "16.00")
        self.assertEqual(totales["montoTotalConIVA"], "116.00")
        self.assertEqual(totales["totalAPagar"], "116.00")

    # ── Identificación documento ──────────────────────────────────

    def test_factura_identificacion_documento(self):
        """Verifica tipo de documento y número para factura regular."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build()

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "01")
        self.assertEqual(id_doc["numeroDocumento"], "00001")

    def test_nota_credito_tipo_documento(self):
        """Verifica que una nota de crédito genera tipo '02'."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(
                is_return=1, bill_no="NC-00001",
                reason="Devolución de mercancía",
            )

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "02")
        self.assertEqual(id_doc["numeroDocumento"], "NC-00001")

    def test_nota_debito_tipo_documento(self):
        """Verifica que una nota de débito genera tipo '03'."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(
                is_debit_note=1, debit_note_no="ND-00001", bill_no=None,
                reason="Ajuste de precio",
            )

        id_doc = payload["documentoElectronico"]["encabezado"]["identificacionDocumento"]
        self.assertEqual(id_doc["tipoDocumento"], "03")

    # ── Exento ────────────────────────────────────────────────────

    def test_factura_exenta(self):
        """Verifica que un ítem exento va al monto exento total, no al gravado."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(
                base_total_taxes_and_charges=0.0,
                net_total=50.0,
                base_net_total=50.0,
                grand_total=50.0,
                base_grand_total=50.0,
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

        totales = payload["documentoElectronico"]["encabezado"]["totales"]
        self.assertEqual(totales["montoExentoTotal"], "0.00")
        self.assertEqual(totales["montoGravadoTotal"], "50.00")
        self.assertEqual(totales["totalIVA"], "0.00")

    # ── Multimoneda ───────────────────────────────────────────────

    def test_factura_multimoneda_totales_otra_moneda(self):
        """Verifica que TotalesOtraMoneda se genera cuando currency != company_currency."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             patch("l10n_ve.digital_invoice.payload_builder.frappe.get_cached_value",
                   return_value="VEF"), \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(conversion_rate=36.5)

        otra_moneda = payload["documentoElectronico"]["encabezado"].get("totalesOtraMoneda")
        self.assertIsNotNone(otra_moneda)
        self.assertEqual(otra_moneda["moneda"], "USD")
        self.assertEqual(otra_moneda["subtotal"], "100.00")

    # ── Formas de pago ────────────────────────────────────────────

    def test_formas_pago_credito(self):
        """Sin payments = crédito (forma 99)."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(payments=[])

        formas = payload["documentoElectronico"]["encabezado"]["totales"]["formasPago"]
        self.assertEqual(len(formas), 1)
        self.assertEqual(formas[0]["forma"], "99")

    def test_formas_pago_con_pagos(self):
        """Con payments = se genera una forma de pago por cada línea."""
        with self._COMMON_PATCHES["get_cached_doc"], \
             self._COMMON_PATCHES["get_cached_value"], \
             self._COMMON_PATCHES["zona_nodo"], \
             self._COMMON_PATCHES["tfhka_code"]:
            payload = self._build(
                payments=[
                    frappe._dict({"mode_of_payment": "Transferencia Banco A", "amount": 116.0}),
                ]
            )

        formas = payload["documentoElectronico"]["encabezado"]["totales"]["formasPago"]
        self.assertEqual(len(formas), 1)
        self.assertEqual(formas[0]["monto"], "116.00")

    # ── Resolución de Zona/Nodo (sin mockear _resolve_zona_and_nodo) ──

    def test_resolve_zone_uses_territory_when_present(self):
        """Con territory en el Customer, se usa ese valor y no se invoca el fallback."""
        customer = frappe._dict({"territory": "Zona Test", "internet_services": []})
        with self._COMMON_PATCHES["get_cached_value"]:
            builder = TFHKAPayloadBuilder(
                _make_base_doc(subscription=None), series_doc=_make_series_doc()
            )
        with patch(f"{_PB}.frappe.get_cached_doc", return_value=customer), \
             patch(f"{_PB}.resolve_zone_from_address") as m_fallback:
            zone, _node = builder._resolve_zona_and_nodo()
        self.assertEqual(zone, "Zona Test")
        m_fallback.assert_not_called()

    def test_resolve_zone_falls_back_to_municipality(self):
        """Sin territory, la Zona cae al municipio vía resolve_zone_from_address."""
        customer = frappe._dict({"territory": "", "internet_services": []})
        with self._COMMON_PATCHES["get_cached_value"]:
            builder = TFHKAPayloadBuilder(
                _make_base_doc(subscription=None), series_doc=_make_series_doc()
            )
        with patch(f"{_PB}.frappe.get_cached_doc", return_value=customer), \
             patch(f"{_PB}.resolve_zone_from_address", return_value="Libertador") as m_fallback:
            zone, _node = builder._resolve_zona_and_nodo()
        self.assertEqual(zone, "Libertador")
        m_fallback.assert_called_once()

    def test_empty_zone_without_municipality_raises(self):
        """Sin territory ni municipio, la validación lanza el throw de Zona (genera el log de error)."""
        with self._COMMON_PATCHES["get_cached_value"]:
            builder = TFHKAPayloadBuilder(
                _make_base_doc(conversion_rate=0, subscription=None),
                series_doc=_make_series_doc(),
            )
        builder.zona = None
        builder.nodo = "NODO-01"
        with self.assertRaisesRegex(frappe.ValidationError, "Zona"):
            builder._build_info_adicional()

    # ── Parse Tax ID (estáticos, sin patches) ─────────────────────

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


class TestResolveZoneFromAddress(unittest.TestCase):
    """Tests del fallback de Zona: municipio (legible) de la dirección del cliente."""

    _PATH = "l10n_ve.digital_invoice.payload_builder.frappe"

    def test_with_customer_address_returns_readable_municipality(self):
        """Con customer_address explícito: parish → municipality → nombre legible."""
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=["VE-PARISH-hash", "VE-MUNI-hash", "Libertador"]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertEqual(zone, "Libertador")

    def test_without_customer_address_uses_billing_address(self):
        """Sin customer_address: busca el Billing Address del Customer vía SQL."""
        with patch(f"{self._PATH}.db.sql", return_value=[["ADDR-BILL"]]) as m_sql, \
             patch(f"{self._PATH}.get_cached_value",
                   side_effect=["VE-PARISH", "VE-MUNI", "Chacao"]):
            zone = resolve_zone_from_address("Customer A", None)
        self.assertEqual(zone, "Chacao")
        m_sql.assert_called_once()

    def test_without_billing_address_returns_none(self):
        """Sin customer_address y sin Billing Address → None (mantiene el throw aguas arriba)."""
        with patch(f"{self._PATH}.db.sql", return_value=[]):
            zone = resolve_zone_from_address("Customer A", None)
        self.assertIsNone(zone)

    def test_without_any_geo_returns_none(self):
        """Dirección sin parish, county ni city → None (mantiene el throw aguas arriba)."""
        with patch(f"{self._PATH}.get_cached_value", return_value=None):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertIsNone(zone)

    def test_parish_without_municipality_falls_back_to_county(self):
        """Parish sin municipio asignado → cae a county (Link a VE Municipality)."""
        # parish, VE Parish.municipality(None), county, VE Municipality.municipality
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=["VE-PARISH", None, "VE-MUNI-hash", "Tovar"]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertEqual(zone, "Tovar")

    def test_falls_back_to_county_municipality(self):
        """Sin parish pero con county → municipio legible vía VE Municipality."""
        # parish(None), county, VE Municipality.municipality
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=[None, "VE-MUNI-hash", "Tovar"]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertEqual(zone, "Tovar")

    def test_county_freetext_returned_as_is(self):
        """county con texto libre (no existe como VE Municipality) → se devuelve tal cual."""
        # parish(None), county="Tovar", municipality(None), name(None: el registro no existe)
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=[None, "Tovar", None, None]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertEqual(zone, "Tovar")

    def test_county_orphaned_id_never_emits_hash(self):
        """county con un id huérfano de VE Municipality (existe sin etiqueta) → nunca emite el hash."""
        # parish(None), county="ORPHAN-hash", municipality(None), name("ORPHAN-hash": SÍ existe), city(None)
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=[None, "ORPHAN-hash", None, "ORPHAN-hash", None]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertIsNone(zone)

    def test_falls_back_to_city_when_no_parish_or_county(self):
        """Sin parish ni county → último recurso: ciudad/pueblo legible vía VE City."""
        # parish(None), county(None), city, VE City.city
        with patch(f"{self._PATH}.get_cached_value",
                   side_effect=[None, None, "VE-CITY-hash", "Colonia Tovar"]):
            zone = resolve_zone_from_address("Customer A", "ADDR-001")
        self.assertEqual(zone, "Colonia Tovar")
