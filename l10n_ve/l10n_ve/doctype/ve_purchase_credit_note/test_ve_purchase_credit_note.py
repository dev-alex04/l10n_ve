# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Tests unitarios de VE Purchase Credit Note (NC de compra).

Cubre la lógica propia del doctype con unittest + mocks (sin BD):
- set_taxes_and_charges: copia la tabla de impuestos descartando las retenciones
  de IVA y preservando las filas ISLR.
- _grand_total_includes_withholding: contrato (grand_total neto -> False).
- _enforce_positive_amounts: normaliza montos negativos y setea stock_qty.
- _validate_credit_note_number / _validate_unique_note_per_invoice: validaciones.
"""

import unittest
from unittest.mock import patch

import frappe

from l10n_ve.tests.helpers import make_mock_tax, MockDoc
from l10n_ve.l10n_ve.doctype.ve_purchase_credit_note.ve_purchase_credit_note import (
    VEPurchaseCreditNote,
)

_PCN = "l10n_ve.l10n_ve.doctype.ve_purchase_credit_note.ve_purchase_credit_note"


class _Thrown(Exception):
    """Sustituto de frappe.throw para poder hacer assertRaises."""


class _FakeNote:
    """Doc mínimo para ejercitar set_taxes_and_charges sin BD."""

    def __init__(self, taxes, taxes_and_charges=None):
        self.taxes = list(taxes)
        self.taxes_and_charges = taxes_and_charges
        self.calls = []

    def get(self, key, default=None):
        return getattr(self, key, default)

    def set(self, key, value):
        setattr(self, key, value)

    def append(self, key, value):
        getattr(self, key).append(value)
        return value

    # Métodos colaboradores: en producción agregan filas de retención; aquí no-op.
    def append_taxes_from_master(self, template):
        self.calls.append(("append_taxes_from_master", template))

    def set_tax_withholding_ve(self):
        self.calls.append("set_tax_withholding_ve")

    def set_islr_withholding_ve(self):
        self.calls.append("set_islr_withholding_ve")


class TestSetTaxesAndCharges(unittest.TestCase):
    """set_taxes_and_charges: descarta retención de IVA, preserva ISLR."""

    def test_drops_vat_withholding_keeps_islr_and_vat(self):
        taxes = [
            make_mock_tax(charge_type="VAT", is_tax_withholding_account=False),
            make_mock_tax(charge_type="VAT Withholding", is_tax_withholding_account=True),
            make_mock_tax(charge_type="ISLR", is_tax_withholding_account=True),
        ]
        note = _FakeNote(taxes)
        VEPurchaseCreditNote.set_taxes_and_charges(note)

        charge_types = [t.charge_type for t in note.taxes]
        self.assertIn("VAT", charge_types)
        self.assertIn("ISLR", charge_types)       # ISLR se preserva y re-agrega
        self.assertNotIn("VAT Withholding", charge_types)  # retención de IVA descartada
        # colaboradores invocados
        self.assertIn("set_tax_withholding_ve", note.calls)
        self.assertIn("set_islr_withholding_ve", note.calls)
        # idx reindexado 1..n
        self.assertEqual([t.idx for t in note.taxes], list(range(1, len(note.taxes) + 1)))

    def test_no_base_tax_loads_from_template(self):
        # Solo retención de IVA (sin base) + plantilla configurada
        taxes = [make_mock_tax(charge_type="VAT Withholding", is_tax_withholding_account=True)]
        note = _FakeNote(taxes, taxes_and_charges="Mi Plantilla")
        VEPurchaseCreditNote.set_taxes_and_charges(note)

        self.assertIn(
            ("append_taxes_from_master", "Purchase Taxes and Charges Template"),
            note.calls,
        )


class TestGrandTotalIncludesWithholding(unittest.TestCase):
    def test_returns_false(self):
        """Regresión de contrato: el grand_total de la NC ya es neto de retenciones."""
        self.assertFalse(VEPurchaseCreditNote._grand_total_includes_withholding(object()))


class TestEnforcePositiveAmounts(unittest.TestCase):
    """_enforce_positive_amounts: normaliza qty/rate y calcula stock_qty."""

    def test_normalizes_negative_qty_and_rate(self):
        items = [frappe._dict(qty=-2, rate=-100.0, conversion_factor=0)]
        doc = MockDoc(items=items)
        VEPurchaseCreditNote._enforce_positive_amounts(doc)
        item = doc.items[0]
        self.assertEqual(item.qty, 2)
        self.assertEqual(item.rate, 100.0)
        self.assertEqual(item.conversion_factor, 1.0)   # fallback cuando es falsy
        self.assertEqual(item.stock_qty, 2.0)           # qty * conversion_factor

    def test_positive_values_and_conversion_factor_preserved(self):
        items = [frappe._dict(qty=3, rate=50.0, conversion_factor=2)]
        doc = MockDoc(items=items)
        VEPurchaseCreditNote._enforce_positive_amounts(doc)
        item = doc.items[0]
        self.assertEqual(item.qty, 3)
        self.assertEqual(item.rate, 50.0)
        self.assertEqual(item.stock_qty, 6.0)           # 3 * 2


class TestValidateCreditNoteNumber(unittest.TestCase):
    """_validate_credit_note_number: obligatorio + unicidad por proveedor."""

    def _run(self, bill_no, existing=None, supplier="PROV-1"):
        doc = MockDoc(bill_no=bill_no, supplier=supplier, name="NCC-1")
        with patch(f"{_PCN}.frappe") as mf, \
             patch(f"{_PCN}._", side_effect=lambda s: s):
            mf.throw.side_effect = _Thrown
            mf.db.get_value.return_value = existing
            VEPurchaseCreditNote._validate_credit_note_number(doc)

    def test_missing_bill_no_raises(self):
        with self.assertRaises(_Thrown):
            self._run(bill_no="")

    def test_duplicate_for_supplier_raises(self):
        with self.assertRaises(_Thrown):
            self._run(bill_no="NC-001", existing="NCC-OTHER")

    def test_unique_bill_no_ok(self):
        # No debe lanzar
        self._run(bill_no="NC-001", existing=None)


class TestValidateUniqueNotePerInvoice(unittest.TestCase):
    def test_no_return_against_skips(self):
        doc = MockDoc(return_against=None, name="NCC-1")
        with patch(f"{_PCN}.frappe") as mf, \
             patch(f"{_PCN}._", side_effect=lambda s: s):
            mf.throw.side_effect = _Thrown
            VEPurchaseCreditNote._validate_unique_note_per_invoice(doc)
            mf.db.get_value.assert_not_called()

    def test_existing_active_note_raises(self):
        doc = MockDoc(return_against="PI-1", name="NCC-1")
        with patch(f"{_PCN}.frappe") as mf, \
             patch(f"{_PCN}._", side_effect=lambda s: s):
            mf.throw.side_effect = _Thrown
            mf.db.get_value.return_value = "NCC-OTHER"
            with self.assertRaises(_Thrown):
                VEPurchaseCreditNote._validate_unique_note_per_invoice(doc)


if __name__ == "__main__":
    unittest.main()


class TestSaldoPendienteSiempreCero(unittest.TestCase):
    """Una nota de crédito no debe quedar con saldo por cobrar: es un crédito, no una deuda.

    El cero lo pone ERPNext solo --`calculate_outstanding_amount` corta en seco cuando el
    documento es devolución, tiene factura de origen y `update_outstanding_for_self` está
    apagado--, pero la NC reemplaza `calculate_taxes_and_totals` por el calculador venezolano
    y en ese camino esa rama no corre. De ahí que el cero haya que ponerlo acá.

    La NC de venta ya tenía este test; la de compra no, y lleva el mismo cambio.
    """

    def _nota(self, pendiente: float = 15000.0) -> VEPurchaseCreditNote:
        nota = VEPurchaseCreditNote.__new__(VEPurchaseCreditNote)
        nota.outstanding_amount = pendiente
        nota.taxes = []
        nota.items = []
        nota.company = "Test Co"
        nota.supplier = "Test Prov"
        return nota

    def _calcular(self, nota) -> None:
        with patch(f"{_PCN}.TaxesAndTotals"), \
                patch.object(VEPurchaseCreditNote, "calculate_total_withholding"):
            nota.calculate_taxes_and_totals()

    def test_el_calculo_deja_el_pendiente_en_cero(self) -> None:
        nota = self._nota(15000.0)

        self._calcular(nota)

        self.assertEqual(nota.outstanding_amount, 0)

    def test_tambien_cuando_ya_venia_en_cero(self) -> None:
        """Idempotente: recalcular no lo mueve."""
        nota = self._nota(0.0)

        self._calcular(nota)

        self.assertEqual(nota.outstanding_amount, 0)

    def test_tambien_con_un_pendiente_negativo(self) -> None:
        """Un negativo es tan incorrecto como un positivo: la NC no tiene saldo propio."""
        nota = self._nota(-8420.55)

        self._calcular(nota)

        self.assertEqual(nota.outstanding_amount, 0)
