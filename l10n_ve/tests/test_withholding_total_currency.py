# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""«Total Retenido» tiene que decir de qué moneda habla.

El campo guarda el monto en la moneda del DOCUMENTO --así lo calcula
`TaxesMixin.calculate_total_withholding`, sumando `tax_amount`-- pero su Custom Field se
declaró sin `options`, y un campo Currency sin `options` lo muestra Frappe con la moneda de la
empresa. Resultado: una factura en divisa decía «Bs. 6,21» cuando en bolívares eran 5.137,68.

Lo levantó administración el 17-sep-2026 revisando GRUPO DROSS. No es un caso raro: ese día,
de las facturas de venta con retención, **las 1.653 estaban en divisa**, o sea que el símbolo
estaba mal en todas. En compras el mismo campo tiene el mismo defecto pero sólo una factura de
418 está en divisa, y por eso nadie lo había visto.

La convención ya existía en la propia app: los doctypes VE Sales Credit Note y VE Sales Debit
Note declaran ese campo con `options = "currency"`. Los Custom Field de Factura de Venta y de
Compra se quedaron sin ella.
"""

import unittest

import frappe


class TestWithholdingTotalCurrency(unittest.TestCase):
    def test_the_field_declares_the_document_currency(self) -> None:
        """Sin esto, Frappe lo pinta con la moneda de la empresa sobre un monto que no lo es."""
        for doctype in ("Sales Invoice", "Purchase Invoice"):
            with self.subTest(doctype=doctype):
                field = frappe.get_meta(doctype).get_field("total_withholding")
                self.assertIsNotNone(field, f"{doctype} no tiene el campo total_withholding")
                self.assertEqual(field.options, "currency")

    def test_it_matches_what_the_notes_already_declared(self) -> None:
        """La misma moneda que sus hermanas, que sí lo tenían bien desde el principio."""
        for doctype in ("VE Sales Credit Note", "VE Sales Debit Note"):
            with self.subTest(doctype=doctype):
                field = frappe.get_meta(doctype).get_field("total_withholding")
                self.assertEqual(field.options, "currency")

    def test_the_base_twin_keeps_the_company_currency(self) -> None:
        """El contraste: el campo que SÍ guarda bolívares declara la moneda de la empresa."""
        field = frappe.get_meta("Sales Invoice").get_field("base_total_exempt")
        self.assertEqual(field.options, "Company:company:default_currency")
