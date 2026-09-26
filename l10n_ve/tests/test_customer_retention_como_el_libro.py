"""El reporte «Retención de Clientes» dice lo MISMO que el Libro de Ventas.

Es el reporte que abre la tarjeta «Retención IVA» (y la de ISLR) del panel ISP, y la
tarjeta sale del libro. Medido sobre agosto-2026 en local, antes de este cambio:

	tarjeta IVA con MIR-01 = Bs 252.690,50        reporte: vacío
	tarjeta IVA sin filtro = Bs 4.947.758,58      reporte: Bs 4.987.272,01

Dos causas, y este archivo pinnea las dos:

1. El filtro de sucursal comparaba por igualdad. MIR-01 es una sucursal de grupo y
   ninguna factura está a su nombre: el reporte salía vacío sin error ni aviso. Ahora usa
   ``branch_scope_condition``, la misma del libro y de los reportes de retención de
   proveedores (84c59a80), que resuelve el subárbol.
2. La retención se atribuía al mes de la FACTURA; el libro la atribuye al de su
   COMPROBANTE. Las facturas de agosto con comprobante de septiembre --seis, por
   Bs 39.513,43-- se contaban en agosto, donde el libro no las declara.

LO QUE ESTE ARCHIVO **NO** CUBRE
--------------------------------
Que el LIBRO acierte: si su regla está mal, los dos se equivocan igual y esto sigue en
verde. Esto vigila que no se separen.
"""

import inspect
import unittest

import frappe
from frappe.utils import flt

from l10n_ve.l10n_ve.report.customer_retention import customer_retention as reporte
from l10n_ve.l10n_ve.report.sales_book import sales_book as libro


class TestElReporteUsaLasReglasDelLibro(unittest.TestCase):
	"""Estructural: corre siempre, incluso en un sitio sin una sola factura."""

	def test_la_sucursal_es_la_MISMA_funcion_del_libro(self):
		"""Se compara el objeto, no el nombre: una copia «para no tocar el libro» pasaría
		un grep y se separaría el primer día que el libro cambie."""
		self.assertIs(reporte.branch_scope_condition, libro.branch_scope_condition)
		self.assertNotIn(".branch = %(branch)s", inspect.getsource(reporte.get_data))

	def test_el_corte_fiscal_es_el_del_libro(self):
		"""Un solo reloj: la fecha escrita aparte ya estaba repetida en dos lugares."""
		self.assertEqual(reporte._FISCAL_CUTOFF_DATE, libro._FISCAL_CUTOFF_DATE)
		self.assertNotIn(libro._FISCAL_CUTOFF_DATE, inspect.getsource(reporte))

	def test_el_comprobante_de_otro_periodo_no_se_cuenta(self):
		"""IVA por `withholding_date` e ISLR por `islr_date`, en facturas y en notas."""
		fuente = inspect.getsource(reporte.get_data)
		for alias in ("si", "nc"):
			for campo in ("withholding_date", "islr_date"):
				with self.subTest(alias=alias, campo=campo):
					self.assertIn(f"{alias}.{campo} NOT BETWEEN %(from_date)s AND %(to_date)s", fuente)

	def test_el_resumen_va_en_la_moneda_de_la_empresa(self):
		"""Sin moneda, Frappe rotulaba «REF.» los totales en bolívares."""
		filas = [{"base_total": 10.0, "grand_total": 11.6, "withholding_amount": 1.2}]
		resumen = reporte.get_report_summary(filas, "VEF")
		self.assertEqual({r["currency"] for r in resumen}, {"VEF"})


