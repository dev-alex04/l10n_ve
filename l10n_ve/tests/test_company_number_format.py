# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del formateo de números fiscales de la empresa (`Company.format_number`).

Contexto: en `domina.designet` no se podía emitir **ninguna** factura de venta. El
formato del número de control es `##-######` y `format_number` devolvía el patrón
crudo, `'##-######'`; después `_validate_bill_control` lo rechaza contra
`^[A-Za-z0-9\\-]+$` --el `#` no está-- y ese `frappe.throw` no lo silencia el
`raise_throw=False` con el que lo llama `set_control_number`. O sea: bloqueo duro
en el guardado, no un número feo.

La causa: `number_format.count('#')` cuenta los ocho `#` de `##-######` pero
`replace('#' * 8, ...)` busca ocho **consecutivos**, que ese patrón no tiene.

La forma esperada no es una interpretación: `HKA_CONTROL_RE` es `^\\d{2}-\\d{8}$` y
los números de control impresos en producción son `00-00220248`. Un solo número
repartido entre los grupos.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCompanyFormatNumber(FrappeTestCase):
    def formatear(self, number_format, number):
        """Llama al método real sin tocar la base: no lee ningún campo de `self`."""
        from l10n_ve.overrides.company import CustomCompany

        return CustomCompany.format_number(None, number_format, number)

    # --- el caso que bloqueaba la emisión -------------------------------------

    def test_grupos_separados_por_guion(self):
        """El caso de designet. Antes devolvía `'##-######'` tal cual."""
        self.assertEqual(self.formatear("##-######", 739), "00-000739")

    def test_reproduce_el_numero_de_control_impreso_en_produccion(self):
        """`00-00220248` es un número de control real, tomado de la base de producción.

        Es la prueba de que la lectura correcta es "un solo número repartido entre
        los grupos" y no "un número por grupo": con el formato de HKA
        (`^\\d{2}-\\d{8}$`) el correlativo 220248 tiene que dar exactamente eso.
        """
        self.assertEqual(self.formatear("##-########", 220248), "00-00220248")

    def test_el_patron_no_sobrevive_a_la_sustitucion(self):
        """Ningún `#` puede quedar en la salida: `_validate_bill_control` lo rechaza."""
        for patron in ("#####", "##-######", "##-########", "A#-##", "#-#-#"):
            with self.subTest(patron=patron):
                self.assertNotIn("#", self.formatear(patron, 7))

    # --- lo que ya funcionaba tiene que seguir igual ---------------------------

    def test_un_solo_grupo_no_cambia(self):
        """El camino que ya andaba: idéntico al del código viejo, dígito por dígito."""
        self.assertEqual(self.formatear("#####", 1), "00001")
        self.assertEqual(self.formatear("######", 739), "000739")

    def test_prefijo_literal_no_cambia(self):
        self.assertEqual(self.formatear("FAC-####", 1), "FAC-0001")

    def test_formato_sin_almohadillas(self):
        self.assertEqual(self.formatear("FAC-", 12), "FAC-12")

    def test_formato_vacio_o_nulo(self):
        self.assertEqual(self.formatear("", 12), "12")
        self.assertEqual(self.formatear(None, 12), "12")

    # --- bordes ---------------------------------------------------------------

    def test_el_numero_que_no_entra_crece_por_la_izquierda(self):
        """`zfill` nunca recortó, y recortar sería peor: cambiaría el número fiscal.

        El excedente se lo lleva el primer grupo para que el tramo de la derecha
        conserve el ancho que la imprenta espera.
        """
        self.assertEqual(self.formatear("###", 12345), "12345")
        self.assertEqual(self.formatear("##-######", 12345678901), "12345-678901")

    def test_el_cero_se_rellena(self):
        self.assertEqual(self.formatear("##-######", 0), "00-000000")

    def test_grupos_de_un_solo_caracter(self):
        """Tres grupos de uno: el número se reparte de izquierda a derecha."""
        self.assertEqual(self.formatear("#/#/#", 123), "1/2/3")

    def test_almohadillas_al_final_y_al_principio(self):
        self.assertEqual(self.formatear("##FAC##", 1234), "12FAC34")


class TestGetControlNumber(FrappeTestCase):
    """El formateo visto desde donde lo usa la factura.

    `format_number` a solas puede pasar y la emisión seguir rota: lo que
    `set_control_number` guarda viene de `get_control_number`, que le suma el
    correlativo y el default del campo vacío.
    """

    def test_el_numero_de_control_pasa_la_validacion_de_la_factura(self):
        from l10n_ve.overrides.company import CustomCompany

        empresa = frappe.new_doc("Company")
        empresa.sales_invoice_control_number_format = "##-######"
        empresa.sales_invoice_control_number_correlative = 739

        control = CustomCompany.get_control_number(empresa)

        self.assertEqual(control, "00-000739")
        # La misma expresión con la que `_validate_bill_control` decide si tira.
        self.assertRegex(control, r"^[A-Za-z0-9\-]+$")

    def test_el_default_del_campo_vacio_sigue_andando(self):
        from l10n_ve.overrides.company import CustomCompany

        empresa = frappe.new_doc("Company")
        empresa.sales_invoice_control_number_format = None
        empresa.sales_invoice_control_number_correlative = None

        self.assertEqual(CustomCompany.get_control_number(empresa), "00001")
