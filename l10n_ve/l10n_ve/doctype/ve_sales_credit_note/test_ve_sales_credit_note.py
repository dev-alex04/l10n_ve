import unittest
from unittest.mock import patch, MagicMock

from l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note import (
    VESalesCreditNote,
)


class TestVESalesCreditNoteOutstanding(unittest.TestCase):
    """Tests unitarios para asegurar que el saldo pendiente en Notas de Crédito sea siempre cero."""

    def test_calculate_taxes_and_totals_forces_zero_outstanding(self):
        note = VESalesCreditNote.__new__(VESalesCreditNote)
        note.outstanding_amount = 15000.0
        note.taxes = []
        note.items = []
        note.company = "Test Co"
        note.customer = "Test Cust"

        with patch("l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.TaxesAndTotals"):
            with patch.object(VESalesCreditNote, "calculate_total_withholding"):
                note.calculate_taxes_and_totals()

        self.assertEqual(note.outstanding_amount, 0)

