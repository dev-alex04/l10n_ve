# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

import unittest
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe.tests.utils import FrappeTestCase

from l10n_ve.controllers.taxes_and_totals import TAX_FROM_TOTAL
from l10n_ve.l10n_ve.doctype.ve_sales_debit_note.ve_sales_debit_note import VESalesDebitNote

_ND = "l10n_ve.l10n_ve.doctype.ve_sales_debit_note.ve_sales_debit_note"


def _note(currency: str) -> VESalesDebitNote:
    note = VESalesDebitNote.__new__(VESalesDebitNote)
    note.company = "Empresa"
    note.currency = currency
    return note


class TestVESalesDebitNote(FrappeTestCase):
    pass


class TestPrecisionLossGlEntry(unittest.TestCase):
    """Una ND en divisa con «Desde el total de la factura» no lleva el asiento de pérdida
    de precisión: el ancla ya separa base_net_total de net_total × tasa, y ese asiento la
    dejaba descuadrada (ND de 1,75 USD con Bs 1,07 de diferencia)."""

    def _run(self, currency: str, method: str) -> bool:
        values = {"default_currency": "VEF", "tax_calculation_method": method}

        def cached_value(_doctype, _name, field, *args, **kwargs):
            return values.get(field)

        with patch(f"{_ND}.frappe.get_cached_value", side_effect=cached_value), \
             patch.object(SalesInvoice, "make_precision_loss_gl_entry") as erpnext_entry:
            _note(currency).make_precision_loss_gl_entry([])
        return erpnext_entry.called

    def test_foreign_currency_from_total_skips_the_entry(self):
        self.assertFalse(self._run("USD", TAX_FROM_TOTAL))

    def test_company_currency_keeps_erpnext_entry(self):
        self.assertTrue(self._run("VEF", TAX_FROM_TOTAL))

    def test_other_method_keeps_erpnext_entry(self):
        self.assertTrue(self._run("USD", "Desde la base imponible"))
