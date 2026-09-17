# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests de la resolución de alícuota de ISLR en facturas de compra.

Contexto: las sociedades de personas —firmas civiles de abogados o contadores—
tienen RIF jurídico, pero por el Decreto 1808 (artículo 9, parágrafo cuarto) se
retienen con las tasas de las personas naturales. Se acordó con el equipo
contable el 31-jul-2026 y es la razón de que el buscador de conceptos no filtre
por tipo de persona.

El sistema quedó a medias: el camino de borrador aceptaba el concepto cruzado y
el camino retroactivo —factura ya aprobada— lo rechazaba, así que contabilidad
terminaba duplicando el documento para esquivar el bloqueo.

Lo que estos tests fijan:
- que un concepto con una sola alícuota se aplique aunque no sea la del tipo de
  persona del proveedor, en LOS DOS caminos;
- que un concepto con varias alícuotas y ninguna del proveedor NO elija por
  orden de fila: esa cifra se declara ante el SENIAT;
- que la fila deje constancia cuando la alícuota aplicada es de otro tipo.
"""

from unittest.mock import patch

import frappe
from frappe import _dict
from frappe.tests.utils import FrappeTestCase

from l10n_ve.utils.islr import (
    describe_purchase_islr_row,
    resolve_purchase_islr_aliquot,
)

JURIDICA = "Domiciled legal entity"
NATURAL = "Natural person domiciled"
NO_DOMICILIADA = "Non-domiciled natural person"


def _aliquot(types_of_person: str, aliquot: float, subtracting: float = 0.0) -> _dict:
    return _dict({
        "types_of_person": types_of_person,
        "aliquot": aliquot,
        "percentage_base": 100.0,
        "subtracting": subtracting,
    })


def _tabulator(codigo: str, rows: list, name: str = None) -> _dict:
    return _dict({
        "name": name or codigo,
        "codigo": codigo,
        "descripcion": "HONORARIOS PROFESIONALES",
        "aliquot": rows,
    })


# ═══════════════════════════════════════════════════════════════════
# resolve_purchase_islr_aliquot()
# ═══════════════════════════════════════════════════════════════════

class TestResolverAlicuotaDeCompra(FrappeTestCase):
    """La alícuota que se aplica según el concepto y el tipo del proveedor."""

    def test_toma_la_alicuota_del_tipo_del_proveedor(self) -> None:
        """Con la alícuota del proveedor disponible, usa esa y no otra."""
        tab = _tabulator("004", [
            _aliquot(NATURAL, 3.0, subtracting=107.5),
            _aliquot(JURIDICA, 5.0),
        ])

        row = resolve_purchase_islr_aliquot(tab, JURIDICA)

        self.assertEqual(row.types_of_person, JURIDICA)
        self.assertEqual(row.aliquot, 5.0)

    def test_sociedad_de_personas_aplica_la_unica_alicuota(self) -> None:
        """Proveedor jurídico + concepto de natural con UNA alícuota: la aplica.

        Es el caso MORA TORRES: el concepto 002 sólo tiene tarifa de natural y
        es la que corresponde practicarle. Antes esto reventaba en el camino
        retroactivo.
        """
        tab = _tabulator("002", [_aliquot(NATURAL, 3.0, subtracting=107.5)])

        row = resolve_purchase_islr_aliquot(tab, JURIDICA)

        self.assertEqual(row.types_of_person, NATURAL)
        self.assertEqual(row.aliquot, 3.0)
        self.assertEqual(row.subtracting, 107.5)

    def test_no_elige_cuando_el_concepto_ofrece_varias(self) -> None:
        """Varias alícuotas y ninguna del proveedor: falla, no adivina.

        Es el concepto 077 (1 % natural, 5 % jurídica) con un proveedor no
        domiciliado. Tomar "la primera" declararía 1 % al azar ante el SENIAT.
        """
        tab = _tabulator("077", [
            _aliquot(NATURAL, 1.0, subtracting=35.83),
            _aliquot(JURIDICA, 5.0),
        ])

        with self.assertRaises(frappe.ValidationError):
            resolve_purchase_islr_aliquot(tab, NO_DOMICILIADA)

    def test_ignora_las_alicuotas_en_cero(self) -> None:
        """Una alícuota en 0 no cuenta como opción ofrecida."""
        tab = _tabulator("002", [
            _aliquot(NATURAL, 3.0, subtracting=107.5),
            _aliquot(JURIDICA, 0.0),
        ])

        row = resolve_purchase_islr_aliquot(tab, JURIDICA)

        self.assertEqual(row.types_of_person, NATURAL)

    def test_falla_si_ninguna_alicuota_tiene_tasa(self) -> None:
        """Todas en cero: no hay nada que aplicar."""
        tab = _tabulator("002", [_aliquot(NATURAL, 0.0)])

        with self.assertRaises(frappe.ValidationError):
            resolve_purchase_islr_aliquot(tab, JURIDICA)

    def test_resolver_no_valida_la_configuracion_del_proveedor(self) -> None:
        """El helper resuelve alícuotas; exigir el tipo de persona es del llamador.

        Los dos caminos cortan antes con su propio mensaje
        (_validate_islr_prerequisites en borrador, el guard equivalente en el
        retroactivo), así que acá un tipo vacío no tiene por qué reventar.
        """
        tab = _tabulator("002", [_aliquot(NATURAL, 3.0)])

        row = resolve_purchase_islr_aliquot(tab, "")

        self.assertEqual(row.aliquot, 3.0)


# ═══════════════════════════════════════════════════════════════════
# describe_purchase_islr_row()
# ═══════════════════════════════════════════════════════════════════

class TestDescripcionDeLaFila(FrappeTestCase):
    """La fila debe explicar por sí sola una alícuota de otro tipo."""

    def test_sin_nota_cuando_la_alicuota_es_la_del_proveedor(self) -> None:
        tab = _tabulator("004", [])
        row = _aliquot(JURIDICA, 5.0)

        texto: str = describe_purchase_islr_row(tab, row, JURIDICA)

        self.assertIn("ISLR 004", texto)
        self.assertIn("5.0%", texto)
        self.assertNotIn("aplicada a un proveedor", texto)

    def test_deja_constancia_de_la_alicuota_cruzada(self) -> None:
        """Quien audite el Libro de Compras tiene que ver por qué el 3 %."""
        tab = _tabulator("002", [])
        row = _aliquot(NATURAL, 3.0, subtracting=107.5)

        texto: str = describe_purchase_islr_row(tab, row, JURIDICA)

        self.assertIn("ISLR 002", texto)
        self.assertIn("aplicada a un proveedor", texto)

    def test_sin_tipo_de_persona_no_inventa_nota(self) -> None:
        tab = _tabulator("002", [])
        row = _aliquot(NATURAL, 3.0)

        texto: str = describe_purchase_islr_row(tab, row, "")

        self.assertNotIn("aplicada a un proveedor", texto)


# ═══════════════════════════════════════════════════════════════════
# Los dos caminos resuelven igual
# ═══════════════════════════════════════════════════════════════════

class TestLosDosCaminosCoinciden(FrappeTestCase):
    """Borrador y factura aprobada tienen que aceptar lo mismo.

    La divergencia entre ambos es el bug que motivó este cambio.
    """

    def _tabulador_de_sociedad_de_personas(self) -> _dict:
        return _tabulator("002", [_aliquot(NATURAL, 3.0, subtracting=107.5)])

    def test_borrador_acepta_el_concepto_cruzado(self) -> None:
        """_get_islr_aliquot no debe rechazar al proveedor jurídico."""
        from l10n_ve.controllers.taxes_mixin import TaxesMixin

        tab = self._tabulador_de_sociedad_de_personas()
        with patch(
            "l10n_ve.controllers.taxes_mixin.frappe.get_cached_doc",
            return_value=tab,
        ):
            tabulator, row = TaxesMixin._get_islr_aliquot(None, "002", JURIDICA)

        self.assertIs(tabulator, tab)
        self.assertEqual(row.aliquot, 3.0)

    def test_factura_aprobada_acepta_el_concepto_cruzado(self) -> None:
        """El camino retroactivo calcula en vez de lanzar el error.

        Base 1.000.000 Bs al 3 % menos 107,50 de sustraendo = 29.892,50.
        """
        from l10n_ve.overrides.purchase_invoice import (
            _calculate_purchase_withholding_base_amount,
        )

        invoice = _dict({
            "supplier": "SUPP-MORA-TORRES",
            "base_net_total": 1_000_000.0,
        })
        tab = self._tabulador_de_sociedad_de_personas()

        with patch(
            "l10n_ve.overrides.purchase_invoice.frappe.db.get_value",
            return_value=JURIDICA,
        ), patch(
            "l10n_ve.overrides.purchase_invoice.frappe.get_doc",
            return_value=tab,
        ):
            monto: float = _calculate_purchase_withholding_base_amount(
                invoice, "ISLR", "002"
            )

        self.assertAlmostEqual(monto, 29_892.50, places=2)
