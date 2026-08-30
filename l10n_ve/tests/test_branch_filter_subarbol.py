# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""El filtro «Sucursal» tiene que significar lo mismo en las retenciones que en el Libro de Ventas.

`VE Branch` es un árbol y sus nodos intermedios se usan de verdad: en producción
`MIR-01` tiene 7 descendientes y `GALANET HQ` --la raíz-- tiene 39. El Libro de
Ventas resuelve el subárbol con `lft`/`rgt`; los reportes de Retención de IVA e
ISLR comparaban por igualdad plana.

El resultado no era un error sino algo peor: filtrar por un nodo padre devolvía
menos filas, en silencio. Medido sobre una copia de producción, filtrando por la
raíz `GALANET HQ`: **0 filas** con la igualdad plana contra **286** con el
subárbol. Estos reportes alimentan declaraciones al SENIAT, así que subdeclarar
sin avisar es lo peor que pueden hacer.

El segundo problema era de coherencia: el `WHERE` aceptaba la fila si coincidía
`parent.branch` O `inv.branch`, pero la columna mostraba `COALESCE(...)`. Una
retención de ARA-02 sobre una factura de MIR-01 pasaba el filtro «MIR-01» y se
mostraba rotulada **ARA-02**: el usuario pedía una sucursal y veía otra.
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from l10n_ve.l10n_ve.report.islr_withholding import islr_withholding as islr
from l10n_ve.l10n_ve.report.sales_book.sales_book import branch_scope_condition
from l10n_ve.l10n_ve.report.vat_withholding import vat_withholding as vat

SB = "l10n_ve.l10n_ve.report.sales_book.sales_book"

_PADRE = "TEST-SUC-PADRE"
_HIJA = "TEST-SUC-HIJA"
_AJENA = "TEST-SUC-AJENA"
_SUPPLIER = "TEST-SUC-PROVEEDOR"
_V_PADRE = "TEST-SUC-VAT-PADRE"
_V_HIJA = "TEST-SUC-VAT-HIJA"
_V_AJENA = "TEST-SUC-VAT-AJENA"

# Rango de `lft`/`rgt` bien lejos del árbol real del sitio, para que el subárbol
# de prueba no arrastre sucursales de verdad ni al revés.
_LFT = 900000


class TestBranchScopeCondition(unittest.TestCase):
    """La condición que arma el helper, sin base de datos."""

    def test_un_nodo_padre_se_expande_a_su_subarbol(self) -> None:
        with patch(f"{SB}.get_branch_subtree", return_value={"MIR-01", "DESIGNET", "GUARENAS"}):
            sql, params = branch_scope_condition("MIR-01", "b.branch")

        self.assertEqual(sql, " AND b.branch IN %(branch_scope)s")
        # Ordenado: hace la consulta reproducible y el plan cacheable.
        self.assertEqual(params, {"branch_scope": ["DESIGNET", "GUARENAS", "MIR-01"]})

    def test_una_hoja_usa_igualdad_simple(self) -> None:
        """En una hoja no hay nada que expandir y la igualdad aprovecha `branch_index`."""
        with patch(f"{SB}.get_branch_subtree", return_value=None):
            sql, params = branch_scope_condition("DC-01", "b.branch")

        self.assertEqual(sql, " AND b.branch = %(branch)s")
        self.assertEqual(params, {"branch": "DC-01"})

    def test_sin_sucursal_no_agrega_condicion(self) -> None:
        self.assertEqual(branch_scope_condition(None, "b.branch"), ("", {}))
        self.assertEqual(branch_scope_condition("", "b.branch"), ("", {}))

    def test_una_sucursal_inexistente_devuelve_cero_filas_no_todas(self) -> None:
        """`get_branch_subtree` devuelve `None` tanto para una hoja como para algo que no existe.

        Los dos casos tienen que terminar en igualdad, no en «sin filtro»: si el
        nombre no existe el reporte debe salir vacío, nunca completo.
        """
        with patch(f"{SB}.get_branch_subtree", return_value=None):
            sql, params = branch_scope_condition("NO-EXISTE", "b.branch")

        self.assertIn("=", sql)
        self.assertEqual(params, {"branch": "NO-EXISTE"})


class TestFiltroYColumnaMiranLoMismo(unittest.TestCase):
    """El `WHERE` y el `SELECT` tienen que hablar de la misma expresión.

    Si divergen, el reporte filtra por una sucursal y rotula las filas con otra;
    y no hay forma de notarlo mirando la pantalla, porque el número que sale es
    plausible.
    """

    def _consulta_de(self, modulo, filtros: dict) -> str:
        db = MagicMock()
        db.sql.return_value = []
        with patch.object(frappe, "db", db), \
             patch(f"{SB}.get_branch_subtree", return_value={"A", "B"}):
            modulo.get_data(dict(filtros))
        return db.sql.call_args[0][0]

    def test_vat_withholding(self) -> None:
        query = self._consulta_de(vat, {
            "company": "X", "from_date": "2026-01-01", "to_date": "2026-12-31", "branch": "PADRE",
        })
        self.assertIn(f"{vat.BRANCH_EXPR} AS branch", query)
        self.assertIn(f"{vat.BRANCH_EXPR} IN %(branch_scope)s", query)

    def test_islr_withholding(self) -> None:
        query = self._consulta_de(islr, {
            "company": "X", "from_date": "2026-01-01", "to_date": "2026-12-31", "branch": "PADRE",
        })
        self.assertIn(f"{islr.BRANCH_EXPR} AS branch", query)
        self.assertIn(f"{islr.BRANCH_EXPR} IN %(branch_scope)s", query)

    def test_el_respaldo_a_la_factura_no_se_come_la_cadena_vacia(self) -> None:
        """Frappe guarda `''` --no NULL-- en un Link sin cargar.

        Con `COALESCE` pelado el respaldo a la sucursal de la factura no entraría
        nunca, y la fila saldría rotulada con una sucursal vacía.
        """
        for modulo in (vat, islr):
            with self.subTest(modulo=modulo.__name__):
                self.assertIn("NULLIF(parent.branch, '')", modulo.BRANCH_EXPR)


