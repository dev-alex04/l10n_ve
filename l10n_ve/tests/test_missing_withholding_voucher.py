# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests para el aviso de "retención contabilizada sin su comprobante".

El indicador de la factura muestra un ⚠️ cuando hay una retención asentada y su número
de comprobante no está registrado. El formulario lo evalúa en vivo sobre la tabla de
impuestos; la vista de lista NO ve esa tabla, así que lee un campo que el servidor deja
calculado con esta misma función.

La heurística que usaba la lista antes fallaba de dos maneras, medidas sobre una copia
de producción (facturas de julio de 2026 en adelante, 392 con retención contabilizada):

    total_withholding != 0 && !nro_iva && !nro_islr

- ``total_withholding`` no se recalcula nunca en Sales Invoice: 66 facturas lo tenían
  en 0 teniendo la fila de retención, y el aviso no se encendía jamás.
- El ``&&`` exigía que faltaran los DOS números. 21 facturas a las que sólo les faltaba
  uno figuraban como completas.

Y no alcanza con cambiar el ``&&`` por un ``||``: 34 de esas 392 tienen un solo tipo de
retención (23 sólo ISLR, 11 sólo IVA), así que reclamarles el número del otro tipo sería
un aviso falso. Por eso la regla mira el ``charge_type``.

Suite unittest con dobles: la función sólo lee ``taxes`` y dos campos del documento.
"""

import unittest

from frappe import _dict

from l10n_ve.overrides.sales_invoice import missing_withholding_voucher


def _tax(charge_type: str, amount: float = 100.0) -> _dict:
    return _dict(charge_type=charge_type, tax_amount=amount)


def _invoice(taxes: list, nro_iva: str = "", nro_islr: str = "") -> _dict:
    doc = _dict(
        taxes=taxes,
        vat_withholding_voucher_number=nro_iva,
        islr_receipt_number=nro_islr,
    )
    # El código usa doc.get(campo); _dict ya lo soporta.
    return doc


class TestMissingWithholdingVoucher(unittest.TestCase):
    def test_no_withholding_never_warns(self):
        """Una factura sin retención no reclama ningún comprobante."""
        doc = _invoice([_tax("On Net Total"), _tax("Actual")])
        self.assertFalse(missing_withholding_voucher(doc))

    def test_vat_withholding_without_its_number_warns(self):
        doc = _invoice([_tax("VAT Withholding")])
        self.assertTrue(missing_withholding_voucher(doc))

    def test_islr_withholding_without_its_number_warns(self):
        doc = _invoice([_tax("ISLR")])
        self.assertTrue(missing_withholding_voucher(doc))

    def test_only_vat_does_not_ask_for_the_islr_number(self):
        """El caso que impide cambiar el && por un || a secas.

        11 facturas de la muestra tienen sólo retención de IVA. Reclamarles el número
        de ISLR sería un aviso falso.
        """
        doc = _invoice([_tax("VAT Withholding")], nro_iva="C-001")
        self.assertFalse(missing_withholding_voucher(doc))

    def test_only_islr_does_not_ask_for_the_vat_number(self):
        doc = _invoice([_tax("ISLR")], nro_islr="R-001")
        self.assertFalse(missing_withholding_voucher(doc))

    def test_both_withholdings_with_only_one_number_warns(self):
        """El bug que arregla este cambio: la lista las daba por completas.

        Reproducido en ACC-SINV-2026-13713 (PREPARADOS ALIMENTICIOS): retención de IVA
        y de ISLR, número de IVA cargado, número de ISLR vacío.
        """
        doc = _invoice([_tax("VAT Withholding"), _tax("ISLR")], nro_iva="C-001")
        self.assertTrue(missing_withholding_voucher(doc))

        doc = _invoice([_tax("VAT Withholding"), _tax("ISLR")], nro_islr="R-001")
        self.assertTrue(missing_withholding_voucher(doc))

    def test_both_withholdings_with_both_numbers_does_not_warn(self):
        doc = _invoice(
            [_tax("VAT Withholding"), _tax("ISLR")],
            nro_iva="C-001", nro_islr="R-001",
        )
        self.assertFalse(missing_withholding_voucher(doc))

    def test_a_zero_amount_row_is_not_a_withholding(self):
        """Una fila en cero no es una retención contabilizada."""
        doc = _invoice([_tax("VAT Withholding", 0)])
        self.assertFalse(missing_withholding_voucher(doc))

    def test_whitespace_is_not_a_voucher_number(self):
        """Un campo con espacios está vacío para lo que importa."""
        doc = _invoice([_tax("VAT Withholding")], nro_iva="   ")
        self.assertTrue(missing_withholding_voucher(doc))

    def test_an_invoice_without_taxes_does_not_break(self):
        self.assertFalse(missing_withholding_voucher(_invoice([])))
        self.assertFalse(missing_withholding_voucher(_dict(taxes=None)))