def _escenario() -> dict | None:
	"""Empresa, mes y sucursales REALES con retención de IVA, o ``None`` si no hay.

	Nada va escrito a mano: en otro sitio los nombres son otros. Y sin datos se salta,
	en vez de comparar ceros contra ceros.
	"""
	fila = frappe.db.sql(
		"""
		SELECT company, YEAR(posting_date) AS anio, MONTH(posting_date) AS mes, COUNT(*) AS n
		FROM `tabSales Invoice`
		WHERE docstatus = 1 AND posting_date > %(corte)s
		  AND COALESCE(vat_withholding_voucher_number, '') != ''
		GROUP BY company, anio, mes
		ORDER BY n DESC
		LIMIT 1
		""",
		{"corte": libro._FISCAL_CUTOFF_DATE},
		as_dict=True,
	)
	if not fila or not fila[0].n:
		return None
	c = fila[0].company
	d1 = f"{int(fila[0].anio):04d}-{int(fila[0].mes):02d}-01"
	d2 = str(frappe.utils.get_last_day(d1))
	arbol = frappe.db.sql("SELECT name, lft, rgt FROM `tabVE Branch` ORDER BY lft", as_dict=True)
	con_retencion = dict(frappe.db.sql(
		"""SELECT branch, COUNT(*) FROM `tabSales Invoice`
		   WHERE docstatus = 1 AND company = %(c)s AND posting_date BETWEEN %(d1)s AND %(d2)s
			 AND COALESCE(vat_withholding_voucher_number, '') != ''
		   GROUP BY branch""",
		{"c": c, "d1": d1, "d2": d2},
	))

	def subarbol(n):
		b = next(x for x in arbol if x.name == n)
		return [x.name for x in arbol if b.lft <= x.lft and x.rgt <= b.rgt]

	hoja = next((b.name for b in arbol if b.rgt - b.lft == 1 and con_retencion.get(b.name)), None)
	# Un GRUPO sin facturas propias pero con hijas que sí: es el caso de MIR-01, el que
	# dejaba el reporte vacío.
	grupo = next((b.name for b in arbol if b.rgt - b.lft > 1 and not con_retencion.get(b.name)
				  and sum(con_retencion.get(x, 0) for x in subarbol(b.name))), None)
	return {"company": c, "from_date": d1, "to_date": d2, "hoja": hoja, "grupo": grupo,
			"subarbol": subarbol(grupo) if grupo else []}

def _escenario_anterior_al_corte() -> dict | None:
	"""Empresa y mes REAL anterior al corte fiscal con retenciones históricas.

	Verifica la regla de la base para documentos <= _FISCAL_CUTOFF_DATE:
	en períodos históricos declarados al SENIAT por fecha de emisión, las
	retenciones se conservan aunque carezcan de número de comprobante.
	"""
	fila = frappe.db.sql(
		"""
		SELECT si.company, YEAR(si.posting_date) AS anio, MONTH(si.posting_date) AS mes, COUNT(*) AS n
		FROM `tabSales Invoice` si
		JOIN `tabSales Taxes and Charges` stc ON si.name = stc.parent
		WHERE si.docstatus = 1 AND si.posting_date < DATE_FORMAT(%(corte)s, '%%Y-%%m-01')
		  AND stc.charge_type IN ('VAT Withholding', 'ISLR') AND stc.tax_amount != 0
		GROUP BY si.company, anio, mes
		ORDER BY anio DESC, mes DESC
		LIMIT 1
		""",
		{"corte": libro._FISCAL_CUTOFF_DATE},
		as_dict=True,
	)
	if not fila or not fila[0].n:
		return None
	c = fila[0].company
	d1 = f"{int(fila[0].anio):04d}-{int(fila[0].mes):02d}-01"
	d2 = str(frappe.utils.get_last_day(d1))
	return {"company": c, "from_date": d1, "to_date": d2}



def _total(filtros: dict, tipo: str) -> tuple[float, list]:
	datos = reporte.execute({**filtros, "retention_type": tipo})[1]
	return sum(flt(d.get("withholding_amount")) for d in datos), datos


