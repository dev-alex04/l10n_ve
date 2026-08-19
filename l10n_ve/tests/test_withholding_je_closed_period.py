# Copyright (c) 2026, Grupo Altia and Contributors
# See license.txt

"""
Test del manejo de período contable cerrado al contabilizar una retención.

Regresión de "name 'ClosedAccountingPeriod' is not defined" (9 entradas entre
el 31 de julio y el 12 de agosto de 2026, vía `fix_missing_withholding`):
`create_withholding_journal_entry` capturaba `ClosedAccountingPeriod` sin
haberla importado. El `except` fallaba AL EVALUARSE, así que:

  - el `except Exception` de abajo NO lo atrapaba (un NameError levantado
    mientras se resuelve una cláusula except se propaga), y
  - el usuario recibía un NameError crudo en vez del mensaje que explica que
    debe hablar con contabilidad.

O sea: el mensaje amable existía desde siempre y nunca se llegó a mostrar.
"""

import unittest

from erpnext.accounts.doctype.accounting_period.accounting_period import (
    ClosedAccountingPeriod,
)

import l10n_ve.overrides.sales_invoice as sales_invoice


class TestWithholdingJEClosedPeriod(unittest.TestCase):
    def test_la_excepcion_esta_importada_en_el_modulo(self):
        """El nombre que usa el `except` tiene que existir en el módulo."""
        self.assertTrue(hasattr(sales_invoice, "ClosedAccountingPeriod"))

    def test_es_la_clase_de_erpnext_no_un_homonimo(self):
        """Debe ser la misma clase que levanta el mayor, o el except no engancha."""
        self.assertIs(sales_invoice.ClosedAccountingPeriod, ClosedAccountingPeriod)

    def test_capturar_la_de_erpnext_engancha_de_verdad(self):
        """Contrato del `except`: la excepción real cae en esa rama."""
        try:
            raise ClosedAccountingPeriod("período cerrado")
        except sales_invoice.ClosedAccountingPeriod:
            enganchó = True
        except Exception:
            enganchó = False

        self.assertTrue(enganchó)

    def test_es_una_validationerror(self):
        """Va antes que `except Exception`, y por herencia también lo atraparía:
        el orden de las cláusulas es lo que la mantiene distinguible."""
        import frappe

        self.assertTrue(issubclass(ClosedAccountingPeriod, frappe.ValidationError))


if __name__ == "__main__":
    unittest.main()
