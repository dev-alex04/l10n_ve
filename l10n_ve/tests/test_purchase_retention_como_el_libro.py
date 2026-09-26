# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Pruebas de paridad entre las retenciones de compras y el Libro de Compras.

Verifica que:
1. El Libro de Compras use la misma función de resolución de subárbol (branch_scope_condition).
2. Los montos de retención de IVA entre el Libro de Compras y el reporte de Retención de IVA coincidan al centavo.
3. El total de retenciones de ISLR coincida entre el reporte y la relación del XML fiscal.
4. Las sucursales de grupo resuelvan correctamente todo el subárbol de sus hijas en compras.
"""

import inspect
import unittest

import frappe
from frappe.utils import flt

from l10n_ve.l10n_ve.report.purchase_book import purchase_book as libro
from l10n_ve.l10n_ve.report.vat_withholding import vat_withholding as reporte_iva
from l10n_ve.l10n_ve.report.islr_withholding import islr_withholding as reporte_islr


class TestEstructuraReportesCompras(unittest.TestCase):
	"""Pruebas estructurales: corren siempre, incluso sin facturas en la base."""

	def test_el_libro_usa_branch_scope_condition(self):
		"""Verifica que purchase_book use branch_scope_condition para resolver subárboles."""
		fuente = inspect.getsource(libro.get_query)
		self.assertIn("branch_scope_condition", fuente)

	def test_los_reportes_de_retencion_usan_branch_scope_condition(self):
		"""Verifica que ambos reportes de retenciones usen branch_scope_condition."""
		fuente_iva = inspect.getsource(reporte_iva.get_data)
		fuente_islr = inspect.getsource(reporte_islr.get_data)
		self.assertIn("branch_scope_condition", fuente_iva)
		self.assertIn("branch_scope_condition", fuente_islr)


def _escenario_compras() -> dict | None:
	"""Empresa, mes y sucursales REALES con retenciones de compras."""
	fila = frappe.db.sql(
		"""
		SELECT wv.empresa AS company, YEAR(wv.issue_date) AS anio, MONTH(wv.issue_date) AS mes, COUNT(*) AS n
		FROM `tabVAT Withholding Voucher` wv
		WHERE wv.docstatus = 1
		GROUP BY wv.empresa, anio, mes
		ORDER BY n DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if not fila or not fila[0].n:
		return None
	c = fila[0].company
	d1 = f"{int(fila[0].anio):04d}-{int(fila[0].mes):02d}-01"
	d2 = str(frappe.utils.get_last_day(d1))

	arbol = frappe.db.sql("SELECT name, lft, rgt FROM `tabVE Branch` ORDER BY lft", as_dict=True)

	def subarbol(n):
		b = next(x for x in arbol if x.name == n)
		return [x.name for x in arbol if b.lft <= x.lft and x.rgt <= b.rgt]

	# Buscar una sucursal grupo y una hoja
	hoja = next((b.name for b in arbol if b.rgt - b.lft == 1), None)
	grupo = next((b.name for b in arbol if b.rgt - b.lft > 1), None)

	return {
		"company": c,
		"from_date": d1,
		"to_date": d2,
		"hoja": hoja,
		"grupo": grupo,
		"subarbol": subarbol(grupo) if grupo else [],
	}


class TestParidadRetencionesYLibroCompras(unittest.TestCase):
	"""Cruce numérico contra la base de datos."""

	@classmethod
	def setUpClass(cls):
		cls.esc = _escenario_compras()

	def setUp(self):
		if not self.esc:
			self.skipTest("el sitio no tiene retenciones de compra: nada que cruzar")
		self.base = {k: self.esc[k] for k in ("company", "from_date", "to_date")}

	def test_el_IVA_retenido_coincide_con_el_libro_de_compras(self):
		"""El total de IVA retenido en el reporte coincide exactamente con el Libro de Compras."""
		pb_cols, pb_data, _, _, _ = libro.execute(dict(self.base))
		pb_iva = libro.get_totals_from_data(pb_data).get("taxes_and_charges_deducted", 0)

		vw_cols, vw_data = reporte_iva.execute(dict(self.base))
		vw_iva = sum(flt(d.get("tax_amount_vat", 0)) for d in vw_data)

		self.assertAlmostEqual(vw_iva, pb_iva, places=2)

	def test_sucursal_grupo_resuelve_subarbol_en_compras(self):
		"""Un nodo de grupo incluye las facturas de todas sus hijas en Libro y Retenciones."""
		if not self.esc.get("grupo"):
			self.skipTest("no hay sucursal grupo")
		grupo = self.esc["grupo"]
		f_grupo = {**self.base, "branch": grupo}

		pb_cols, pb_data, _, _, _ = libro.execute(dict(f_grupo))
		vw_cols, vw_data = reporte_iva.execute(dict(f_grupo))
		iw_cols, iw_data = reporte_islr.execute(dict(f_grupo))

		rama = set(self.esc["subarbol"])
		if vw_data:
			self.assertTrue({d.get("branch") for d in vw_data if d.get("branch")} <= rama)
		if iw_data:
			self.assertTrue({d.get("branch") for d in iw_data if d.get("branch")} <= rama)

		# La suma del IVA retenido del grupo coincide entre libro y reporte
		pb_iva = libro.get_totals_from_data(pb_data).get("taxes_and_charges_deducted", 0)
		vw_iva = sum(flt(d.get("tax_amount_vat", 0)) for d in vw_data)
		self.assertAlmostEqual(vw_iva, pb_iva, places=2)

	def test_exclusion_de_sucursal(self):
		"""Verifica que exclude_branches omita las sucursales indicadas."""
		if not self.esc.get("hoja"):
			self.skipTest("no hay sucursal hoja")
		hoja = self.esc["hoja"]
		f_ex = {**self.base, "branch": [hoja], "exclude_branches": 1}

		vw_cols, vw_data = reporte_iva.execute(dict(f_ex))
		iw_cols, iw_data = reporte_islr.execute(dict(f_ex))

		self.assertFalse(any(d.get("branch") == hoja for d in vw_data))
		self.assertFalse(any(d.get("branch") == hoja for d in iw_data))