class TestElReporteDaElMismoNumeroQueElLibro(unittest.TestCase):
	"""El cruce de verdad, contra la base."""

	@classmethod
	def setUpClass(cls):
		cls.esc = _escenario()
		cls.esc_pre = _escenario_anterior_al_corte()

	def setUp(self):
		if not self.esc:
			self.skipTest("el sitio no tiene retenciones de IVA con comprobante: nada que cruzar")
		self.base = {k: self.esc[k] for k in ("company", "from_date", "to_date")}

	def _casos(self) -> list:
		casos = [("sin filtro de sucursal", self.base)]
		if self.esc["hoja"]:
			casos.append((f"sucursal HOJA ({self.esc['hoja']})", {**self.base, "branch": self.esc["hoja"]}))
		if self.esc["grupo"]:
			casos.append((f"sucursal GRUPO ({self.esc['grupo']})", {**self.base, "branch": self.esc["grupo"]}))
		return casos

	def test_el_IVA_retenido_es_el_del_libro(self):
		"""El libro resume SOLO el período principal: los ajustes (`04-Ajus`) se listan
		pero no se suman. El reporte tiene que dar ese número, no otro."""
		for etiqueta, filtros in self._casos():
			with self.subTest(caso=etiqueta):
				principal, _ajustes = libro.get_sales_data(dict(filtros))
				del_libro = flt(libro.get_total_row(principal).get("iva_retained"))
				del_reporte, _ = _total(filtros, "IVA")
				self.assertAlmostEqual(del_reporte, del_libro, places=2)

	def test_un_GRUPO_trae_lo_de_sus_hijas(self):
		"""El caso que dejaba el reporte vacío: la suma de lo que hay en su subárbol."""
		if not self.esc["grupo"]:
			self.skipTest("no hay una sucursal de grupo con retenciones solo en sus hijas")
		rama = set(self.esc["subarbol"])
		for tipo in ("IVA", "ISLR"):
			with self.subTest(tipo=tipo):
				del_grupo, datos = _total({**self.base, "branch": self.esc["grupo"]}, tipo)
				_todo, todas = _total(self.base, tipo)
				self.assertAlmostEqual(
					del_grupo, sum(flt(d["withholding_amount"]) for d in todas if d.get("branch") in rama),
					places=2)
				self.assertTrue({d.get("branch") for d in datos} <= rama)

	def test_ningun_comprobante_de_otro_mes_entra(self):
		"""La retención cuenta en el mes de su comprobante, como en el libro."""
		for tipo in ("IVA", "ISLR"):
			with self.subTest(tipo=tipo):
				_t, datos = _total(self.base, tipo)
				fuera = [d.get("name") for d in datos
						 if str(d.get("posting_date")) > libro._FISCAL_CUTOFF_DATE
						 and d.get("withholding_date")
						 and not (self.base["from_date"] <= str(d["withholding_date"]) <= self.base["to_date"])]
				self.assertEqual(fuera, [])

	def test_periodo_anterior_al_corte_fiscal_conserva_retenciones(self):
		"""Períodos anteriores al corte fiscal mantienen la regla de la base:
		las retenciones se declaran en el mes de emisión de la factura y no se
		descartan por falta de número de comprobante."""
		if not self.esc_pre:
			self.skipTest("el sitio no tiene retenciones anteriores al corte fiscal: nada que cruzar")
		base_filtros = {k: self.esc_pre[k] for k in ("company", "from_date", "to_date")}
		company_currency = frappe.get_cached_value("Company", base_filtros["company"], "default_currency")

		for rtype, ctype in (("IVA", "VAT Withholding"), ("ISLR", "ISLR")):
			with self.subTest(tipo=rtype):
				del_reporte, datos = _total(base_filtros, rtype)
				self.assertGreater(del_reporte, 0, f"Retenciones {rtype} cayeron a 0 en mes anterior al corte")
				self.assertGreater(len(datos), 0)

				# Suma esperada según la regla de la base para documentos <= corte
				si_esp = frappe.db.sql(
					"""
					SELECT SUM(ABS(stc.tax_amount) * (CASE WHEN si.currency != %(curr)s THEN si.conversion_rate ELSE 1 END))
					FROM `tabSales Invoice` si
					JOIN `tabSales Taxes and Charges` stc ON si.name = stc.parent
					WHERE (si.docstatus = 1 OR (si.docstatus = 2 AND si.is_void = 1))
					  AND si.is_void = 0 AND si.company = %(company)s
					  AND si.posting_date BETWEEN %(from_date)s AND %(to_date)s
					  AND stc.charge_type = %(ctype)s AND stc.tax_amount != 0
					""",
					{**base_filtros, "curr": company_currency, "ctype": ctype},
				)[0][0] or 0.0

				nc_esp = frappe.db.sql(
					"""
					SELECT SUM(ABS(stc.tax_amount) * (CASE WHEN nc.currency != %(curr)s THEN nc.conversion_rate ELSE 1 END))
					FROM `tabVE Sales Credit Note` nc
					JOIN `tabSales Taxes and Charges` stc ON nc.name = stc.parent
					WHERE nc.docstatus = 1 AND nc.company = %(company)s
					  AND nc.posting_date BETWEEN %(from_date)s AND %(to_date)s
					  AND stc.charge_type = %(ctype)s AND stc.tax_amount != 0
					""",
					{**base_filtros, "curr": company_currency, "ctype": ctype},
				)[0][0] or 0.0

				esperado = flt(si_esp) - flt(nc_esp)
				self.assertAlmostEqual(del_reporte, esperado, places=2)
