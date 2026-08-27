"""Pago directo de la Nota de Débito de compra.

La ND de compra lleva outstanding propio --el hook de GL Entry se lo recalcula como
AP (credit - debit)-- asi que se paga contra si misma y no a traves de la factura
afectada. Antes de esto solo estaba cableada la ND de VENTAS: faltaban la lista
blanca del servidor, el manejo en `get_payment_entry` y el boton del formulario.

ALCANCE: aca van las piezas aisladas. El pago DE VERDAD --emitir el Payment Entry y
ver moverse el outstanding-- vive en `test_purchase_debit_note_payment_e2e`, y esa
separacion importa: el bug que motivo la feature solo aparece emitiendo, y un test
con `PurchaseInvoice.set_status` mockeado como los de aca no lo atrapa.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.overrides import payment_entry as pe_mod


class TestValidReferenceDoctypes(unittest.TestCase):
    """`get_valid_reference_doctypes` habilita la ND que corresponde a cada parte."""

    def _pe(self, party_type):
        obj = pe_mod.CustomPaymentEntry.__new__(pe_mod.CustomPaymentEntry)
        obj.party_type = party_type
        return obj

    def test_proveedor_habilita_la_nd_de_compra(self):
        with patch.object(
            pe_mod.PaymentEntry, "get_valid_reference_doctypes",
            return_value=("Purchase Order", "Purchase Invoice", "Journal Entry"),
        ):
            valid = self._pe("Supplier").get_valid_reference_doctypes()
        self.assertIn("VE Purchase Debit Note", valid)
        self.assertIn("Purchase Invoice", valid)

    def test_cliente_habilita_la_nd_de_ventas(self):
        with patch.object(
            pe_mod.PaymentEntry, "get_valid_reference_doctypes",
            return_value=("Sales Order", "Sales Invoice", "Journal Entry"),
        ):
            valid = self._pe("Customer").get_valid_reference_doctypes()
        self.assertIn("VE Sales Debit Note", valid)

    def test_no_se_cruzan_las_notas_entre_partes(self):
        """Una ND de compra no debe poder referenciarse desde un cobro a cliente."""
        with patch.object(
            pe_mod.PaymentEntry, "get_valid_reference_doctypes",
            return_value=("Sales Invoice",),
        ):
            valid = self._pe("Customer").get_valid_reference_doctypes()
        self.assertNotIn("VE Purchase Debit Note", valid)

    def test_las_notas_de_credito_nunca_entran(self):
        """Las NC no tienen outstanding propio: reducen el de la factura original."""
        for parte, base in (("Supplier", ("Purchase Invoice",)), ("Customer", ("Sales Invoice",))):
            with patch.object(
                pe_mod.PaymentEntry, "get_valid_reference_doctypes", return_value=base
            ):
                valid = self._pe(parte).get_valid_reference_doctypes()
            self.assertNotIn("VE Purchase Credit Note", valid)
            self.assertNotIn("VE Sales Credit Note", valid)


class TestPurchaseDebitNoteSetStatus(unittest.TestCase):
    """set_status rellena los campos de Purchase Invoice que la ND no tiene.

    El camino donde esto explotaba no era el obvio: se llega desde el hook de GL
    Entry al aprobar el Payment Entry, o sea al PAGAR la nota, no al emitirla.
    """

    def _nota(self):
        from l10n_ve.l10n_ve.doctype.ve_purchase_debit_note.ve_purchase_debit_note import (
            VEPurchaseDebitNote,
        )
        nd = VEPurchaseDebitNote.__new__(VEPurchaseDebitNote)
        nd.posting_date = "2026-08-27"
        return nd

    def test_rellena_is_return_en_cero(self):
        nd = self._nota()
        nd.due_date = "2026-08-27"
        capturado = {}
        with patch("erpnext.accounts.doctype.purchase_invoice.purchase_invoice."
                   "PurchaseInvoice.set_status",
                   side_effect=lambda **kw: capturado.update(kw)):
            nd.set_status(update=True)
        # una ND AUMENTA la deuda: con is_return=1 ERPNext invierte el signo del estado
        self.assertEqual(nd.is_return, 0)

    def test_rellena_due_date_si_falta(self):
        nd = self._nota()
        with patch("erpnext.accounts.doctype.purchase_invoice.purchase_invoice."
                   "PurchaseInvoice.set_status"):
            nd.set_status(update=True)
        self.assertEqual(nd.due_date, "2026-08-27")

    def test_no_pisa_un_is_return_ya_puesto(self):
        nd = self._nota()
        nd.due_date = "2026-08-27"
        nd.is_return = 1
        with patch("erpnext.accounts.doctype.purchase_invoice.purchase_invoice."
                   "PurchaseInvoice.set_status"):
            nd.set_status(update=True)
        self.assertEqual(nd.is_return, 1)
