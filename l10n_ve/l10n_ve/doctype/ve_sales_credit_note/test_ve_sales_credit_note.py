import unittest
from unittest.mock import patch

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

        with patch(
            "l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note.TaxesAndTotals"
        ), patch.object(VESalesCreditNote, "calculate_total_withholding"):
            note.calculate_taxes_and_totals()

        self.assertEqual(note.outstanding_amount, 0)



class TestDondeSeFijaElCero(unittest.TestCase):
    """Cuál de las asignaciones de `outstanding_amount = 0` es la que gobierna.

    El cambio original puso el cero en cuatro lugares. Estos tests muestran que sólo dos
    hacen falta, y por qué:

    - dentro de `validate`, DESPUÉS de `_run_super_validate_safely()`, porque el super
      recalcula los totales y pisa cualquier cero anterior;
    - dentro de `calculate_taxes_and_totals`, que es un camino propio: el cliente lo dispara
      al recalcular sin pasar por `validate`.

    Las otras dos --`before_insert` y el cero al principio de `validate`-- quedan pisadas por
    el super dentro del mismo guardado. Se quitaron; estos tests impiden que el
    comportamiento se pierda al quitarlas.
    """

    def _nota(self):
        nota = VESalesCreditNote.__new__(VESalesCreditNote)
        nota.outstanding_amount = 0.0
        nota.is_return = 0
        nota.update_outstanding_for_self = 1
        nota.set_posting_time = 0
        nota.taxes = []
        nota.items = []
        return nota

    def test_el_super_pisa_el_cero_y_por_eso_se_repone_despues(self):
        """Si el super deja un pendiente, `validate` tiene que volver a ponerlo en cero."""
        nota = self._nota()

        def _super_que_recalcula():
            nota.outstanding_amount = 115325.19   # lo que hoy tienen las 18 emitidas

        with patch.object(VESalesCreditNote, "_init_si_defaults"), \
                patch.object(VESalesCreditNote, "_inherit_branch_from_si"), \
                patch.object(VESalesCreditNote, "_enforce_positive_amounts"), \
                patch.object(VESalesCreditNote, "_validate_unique_note_per_invoice"), \
                patch.object(VESalesCreditNote, "_run_super_validate_safely",
                             side_effect=_super_que_recalcula), \
                patch.object(VESalesCreditNote, "_set_base_total_with_vat"), \
                patch("l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note"
                      ".validate_return_in_same_month"):
            nota.validate()

        self.assertEqual(nota.outstanding_amount, 0)

    def test_validate_deja_puestas_las_dos_banderas(self):
        """`is_return` y `update_outstanding_for_self` son lo que hace que ERPNext no cobre."""
        nota = self._nota()

        with patch.object(VESalesCreditNote, "_init_si_defaults"), \
                patch.object(VESalesCreditNote, "_inherit_branch_from_si"), \
                patch.object(VESalesCreditNote, "_enforce_positive_amounts"), \
                patch.object(VESalesCreditNote, "_validate_unique_note_per_invoice"), \
                patch.object(VESalesCreditNote, "_run_super_validate_safely"), \
                patch.object(VESalesCreditNote, "_set_base_total_with_vat"), \
                patch("l10n_ve.l10n_ve.doctype.ve_sales_credit_note.ve_sales_credit_note"
                      ".validate_return_in_same_month"):
            nota.validate()

        self.assertEqual(nota.is_return, 1)
        self.assertEqual(nota.update_outstanding_for_self, 0)
