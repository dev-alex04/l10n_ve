# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del total de la línea del comprobante de retención de IVA.

El total de la línea es el BRUTO de la factura (base + IVA). Se fija acá porque
derivarlo de `base_grand_total` --que en una factura de compra ya viene neto de
TODAS las retenciones-- dejaba el total corto exactamente en el ISLR, y el
comprobante impreso mostraba un detalle y un total que no cerraban entre sí.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.l10n_ve.doctype.vat_withholding_voucher.vat_withholding_voucher import (
    _build_invoice_row,
)

# Caso VNET del 16-sep-2026, el que reportó contabilidad.
_BASE = 11530639.90
_IVA = 1844902.38
_RETENCION_IVA = 1383676.78
_ISLR = 230612.80


def _invoice(**overrides) -> frappe._dict:
    inv = frappe._dict({
        "name": "ACC-PINV-2026-00001",
        "bill_no": "12013",
        "bill_control": "00-05476240",
        "bill_date": "2026-09-08",
        "posting_date": "2026-09-08",
        "currency": "VEF",
        "conversion_rate": 1,
        "base_total": _BASE,
        # El campo «Total Base + IVA (Bs)» del documento, que es el que la línea transporta.
        "base_total_with_vat": _BASE + _IVA,
        # Neto de las DOS retenciones, que es como lo guarda Purchase Invoice.
        "base_grand_total": _BASE + _IVA - _RETENCION_IVA - _ISLR,
        "total_exempt": 0.0,
        "affected_invoice_number": None,
        "is_return": 0,
        "branch": "HQ",
    })
    inv.update(overrides)
    return inv


def _maps(inv_name: str) -> tuple[dict, dict]:
    vat_map = {inv_name: {"rate": 16.0, "base_tax_amount": _IVA}}
    wh_map = {inv_name: {"withholding_rate": 75.0, "base_tax_amount": _RETENCION_IVA}}
    return vat_map, wh_map


class TestVatVoucherRowGrossTotal(FrappeTestCase):

    def test_total_de_la_linea_es_base_mas_iva(self) -> None:
        inv = _invoice()
        vat_map, wh_map = _maps(inv.name)

        row = _build_invoice_row(inv, vat_map, wh_map, "VEF")

        self.assertAlmostEqual(row["grand_total"], _BASE + _IVA, places=2)

    def test_el_islr_no_afecta_el_total_de_la_linea(self) -> None:
        """La misma factura con y sin ISLR da el mismo total de línea.

        Lo único que cambia entre las dos es `base_grand_total`, que el total ya no mira.
        """
        vat_map, wh_map = _maps("ACC-PINV-2026-00001")

        con_islr = _build_invoice_row(_invoice(), vat_map, wh_map, "VEF")
        sin_islr = _build_invoice_row(
            _invoice(base_grand_total=_BASE + _IVA - _RETENCION_IVA), vat_map, wh_map, "VEF"
        )

        self.assertAlmostEqual(con_islr["grand_total"], sin_islr["grand_total"], places=2)

    def test_la_linea_cierra_con_el_detalle_que_se_le_manda_a_hka(self) -> None:
        """El detalle del payload manda base + exento + IVA; el total debe ser esa misma cuenta.

        Con exento de por medio, que es donde se notaría si el total tomara solo la base gravada.
        """
        exento = 500000.0
        inv = _invoice(total_exempt=exento)
        vat_map, wh_map = _maps(inv.name)

        row = _build_invoice_row(inv, vat_map, wh_map, "VEF")
        detalle_hka = (
            abs(row["total"]) + abs(row["total_exempt"]) + abs(row["taxes_and_charges_added"])
        )

        self.assertAlmostEqual(row["grand_total"], detalle_hka, places=2)

    def test_factura_en_divisa_usa_los_montos_en_bolivares(self) -> None:
        """base_total y base_tax_amount ya vienen en Bs; solo el exento se convierte."""
        inv = _invoice(currency="USD", conversion_rate=800.0, total_exempt=10.0)
        vat_map, wh_map = _maps(inv.name)

        row = _build_invoice_row(inv, vat_map, wh_map, "VEF")

        self.assertAlmostEqual(row["total_exempt"], 8000.0, places=2)
        self.assertAlmostEqual(row["grand_total"], _BASE + _IVA, places=2)
        self.assertAlmostEqual(row["total"], _BASE - 8000.0, places=2)

    def test_el_total_se_transporta_del_documento_no_se_recalcula(self) -> None:
        """Si el documento dice otro monto, la línea lleva ESE, no una cuenta propia.

        Es la garantía de que el comprobante no tiene aritmética paralela: el único
        lugar donde se calculan impuestos es controllers/taxes_and_totals.py.
        """
        inv = _invoice(base_total_with_vat=999999.99)
        vat_map, wh_map = _maps(inv.name)

        row = _build_invoice_row(inv, vat_map, wh_map, "VEF")

        self.assertAlmostEqual(row["grand_total"], 999999.99, places=2)

    def test_documento_sin_total_base_mas_iva_no_arma_comprobante(self) -> None:
        """Falta el monto que va impreso: se corta, no se inventa."""
        inv = _invoice(base_total_with_vat=0)
        vat_map, wh_map = _maps(inv.name)

        with self.assertRaises(frappe.ValidationError):
            _build_invoice_row(inv, vat_map, wh_map, "VEF")