class TestSubarbolContraLaBase(FrappeTestCase):
    """El mismo caso, pero ejecutando el SQL de verdad contra un árbol de prueba."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.company = frappe.db.get_value("Company", {}, "name")
        cls._limpiar()
        cls._armar_arbol()
        cls._armar_comprobantes()
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._limpiar()
        frappe.db.commit()
        super().tearDownClass()

    @classmethod
    def _limpiar(cls) -> None:
        vouchers = [_V_PADRE, _V_HIJA, _V_AJENA]
        frappe.db.delete("VAT Withholding Voucher Item", {"parent": ["in", vouchers]})
        frappe.db.delete("VAT Withholding Voucher", {"name": ["in", vouchers]})
        frappe.db.delete("Supplier", {"name": _SUPPLIER})
        frappe.db.delete("VE Branch", {"name": ["in", [_PADRE, _HIJA, _AJENA]]})

    @classmethod
    def _armar_arbol(cls) -> None:
        # PADRE (900000..900003) contiene a HIJA (900001..900002).
        # AJENA queda fuera del rango: sirve para comprobar que el subárbol no
        # se lleva puesto lo que no le toca.
        for nombre, lft, rgt, es_grupo, padre in (
            (_PADRE, _LFT, _LFT + 3, 1, None),
            (_HIJA, _LFT + 1, _LFT + 2, 0, _PADRE),
            (_AJENA, _LFT + 10, _LFT + 11, 0, None),
        ):
            suc = frappe.get_doc({
                "doctype": "VE Branch",
                "branch_name": nombre,
                "company": cls.company,
                "lft": lft,
                "rgt": rgt,
                "is_group": es_grupo,
                "parent_ve_branch": padre,
            })
            suc.name = nombre
            suc.db_insert()

        supp = frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": _SUPPLIER,
            "supplier_group": "All Supplier Groups",
            "tax_id": "J-98765432-1",
        })
        supp.name = _SUPPLIER
        supp.db_insert()

    @classmethod
    def _armar_comprobantes(cls) -> None:
        for idx, (nombre, sucursal) in enumerate((
            (_V_PADRE, _PADRE), (_V_HIJA, _HIJA), (_V_AJENA, _AJENA),
        ), start=1):
            v = frappe.get_doc({
                "doctype": "VAT Withholding Voucher",
                "empresa": cls.company,
                "supplier": _SUPPLIER,
                "branch": sucursal,
                "issue_date": nowdate(),
                "start_date": nowdate(),
                "end_date": nowdate(),
                "voucher_number": f"2026070000900{idx}",
                "docstatus": 1,
            })
            v.name = nombre
            v.db_insert()

            item = frappe.get_doc({
                "doctype": "VAT Withholding Voucher Item",
                "parent": nombre,
                "parenttype": "VAT Withholding Voucher",
                "parentfield": "vat_withholding_voucher_item",
                "idx": 1,
                "bill_no": f"TEST-SUC-FACT-{idx}",
                "bill_control": "00-00001",
                "posting_date": nowdate(),
                "total": 10000,
                "rate": 16,
                "withholding_rate": 75,
                "tax_amount_vat": 1200,
            })
            item.name = f"TEST-SUC-ITEM-{idx}"
            item.db_insert()

    def _filas(self, branch: str | None) -> list:
        filtros = {
            "company": self.company,
            "from_date": nowdate(),
            "to_date": nowdate(),
            "supplier": _SUPPLIER,
        }
        if branch:
            filtros["branch"] = branch
        return vat.get_data(filtros)

    def test_filtrar_por_el_padre_trae_tambien_a_la_hija(self) -> None:
        """Este es el caso que fallaba: con igualdad plana solo salía el padre."""
        sucursales = sorted(r["branch"] for r in self._filas(_PADRE))
        self.assertEqual(sucursales, [_HIJA, _PADRE])

    def test_el_subarbol_no_arrastra_sucursales_de_afuera(self) -> None:
        self.assertNotIn(_AJENA, [r["branch"] for r in self._filas(_PADRE)])

    def test_filtrar_por_la_hoja_trae_solo_la_hoja(self) -> None:
        self.assertEqual([r["branch"] for r in self._filas(_HIJA)], [_HIJA])

    def test_sin_filtro_estan_las_tres(self) -> None:
        sucursales = sorted(r["branch"] for r in self._filas(None))
        self.assertEqual(sucursales, [_AJENA, _HIJA, _PADRE])

    def test_una_sucursal_inexistente_no_devuelve_todo(self) -> None:
        self.assertEqual(self._filas("TEST-SUC-QUE-NO-EXISTE"), [])
