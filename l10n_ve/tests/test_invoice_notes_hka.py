# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests unitarios para el campo notes de Sales Invoice en HKA.

Cubre payload real (_build_info_adicional) y vista previa
(get_invoice_preview_data), verificando que ambos coinciden:
- La nota del usuario reemplaza solo "Nota"; "Periodo" conserva el
  período de servicio (no se pierde en la factura legal).
- "Periodo" y "Nota" salen del período de servicio de la factura
  (from_date/to_date), no del mes de emisión; sin período propio, del mes
  de posting_date.
- Fallback sin nota: "Nota" = mes/año del período.
- Sanitización idéntica en payload y preview (comillas dobles fuera,
  saltos de línea y espacios múltiples colapsados).
"""

import ast
from datetime import date

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import MagicMock, patch

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder, service_period_label
from l10n_ve.digital_invoice.tfhka_integration import get_invoice_preview_data


# ═══════════════════════════════════════════════════════════════════
# Helpers — payload
# ═══════════════════════════════════════════════════════════════════

def _make_invoice(**overrides) -> frappe._dict:
    """Mock mínimo de Sales Invoice para _build_info_adicional."""
    doc = frappe._dict({
        "name": "ACC-SINV-2026-00001",
        "customer": "CLIENTE PRUEBA",
        "company": "GALANET",
        "posting_date": "2026-07-15",
        # 0 => no se construye TasaCambio (evita is_juridical/resolve_rate)
        "conversion_rate": 0,
        "currency": "USD",
        "tax_id": "J-12345678-9",
        "address_display": "CALLE 1, CASA 2, SAN JUAN",
        "subscription": "",
        "notes": "",
    })
    doc.update(overrides)
    return doc


def _make_builder(doc) -> TFHKAPayloadBuilder:
    """Instancia el builder sin pasar por __init__ (sin BD)."""
    builder = TFHKAPayloadBuilder.__new__(TFHKAPayloadBuilder)
    builder.doc = doc
    builder.tasa_fecha = None
    builder.zona = "ZONA CENTRO"
    builder.nodo = "NODO 1"
    builder.series_doc = frappe._dict({"serie": "MIR-01"})
    builder._bill_no_original = ""
    return builder


def _extract_pdf_dict(info_adicional: list) -> dict:
    """Parsea el string python-like del campo PDF que consume HKA."""
    valor = next(e["Valor"] for e in info_adicional if e["Campo"] == "PDF")
    return ast.literal_eval(valor)


_SUBSCRIPTION = frappe._dict({
    "current_invoice_start": "2026-07-01",
    "current_invoice_end": "2026-07-31",
})


# ═══════════════════════════════════════════════════════════════════
# Payload real (dict PDF enviado a HKA)
# ═══════════════════════════════════════════════════════════════════

class TestInvoiceNotesPayload(FrappeTestCase):
    """La nota reemplaza solo 'Nota'; 'Periodo' conserva la suscripción."""

    @patch(
        "l10n_ve.digital_invoice.payload_builder.frappe.get_cached_doc",
        return_value=_SUBSCRIPTION,
    )
    def test_notes_replace_nota_and_period_keeps_subscription_range(
        self, _mock_sub: MagicMock
    ) -> None:
        """Con suscripción + nota: Nota = nota, Periodo = rango real."""
        doc = _make_invoice(notes="Ajuste acordado con el cliente", subscription="SUB-0001")
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "Ajuste acordado con el cliente")
        self.assertEqual(pdf["Periodo"], "Desde el 01/07/2026 hasta el 31/07/2026")

    def test_nota_fallback_without_notes(self) -> None:
        """Sin nota ni suscripción: Nota = mes/año, Periodo = rango del mes de posting_date."""
        doc = _make_invoice()
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "JULIO 2026")
        self.assertEqual(pdf["Periodo"], "Desde el 01/07/2026 hasta el 31/07/2026")

    def test_notes_without_subscription_keep_default_period(self) -> None:
        """Con nota y sin suscripción: Periodo = rango del mes de posting_date."""
        doc = _make_invoice(notes="Corresponde a instalacion del servicio")
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "Corresponde a instalacion del servicio")
        self.assertEqual(pdf["Periodo"], "Desde el 01/07/2026 hasta el 31/07/2026")

    def test_notes_sanitization_in_payload(self) -> None:
        """Comillas dobles fuera; saltos de línea y espacios colapsados."""
        doc = _make_invoice(notes='Ajuste "especial"\ncon   saltos\ny  espacios')
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "Ajuste especial con saltos y espacios")


class TestServicePeriodPayload(FrappeTestCase):
    """«Periodo» y «Nota» dicen qué mes se cobra, no cuándo se emite.

    Reportado por Galanet el 10-sep-2026: un borrador de agosto cobrado en septiembre se
    contabiliza en septiembre, y el PDF de HKA decía «SEPTIEMBRE 2026».
    """

    def test_old_month_invoice_emitted_later_keeps_its_service_month(self) -> None:
        """Borrador de agosto cobrado en septiembre: la emisión es de septiembre, el período de agosto."""
        doc = _make_invoice(posting_date="2026-09-08", from_date="2026-08-01", to_date="2026-08-31")
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "AGOSTO 2026")
        self.assertEqual(pdf["Periodo"], "Desde el 01/08/2026 hasta el 31/08/2026")

    def test_notes_replace_nota_but_not_the_service_period(self) -> None:
        doc = _make_invoice(
            posting_date="2026-09-08", from_date="2026-08-01", to_date="2026-08-31", notes="Pago atrasado",
        )
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "Pago atrasado")
        self.assertEqual(pdf["Periodo"], "Desde el 01/08/2026 hasta el 31/08/2026")

    def test_period_across_two_months_prints_its_exact_dates(self) -> None:
        doc = _make_invoice(posting_date="2026-09-20", from_date="2026-08-15", to_date="2026-09-14")
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "AGOSTO - SEPTIEMBRE 2026")
        self.assertEqual(pdf["Periodo"], "Desde el 15/08/2026 hasta el 14/09/2026")

    def test_manual_invoice_without_period_uses_the_posting_month(self) -> None:
        """Una factura manual sin Desde/Hasta sigue con el mes de posting_date, como antes."""
        doc = _make_invoice(posting_date="2026-09-08")
        pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

        self.assertEqual(pdf["Nota"], "SEPTIEMBRE 2026")
        self.assertEqual(pdf["Periodo"], "Desde el 01/09/2026 hasta el 30/09/2026")

    def test_incomplete_or_inverted_period_falls_back_to_the_posting_month(self) -> None:
        for from_date, to_date in (("2026-08-01", None), (None, "2026-08-31"), ("2026-08-31", "2026-08-01")):
            with self.subTest(from_date=from_date, to_date=to_date):
                doc = _make_invoice(posting_date="2026-09-08", from_date=from_date, to_date=to_date)
                pdf = _extract_pdf_dict(_make_builder(doc)._build_info_adicional())

                self.assertEqual(pdf["Periodo"], "Desde el 01/09/2026 hasta el 30/09/2026")


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
