# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Resolución de la alícuota al retener sobre una factura de compra ya aprobada.

Lo que se protege: que la alícuota salga del tabulador **para el tipo de persona del
proveedor** siempre que ese tipo esté en el concepto, y que cuando no está NO se tome
"la primera con alícuota > 0" si el concepto ofrece varias. Esa "primera" sería la fila
de otro tipo de persona sobre un monto que se declara ante el SENIAT.

Lo que sí se permite, desde 16-sep-2026: si el concepto ofrece **una sola** alícuota, se
aplica aunque no sea la del tipo del proveedor. Es el caso de las sociedades de personas
--firmas civiles de abogados o contadores, con RIF jurídico, que por el Decreto 1808
(artículo 9, parágrafo cuarto) se retienen con las tasas de las naturales--, acordado con
el equipo contable el 31-jul-2026. Ahí no hay nada que adivinar: el concepto ofrece una
tarifa y es la que el contador eligió.

Medido en el sitio el 16-sep-2026: 66 conceptos con alícuota > 0, de los cuales 65 tienen
exactamente una fila. El único con dos tipos es el `077`, que va de 1 % con sustraendo
Bs 35,83 (natural domiciliado) a 5 % sin sustraendo (jurídico), y ninguna línea viva lo usa.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from l10n_ve.overrides.purchase_invoice import _calculate_purchase_withholding_base_amount

MOD = "l10n_ve.overrides.purchase_invoice"


def _factura(base_bs=1000.0):
    return frappe._dict(
        name="ACC-PINV-2026-00001",
        supplier="PROVEEDOR X",
        company="Galanet Solution C.A.",
        base_net_total=base_bs,
        taxes=[],
    )


def _tabulador(filas):
    doc = MagicMock()
    doc.aliquot = [frappe._dict(f) for f in filas]
    return doc


class TestISLRRateResolution(unittest.TestCase):
    def _base(self, filas, tipo_persona):
        with patch(f"{MOD}.frappe.db.get_value", return_value=tipo_persona), patch(
            f"{MOD}.frappe.get_doc", return_value=_tabulador(filas)
        ):
            return _calculate_purchase_withholding_base_amount(
                _factura(), "ISLR", "TAB-9"
            )

    def test_uses_the_row_of_the_supplier_person_type(self):
        filas = [
            {"types_of_person": "Natural person domiciled", "aliquot": 1.0,
             "subtracting": 35.83, "percentage_base": 100.0},
            {"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
             "subtracting": 0.0, "percentage_base": 100.0},
        ]
        # 1000 × 5 % − 0 = 50
        self.assertEqual(self._base(filas, "Domiciled legal entity"), 50.0)

        # Con la fila del natural el resultado es otro: 1000 × 1 % − 35,83 queda en
        # negativo, se acota en 0 y la función corta --no se retiene 0--. Que las dos
        # filas den resultados distintos es justamente el punto: tomar "la primera"
        # cambiaba el monto declarado.
        with self.assertRaises(frappe.ValidationError):
            self._base(filas, "Natural person domiciled")

    def test_a_single_rate_concept_applies_to_any_person_type(self):
        """Concepto de una sola alícuota: se aplica aunque sea de otro tipo.

        Sociedades de personas. El concepto ofrece una tarifa, el contador la
        eligió, y no hay ninguna otra fila entre la cual equivocarse.
        1000 × 5 % − 0 = 50.
        """
        filas = [{"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
                  "subtracting": 0.0, "percentage_base": 100.0}]
        self.assertEqual(self._base(filas, "Natural person domiciled"), 50.0)

    def test_with_several_rates_and_none_of_that_type_it_blocks(self):
        """Varias alícuotas y ninguna del proveedor: falla, no elige por orden."""
        filas = [
            {"types_of_person": "Natural person domiciled", "aliquot": 1.0,
             "subtracting": 35.83, "percentage_base": 100.0},
            {"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
             "subtracting": 0.0, "percentage_base": 100.0},
        ]
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._base(filas, "Non-domiciled natural person")
        self.assertIn("ofrece más de una", str(ctx.exception))

    def test_a_supplier_without_person_type_also_blocks(self):
        """Sin tipo de persona no se retiene, igual que en borrador.

        Es configuración faltante del proveedor, no una alícuota que se pueda
        resolver, así que se corta antes de mirar el concepto.
        """
        filas = [{"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
                  "subtracting": 0.0, "percentage_base": 100.0}]
        with self.assertRaises(frappe.ValidationError):
            self._base(filas, "")

    def test_a_zero_percentage_base_blocks(self):
        """Antes un 0 pasaba a 100 %, que son 100x de diferencia en la base."""
        filas = [{"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
                  "subtracting": 0.0, "percentage_base": 0.0}]
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._base(filas, "Domiciled legal entity")
        self.assertIn("porcentaje de base", str(ctx.exception))

    def test_the_percentage_base_is_applied(self):
        """Base al 50 %: 1000 × 50 % × 5 % = 25."""
        filas = [{"types_of_person": "Domiciled legal entity", "aliquot": 5.0,
                  "subtracting": 0.0, "percentage_base": 50.0}]
        self.assertEqual(self._base(filas, "Domiciled legal entity"), 25.0)

    def test_an_empty_tabulator_blocks(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            self._base([], "Domiciled legal entity")
        self.assertIn("no tiene alícuotas", str(ctx.exception))


class TestNoArbitraryDefaults(unittest.TestCase):
    """Los defaults que se quitaron no deben volver: cada uno cambia un monto fiscal."""

    def test_the_source_has_no_arbitrary_fallbacks(self):
        import inspect

        from l10n_ve.overrides import purchase_invoice

        src = inspect.getsource(purchase_invoice.apply_retroactive_purchase_withholding)
        src += inspect.getsource(purchase_invoice._calculate_purchase_withholding_base_amount)

        self.assertNotIn("if flt(r.aliquot) > 0), None)\n        if not target_row", src)
        self.assertNotIn('flt(invoice.conversion_rate) or 1.0', src)
        self.assertNotIn('or "VEF"', src)


if __name__ == "__main__":
    unittest.main()
