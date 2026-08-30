# Copyright (c) 2026, Domina Software and Contributors
# For license information, please see license.txt

"""Clasificar una parte por su documento, para que no la clasifique el silencio.

`type_of_document`, `nature_of_the_taxpayer` y `type_of_person` son Select obligatorios, y
**Frappe rellena un Select obligatorio vacío con su primera opción**. Omitirlos no deja la
parte sin clasificar: la deja como `RIF` + `Juridical`, o sea persona jurídica, sin un
solo error en pantalla.

Se vio en producción del ensayo por los dos lados. En la contratista, un cliente con
cédula quedaba registrado como empresa. En el ISP, la conversión del prospecto reventaba
con «Para el tipo de documento 'RIF', el ID de Impuesto 'V23623826' debe tener 9 dígitos»
--un mensaje sobre un tipo de documento que nadie eligió--.

La regla vive al lado de `validate_taxpayer_and_person_type_consistency` a propósito: es
la que tiene que satisfacer, y el último test de acá lo comprueba contra ella misma en
vez de contra una copia.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.utils.utils import (
    IDENTITY_BY_LETTER,
    get_tax_id_config,
    classify_party_by_document,
    split_document_number,
    validate_taxpayer_and_person_type_consistency,
)


class TestSplitDocumentNumber(FrappeTestCase):
    def test_tolera_lo_que_la_gente_escribe(self):
        for crudo in ("V-23.623.826", "v23623826", " V 23623826 ", "V23623826"):
            self.assertEqual(split_document_number(crudo), ("V", "23623826"), crudo)

    def test_sin_letra_no_adivina(self):
        """El caso real: el ISP mandó «23623826» pelado. De la letra dependen la retención
        de ISLR y el documento fiscal, así que suponer «V» por ser lo común es inventar."""
        self.assertEqual(split_document_number("23623826"), ("", "23623826"))

    def test_una_letra_que_no_es_de_documento(self):
        self.assertEqual(split_document_number("X23623826"), ("", "X23623826"))

    def test_vacio(self):
        self.assertEqual(split_document_number(None), ("", ""))
        self.assertEqual(split_document_number("---"), ("", ""))


class TestClassifyPartyByDocument(FrappeTestCase):
    def test_cedula_es_persona_natural(self):
        self.assertEqual(
            classify_party_by_document("V23623826"),
            {
                "type_of_document": "Cedula",
                "nature_of_the_taxpayer": "Venezuelan",
                "type_of_person": "Natural person domiciled",
                "customer_type": "Individual",
            },
        )

    def test_la_longitud_distingue_cedula_de_rif(self):
        """Un dígito más y ya es RIF. Es lo único que los separa, y es lo que hacía
        rebotar la conversión: 8 dígitos validados como RIF."""
        self.assertEqual(classify_party_by_document("V23623826")["type_of_document"], "Cedula")
        self.assertEqual(classify_party_by_document("V236238267")["type_of_document"], "RIF")

    def test_empresa(self):
        clasificacion = classify_party_by_document("J310123456")

        self.assertEqual(clasificacion["nature_of_the_taxpayer"], "Juridical")
        self.assertEqual(clasificacion["customer_type"], "Company")

    def test_pasaporte_es_no_domiciliado(self):
        self.assertEqual(
            classify_party_by_document("P12345")["type_of_person"],
            "Non-domiciled natural person",
        )

    def test_sin_letra_no_clasifica(self):
        """Y por eso quien llama debe detenerse, no rellenar con lo que sea."""
        self.assertEqual(classify_party_by_document("23623826"), {})
        self.assertEqual(classify_party_by_document(None), {})

    def test_lo_elegido_manda_sobre_lo_deducido(self):
        """Quien carga el dato tiene el documento en la mano; la longitud sólo deduce."""
        self.assertEqual(classify_party_by_document("V23623826", "RIF")["type_of_document"], "RIF")

    def test_un_tipo_imposible_para_esa_letra_se_ignora(self):
        """Llega de un formulario: una empresa con cédula no puede colarse por ahí."""
        self.assertEqual(
            classify_party_by_document("J310123456", "Cedula")["type_of_document"], "RIF"
        )

    def test_cada_letra_tiene_rango_de_longitud_configurado(self):
        """`get_tax_id_config` tiene que saber cuántos dígitos admite cada combinación.

        Con `None` no hay con qué comparar y `validate_tax_id_format` rechaza cualquier
        longitud. Pasó con la "P": estaba mapeada a la naturaleza `Passport`, y el único
        par configurado es (Passport, Extranjero) --que además es el que usan los
        clientes con pasaporte reales--.
        """
        for letra, entrada in IDENTITY_BY_LETTER.items():
            nature = entrada["nature_of_the_taxpayer"]

            for documento in (entrada["short_document"], entrada["long_document"]):
                self.assertIsNotNone(
                    get_tax_id_config(documento, nature),
                    f"'{letra}' produce ({documento}, {nature}) y eso no tiene rango",
                )

    def test_la_longitud_la_decide_get_tax_id_config_y_no_una_copia(self):
        """El rango de la cédula --[6, 8]-- vive en `get_tax_id_config`. Tenerlo también
        acá era copiar el techo sin el piso."""
        cedula = get_tax_id_config("Cedula", "Venezuelan")
        rif = get_tax_id_config("RIF", "Venezuelan")

        # Lo que entra en el rango de la cédula sale cédula; lo que entra en el del RIF,
        # RIF. Sin números escritos a mano en el test tampoco.
        for largo in range(cedula[0], cedula[1] + 1):
            self.assertEqual(
                classify_party_by_document("V" + "1" * largo)["type_of_document"], "Cedula", largo
            )

        self.assertEqual(
            classify_party_by_document("V" + "1" * rif)["type_of_document"], "RIF"
        )

    def test_un_numero_que_no_entra_en_ninguno_elige_el_mas_cercano(self):
        """No es adivinar la clasificación --la da la letra-- sino de qué rango va a
        hablar el mensaje de error que sigue: demasiado corto es un intento de cédula."""
        self.assertEqual(classify_party_by_document("V1")["type_of_document"], "Cedula")
        self.assertEqual(
            classify_party_by_document("V" + "1" * 20)["type_of_document"], "RIF"
        )

    def test_todas_las_letras_pasan_su_propia_validacion(self):
        """Contra la regla real, no contra una copia.

        Si mañana mueven `Communal` al grupo de naturalezas naturales, esto falla acá y no
        en la conversión de un prospecto.
        """
        for letra in IDENTITY_BY_LETTER:
            clasificacion = classify_party_by_document(f"{letra}12345678")

            validate_taxpayer_and_person_type_consistency(frappe._dict(clasificacion))

    def test_la_tabla_cubre_las_letras_que_acepta_el_validador(self):
        """`validate_tax_id_format` exige que la letra esté en «VEJGPC»."""
        self.assertEqual(set(IDENTITY_BY_LETTER), set("VEJGPC"))
