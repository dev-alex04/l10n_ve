# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""El centro de costo de un cobro (Payment Entry) prefiere el de la factura, no
el de la sucursal en que se cargó -- cuando las facturas se ponen de acuerdo.

Antes `_set_cost_center_from_branch` derivaba SIEMPRE del `doc.branch` del
cobro, sin mirar qué facturas salda. Un cobro cargado en la sucursal A que
salda una factura de la sucursal B terminaba con el centro de costo de A, que
esa factura no tiene. Medido en producción: 8 casos limpios donde las facturas
referenciadas SÍ coinciden entre ellas en un centro de costo, y ese valor no es
el que la sucursal del cobro habría puesto.

La factura no falla nunca -- de las facturas emitidas con sucursal y centro de
costo, ninguna trae uno distinto al de su propia sucursal --, así que preferirla
no pierde nada donde coincide con la sucursal y gana justo donde difieren.

Es la misma regla que `domina_isp.overrides.payment_entry._resolve_cost_center`
ya aplica en la conciliación; acá se porta a la emisión, que es donde faltaba
--el propio docstring de esa función en domina_isp lo deja anotado como pendiente
para esta app--. No se importa de domina_isp: l10n_ve es la app base.

Cuando las facturas NO coinciden entre ellas, seguir cayendo a la sucursal es
DELIBERADO, no una laguna: repartido entre varias, ningún centro de costo sería
correcto para todas, y un valor definido y auditable es mejor que uno vacío --el
filtro de permisos de sucursal (`branch IN (...)`) no casa contra `NULL`--.

