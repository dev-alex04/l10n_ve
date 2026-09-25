# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para el campo notes de Sales Invoice en HKA.

Cubre la vista previa (get_invoice_preview_data). El payload real (el bloque «PDF»
de InfoAdicional) es de la plantilla de Galanet y sus tests viven en domina_isp
(domina_isp/tests/test_hka_info_adicional.py):
- La nota del usuario reemplaza solo "Nota"; "Periodo" conserva el
  período de servicio (no se pierde en la factura legal).
- "Periodo" y "Nota" salen del período de servicio de la factura
  (from_date/to_date), no del mes de emisión; sin período propio, del mes
  de posting_date.
- Fallback sin nota: "Nota" = mes/año del período.
- Sanitización idéntica en payload y preview (comillas dobles fuera,
  saltos de línea y espacios múltiples colapsados).
"""

from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from l10n_ve.digital_invoice.payload_builder import service_period_label
from l10n_ve.digital_invoice.tfhka_integration import get_invoice_preview_data


# ═══════════════════════════════════════════════════════════════════
# Helpers — payload
# ═══════════════════════════════════════════════════════════════════

_SUBSCRIPTION = frappe._dict({
    "current_invoice_start": "2026-07-01",
    "current_invoice_end": "2026-07-31",
})


class TestServicePeriodLabel(FrappeTestCase):
    def test_one_month(self) -> None:
        self.assertEqual(service_period_label(date(2026, 8, 1), date(2026, 8, 31)), "AGOSTO 2026")

    def test_two_months_of_the_same_year(self) -> None:
        self.assertEqual(service_period_label(date(2026, 8, 15), date(2026, 9, 14)), "AGOSTO - SEPTIEMBRE 2026")

    def test_two_months_across_years(self) -> None:
        self.assertEqual(service_period_label(date(2026, 12, 15), date(2027, 1, 14)), "DICIEMBRE 2026 - ENERO 2027")


# ═══════════════════════════════════════════════════════════════════
# Helpers — vista previa
# ═══════════════════════════════════════════════════════════════════

class _FakeDoc:
    """Objeto simple con .attr y .get() como un Document (attrs faltantes = None)."""

    def __init__(self, **data):
        self.__dict__.update(data)

    def __getattr__(self, _key):
        return None

    def get(self, key, default=None):
        return self.__dict__.get(key, default)


def _make_preview_invoice(**overrides) -> _FakeDoc:
    data = {
        "name": "ACC-SINV-2026-00001",
        "branch": "",
        "company": "GALANET",
        "customer": "CLIENTE PRUEBA",
        "posting_date": "2026-07-15",
        "posting_time": "10:00:00",
        "due_date": None,
        "address_display": "CALLE 1, CASA 2, SAN JUAN",
        "conversion_rate": 36.5,
        "currency": "USD",
        "subscription": "",
        "notes": "",
        "customer_address": None,
        "base_total_taxes_and_charges": 0,
        "total": 10.0,
        "taxes": [],
        "items": [
            frappe._dict({
                "item_code": "PLAN-10M",
                "item_name": "Plan 10 Megas",
                "qty": 1,
                "rate": 10.0,
                "amount": 10.0,
            })
        ],
    }
    data.update(overrides)
    return _FakeDoc(**data)


_SERIES = frappe._dict({
    "operation_mode": "Internal",
    "invoice_number_correlative": 42,
    "last_control_number": 100,
    "range_from": 1,
    "range_to": 99999,
    "prefix": "00",
    "serie": "MIR-01",
})


def _cached_doc_dispatch(doctype, _name=None):
    if doctype == "Company":
        return frappe._dict({
            "company_name": "GALANET",
            "tax_id": "J-00000000-0",
            "phone_no": "",
            "website": "",
        })
    if doctype == "Customer":
        return frappe._dict({
            "customer_name": "CLIENTE PRUEBA",
            "tax_id": "V-11222333-4",
            "territory": "ZONA CENTRO",
            "internet_services": [],
        })
    if doctype == "Subscription":
        return _SUBSCRIPTION
    raise AssertionError(f"get_cached_doc inesperado: {doctype}")


def _run_preview(invoice_doc) -> dict:
    ns = "l10n_ve.digital_invoice.tfhka_integration"
    with patch(f"{ns}.frappe.has_permission", return_value=True), \
         patch(f"{ns}.frappe.get_doc", return_value=invoice_doc), \
         patch(f"{ns}.get_active_billing_series", return_value=(_SERIES, "01")), \
         patch(f"{ns}.frappe.get_cached_doc", side_effect=_cached_doc_dispatch), \
         patch(f"{ns}.frappe.db.get_value", return_value=None), \
         patch(f"{ns}.is_juridical_customer", return_value=False):
        return get_invoice_preview_data("ACC-SINV-2026-00001")


# ═══════════════════════════════════════════════════════════════════
# Vista previa (debe espejar el payload)
# ═══════════════════════════════════════════════════════════════════

class TestInvoiceNotesPreview(FrappeTestCase):
    """La preview muestra nota y periodo por separado, igual que el PDF."""

    def test_preview_shows_nota_and_subscription_period(self) -> None:
        """Con suscripción + nota: nota visible y periodo = rango real."""
        data = _run_preview(_make_preview_invoice(
            notes="Ajuste acordado con el cliente", subscription="SUB-0001",
        ))

        self.assertEqual(data["nota"], "Ajuste acordado con el cliente")
        self.assertEqual(data["periodo"], "Desde 01/07/2026 hasta 31/07/2026")

    def test_preview_nota_fallback_without_notes(self) -> None:
        """Sin nota: nota = mes/año, periodo = rango del mes de posting_date."""
        data = _run_preview(_make_preview_invoice())

        self.assertEqual(data["nota"], "JULIO 2026")
        self.assertEqual(data["periodo"], "Desde 01/07/2026 hasta 31/07/2026")

    def test_preview_notes_do_not_leak_into_period(self) -> None:
        """Con nota y sin suscripción: periodo = rango del mes de posting_date."""
        data = _run_preview(_make_preview_invoice(notes="Nota del operador"))

        self.assertEqual(data["nota"], "Nota del operador")
        self.assertEqual(data["periodo"], "Desde 01/07/2026 hasta 31/07/2026")

    def test_preview_sanitization_mirrors_payload(self) -> None:
        """La normalización de la preview es idéntica a la del payload."""
        data = _run_preview(_make_preview_invoice(
            notes='Ajuste "especial"\ncon   saltos\ny  espacios',
        ))

        self.assertEqual(data["nota"], "Ajuste especial con saltos y espacios")

    def test_preview_uses_the_service_period_like_the_payload(self) -> None:
        """Borrador de agosto cobrado en septiembre: la vista previa dice agosto, como el PDF."""
        data = _run_preview(_make_preview_invoice(
            posting_date="2026-09-08", from_date="2026-08-01", to_date="2026-08-31",
        ))

        self.assertEqual(data["nota"], "AGOSTO 2026")
        self.assertEqual(data["periodo"], "Desde 01/08/2026 hasta 31/08/2026")
