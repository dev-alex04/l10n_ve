# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del payload de retención de IVA: transporta, no recalcula.

El comprobante no hace aritmética propia salvo la suma de sus líneas. Recalcular el
retenido como IVA x % daba un céntimo de diferencia contra lo que la factura retuvo y
asentó --la factura acumula renglón por renglón y el payload multiplicaba una sola vez
sobre el IVA total-- en 59 de las 372 facturas de compra de 2026.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.digital_invoice.vat_withholding_payload_builder import (
    TFHKARetentionPayloadBuilder,
)

# Caso VNET del 16-sep-2026: el 75 % de este IVA cae justo en la mitad de un céntimo
# (1.383.676,785), así que recalcular y transportar dan valores distintos.
_IVA = 1844902.38
_RETENIDO_ASENTADO = 1383676.79
_RETENIDO_RECALCULADO = 1383676.78
_BRUTO = 13375542.28


def _item(**overrides) -> frappe._dict:
    item = frappe._dict({
        "purchase_invoice": "ACC-PINV-2026-00001",
        "bill_no": "12013",
        "bill_control": "00-05476240",
        "posting_date": "2026-09-08",
        "rate": 16.0,
        "withholding_rate": 75.0,
        "grand_total": _BRUTO,
        "total": _BRUTO - _IVA,
        "total_exempt": 0.0,
        "taxes_and_charges_added": _IVA,
        "tax_amount_vat": _RETENIDO_ASENTADO,
        "credit_note_no": None,
        "debit_note_no": None,
        "is_return": 0,
        "affected_invoice_number": None,
    })
    item.update(overrides)
    return item


def _builder(*items) -> TFHKARetentionPayloadBuilder:
    """Instancia sin pasar por __init__: estos métodos solo leen el documento."""
    builder = TFHKARetentionPayloadBuilder.__new__(TFHKARetentionPayloadBuilder)
    builder.company_currency = "BSD"
    builder.doc = frappe._dict({
        "name": "COMP-RET-IVA-2026-00001",
        TFHKARetentionPayloadBuilder.CHILD_TABLE_FIELD: list(items),
    })
    return builder


class TestVatPayloadSinRecalculo(FrappeTestCase):

    def test_el_retenido_es_el_que_retuvo_la_factura(self) -> None:
        detalle = _builder()._build_vat_detail_item(_item(), 1)

        self.assertEqual(detalle["Retenido"], f"{_RETENIDO_ASENTADO:.2f}")
        self.assertNotEqual(detalle["Retenido"], f"{_RETENIDO_RECALCULADO:.2f}")

    def test_el_monto_total_es_el_de_la_linea(self) -> None:
        detalle = _builder()._build_vat_detail_item(_item(), 1)

        self.assertEqual(detalle["MontoTotal"], f"{_BRUTO:.2f}")

    def test_el_total_retenido_es_la_suma_de_las_lineas(self) -> None:
        """La única cuenta que el comprobante sí hace: sumar sus propias líneas."""
        builder = _builder(_item(), _item(tax_amount_vat=1000.0))

        self.assertAlmostEqual(
            builder._calculate_total_retenido(), _RETENIDO_ASENTADO + 1000.0, places=2
        )

    def test_una_nota_de_credito_resta_en_el_total(self) -> None:
        builder = _builder(_item(), _item(tax_amount_vat=1000.0, credit_note_no="NC-1"))

        self.assertAlmostEqual(
            builder._calculate_total_retenido(), _RETENIDO_ASENTADO - 1000.0, places=2
        )