Corren sin site, con `frappe` parcheado.
"""

import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict

from l10n_ve.helpers.helpers import (
    _payment_entry_invoice_cost_centers,
    _set_cost_center_from_branch,
)

MOD = "l10n_ve.helpers.helpers"


def _pe(branch=None, cost_center=None, references=None, doctype="Payment Entry"):
    return _dict({
        "doctype": doctype,
        "branch": branch,
        "cost_center": cost_center,
        "references": references or [],
    })


def _ref(reference_name, reference_doctype="Sales Invoice"):
    return _dict({"reference_doctype": reference_doctype, "reference_name": reference_name})


class TestInvoiceCostCenters(unittest.TestCase):
    """El conjunto que arma `_payment_entry_invoice_cost_centers`, sin base de datos."""

    def _con(self, refs, filas_si):
        doc = _pe(references=refs)
        frappe_db = MagicMock()
        frappe_db.get_all = MagicMock(return_value=filas_si)
        with patch(f"{MOD}.frappe.get_all", frappe_db.get_all):
            return _payment_entry_invoice_cost_centers(doc)

    def test_una_sola_factura(self) -> None:
        s = self._con([_ref("SI-1")], [_dict(name="SI-1", cost_center="MIR-01")])
        self.assertEqual(s, {"MIR-01"})

    def test_dos_facturas_de_acuerdo(self) -> None:
        s = self._con(
            [_ref("SI-1"), _ref("SI-2")],
            [_dict(name="SI-1", cost_center="MIR-01"), _dict(name="SI-2", cost_center="MIR-01")],
        )
        self.assertEqual(s, {"MIR-01"})

    def test_dos_facturas_en_desacuerdo(self) -> None:
        s = self._con(
            [_ref("SI-1"), _ref("SI-2")],
            [_dict(name="SI-1", cost_center="MIR-01"), _dict(name="SI-2", cost_center="MIR-03")],
        )
        self.assertEqual(s, {"MIR-01", "MIR-03"})

    def test_una_factura_sin_centro_de_costo_veta_el_acuerdo(self) -> None:
        """No se completa a medias: una factura sin dato mete `None` y rompe el acuerdo."""
        s = self._con(
            [_ref("SI-1"), _ref("SI-2")],
            [_dict(name="SI-1", cost_center="MIR-01"), _dict(name="SI-2", cost_center=None)],
        )
        self.assertEqual(s, {"MIR-01", None})

    def test_una_referencia_que_no_es_factura_se_ignora(self) -> None:
        s = self._con(
            [_ref("SI-1"), _ref("JE-1", reference_doctype="Journal Entry")],
            [_dict(name="SI-1", cost_center="MIR-01")],
        )
        self.assertEqual(s, {"MIR-01"})

    def test_sin_referencias_devuelve_vacio(self) -> None:
        self.assertEqual(self._con([], []), set())


class TestSetCostCenterFromBranchPaymentEntry(unittest.TestCase):
    """El caso que reproduce el bug medido: sucursal A, facturas de B."""

    def _correr(self, doc, branch_cc, invoice_ccs):
        with patch(f"{MOD}.frappe.get_meta") as get_meta, \
             patch(f"{MOD}.frappe.get_cached_value", return_value=branch_cc), \
             patch(f"{MOD}._payment_entry_invoice_cost_centers", return_value=invoice_ccs):
            get_meta.return_value.get_field.return_value = True
            _set_cost_center_from_branch(doc)
        return doc

    def test_las_facturas_coinciden_y_ganan_sobre_la_sucursal(self) -> None:
        """El caso medido: 8 cobros en producción exactamente así."""
        doc = _pe(branch="MIR-03", cost_center="MIR-03")
        self._correr(doc, branch_cc="MIR-03", invoice_ccs={"MIR-01"})
        self.assertEqual(doc.cost_center, "MIR-01")

    def test_sin_acuerdo_cae_a_la_sucursal_deliberadamente(self) -> None:
        """Repartido entre varias, ninguna es correcta para todas: la sucursal es el respaldo, no un olvido."""
        doc = _pe(branch="MIR-01")
        self._correr(doc, branch_cc="MIR-01", invoice_ccs={"MIR-01", "MIR-03"})
        self.assertEqual(doc.cost_center, "MIR-01")

    def test_sin_facturas_se_comporta_como_antes(self) -> None:
        doc = _pe(branch="DC-01")
        self._correr(doc, branch_cc="DC-01", invoice_ccs=set())
        self.assertEqual(doc.cost_center, "DC-01")

    def test_las_facturas_deciden_aunque_la_sucursal_este_vacia(self) -> None:
        """Vacío es peor: si las facturas se ponen de acuerdo, no hace falta sucursal."""
        doc = _pe(branch=None)
        self._correr(doc, branch_cc=None, invoice_ccs={"MIR-05"})
        self.assertEqual(doc.cost_center, "MIR-05")

    def test_propaga_a_las_tablas_hijas(self) -> None:
        item = _dict(cost_center=None)
        doc = _pe(branch="MIR-03", cost_center="MIR-03")
        doc["items"] = [item]
        self._correr(doc, branch_cc="MIR-03", invoice_ccs={"MIR-01"})
        self.assertEqual(item.cost_center, "MIR-01")


class TestOtrosDoctypesSinCambios(unittest.TestCase):
    """El resto de los 10 doctypes hookeados no tocan facturas de Payment Entry: sin cambio de conducta."""

    def test_sales_invoice_sigue_derivando_de_la_sucursal(self) -> None:
        doc = _pe(branch="MIR-01", cost_center=None, doctype="Sales Invoice")
        with patch(f"{MOD}.frappe.get_meta") as get_meta, \
             patch(f"{MOD}.frappe.get_cached_value", return_value="MIR-01"), \
             patch(f"{MOD}._payment_entry_invoice_cost_centers") as invoice_fn:
            get_meta.return_value.get_field.return_value = True
            _set_cost_center_from_branch(doc)
        invoice_fn.assert_not_called()
        self.assertEqual(doc.cost_center, "MIR-01")

    def test_purchase_invoice_sigue_igual(self) -> None:
        doc = _pe(branch="DC-01", cost_center=None, doctype="Purchase Invoice")
        with patch(f"{MOD}.frappe.get_meta") as get_meta, \
             patch(f"{MOD}.frappe.get_cached_value", return_value="DC-01"), \
             patch(f"{MOD}._payment_entry_invoice_cost_centers") as invoice_fn:
            get_meta.return_value.get_field.return_value = True
            _set_cost_center_from_branch(doc)
        invoice_fn.assert_not_called()
        self.assertEqual(doc.cost_center, "DC-01")
