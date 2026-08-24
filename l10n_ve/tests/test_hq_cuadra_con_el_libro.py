"""Los dos reportes fiscales tienen que dar lo MISMO donde corresponden.

La fuente de verdad es el **Libro de Ventas**. «Facturas de Venta HQ» es un envoltorio:
reusa ``get_columns``, ``get_sales_data``, ``get_total_row`` y ``get_report_summary``, y
solo agrega columnas de consolidación —sucursal principal, municipio, y las dos sumas
por alícuota—.

Hoy eso se cumple, pero lo sostenía un docstring. Basta que alguien copie una función
«para no tocar el Libro» y los dos reportes empiezan a divergir en silencio: nadie
compara dos pantallas hasta que el SENIAT pregunta.

El cruce se corre sobre las combinaciones donde los dos reportes DEBEN coincidir: sin
filtro, por sucursal hoja, por sucursal grupo —que dispara el rollup de subárbol—, por
sucursal principal, y por las dos juntas. El municipio queda fuera a propósito: solo
existe en el HQ.

LO QUE ESTE ARCHIVO **NO** CUBRE
--------------------------------
Un error en el codigo COMPARTIDO. Si `sales_book` empieza a filtrar mal, los dos
reportes se equivocan igual y el cruce sigue en verde —se comprobo rompiendo
`resolve_branch_scope`: cero fallos—. Esto vigila que no se SEPAREN, no que acierten;
lo segundo lo cuidan los tests de cada reporte por su cuenta.
"""

import inspect
import unittest

import frappe

from l10n_ve.l10n_ve.report.sales_book import sales_book as libro
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq import ve_sales_invoices_hq as hq


class TestElHQ_NoReimplementaAlLibro(unittest.TestCase):
	"""Estructural: corre siempre, incluso en un sitio sin una sola factura.

	Es la mitad barata de la garantía. La otra mitad —que los números coincidan— cuesta
	unos segundos y necesita datos; ésta no, así que en un sitio vacío igual protege.
	"""

	#: Lo que el HQ reusa. La clave es el alias con que lo importa.
	REUSADO = {
		"_sales_book_columns": "get_columns",
		"_sales_book_data": "get_sales_data",
		"_sales_book_total_row": "get_total_row",
		"_sales_book_report_summary": "get_report_summary",
	}

	def test_reusa_LAS_funciones_del_libro_y_no_uma_copia(self):
		"""Se compara la identidad del objeto, no el nombre.

		Un ``grep`` pasaría igual si alguien dejara el import y encima definiera una
		función propia con el mismo alias. ``is`` no.
		"""
		for alias, original in self.REUSADO.items():
			with self.subTest(funcion=original):
				self.assertIs(getattr(hq, alias), getattr(libro, original))

	def test_el_HQ_no_define_ninguna_de_esas_funciones(self):
		"""La forma en que esto se rompe es «la copio acá para no tocar el Libro»."""
		fuente = inspect.getsource(hq)
		for original in self.REUSADO.values():
			with self.subTest(funcion=original):
				self.assertNotIn(f"\ndef {original}(", fuente)

	def test_las_sumas_del_HQ_cubren_TODAS_las_alicuotas_del_libro(self):
		"""Estructural a proposito, y no comparando importes.

		«Base Imponible Total» y «Monto IVA Total» son lo unico que el HQ calcula: suman
		las seis bases y los seis IVA del libro. Verificarlo por importe no alcanza —se
		probo: quitandole una alicuota a la suma, el cruce numerico sigue en verde
		porque en estos datos las tasas reducida y adicional estan en CERO—. El dia que
		exista una venta a tasa reducida, la columna diria de menos y nadie se entera.

		Los conjuntos esperados salen de las columnas del PROPIO libro, asi que si
		manana aparece una septima alicuota, este test la exige sin que haya que
		tocarlo.
		"""
		campos = {c["fieldname"] for c in libro.get_columns() if c.get("fieldname")}
		bases = {f for f in campos if f.startswith("base_") and f != "base_amount_igtf"}
		ivas = {f for f in campos if f.startswith("iva_") and f != "iva_retained"}

		self.assertEqual(set(hq.TAXABLE_BASE_FIELDS), bases)
		self.assertEqual(set(hq.VAT_AMOUNT_FIELDS), ivas)

	def test_los_DOS_resumen_solo_con_las_filas_del_PERIODO(self):
		"""Las filas de ajuste (``04-Ajus``) se MUESTRAN pero no se suman.

		Son retenciones cuyo comprobante cayó en este período pero cuya factura es de
		otro. Si uno de los dos las sumara, el total diferiría sin que nada se vea roto.
		Medido cuando pasó: 1 fila de ajuste desviaba Bs. 285.009,73.
		"""
		self.assertIn("get_total_row(main_data)", inspect.getsource(libro.execute))
		self.assertIn("_sales_book_total_row(main_data)", inspect.getsource(hq.get_hq_data))


def _escenario() -> dict | None:
	"""Empresa, período y sucursales REALES del sitio, o ``None`` si no hay datos.

	Nada va escrito a mano: en otro sitio los nombres son otros. Y si no hay facturas,
	se devuelve ``None`` para saltar en vez de comparar ceros contra ceros, que es la
	forma clásica de tener un test verde que no prueba nada.
	"""
	# Sin `DATE_FORMAT`: su cadena de formato lleva `%` y esta consulta no pasa
	# parametros, asi que pymysql no interpola y el `%%` llegaria literal a MySQL, que
	# lo colapsa a `%` y devuelve la cadena «%Y-%m-01» en vez de una fecha. `YEAR` y
	# `MONTH` no tienen ese problema y el mes se arma en Python.
	fila = frappe.db.sql(
		"""
		SELECT company, YEAR(posting_date) AS anio, MONTH(posting_date) AS mes,
		       COUNT(*) AS n
		FROM `tabSales Invoice`
		WHERE docstatus = 1
		GROUP BY company, anio, mes
		ORDER BY n DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if not fila or not fila[0].n:
		return None
	c = fila[0].company
	d1 = f"{int(fila[0].anio):04d}-{int(fila[0].mes):02d}-01"
	d2 = frappe.utils.get_last_day(d1)

	arbol = frappe.db.sql(
		"SELECT name, lft, rgt, parent_ve_branch FROM `tabVE Branch` ORDER BY lft",
		as_dict=True,
	)
	con_facturas = dict(
		frappe.db.sql(
			"""SELECT branch, COUNT(*) FROM `tabSales Invoice`
			   WHERE docstatus = 1 AND company = %(c)s
			     AND posting_date BETWEEN %(d1)s AND %(d2)s
			   GROUP BY branch""",
			{"c": c, "d1": d1, "d2": d2},
		)
	)

	def subarbol(n):
		b = next(x for x in arbol if x.name == n)
		return [x.name for x in arbol if b.lft <= x.lft and x.rgt <= b.rgt]

	hoja = next((b.name for b in arbol
	             if b.rgt - b.lft == 1 and con_facturas.get(b.name)), None)
	# Una GRUPO cuyo subárbol tenga facturas: es la que ejercita el rollup.
	grupo = next((b.name for b in arbol
	              if b.rgt - b.lft > 1
	              and sum(con_facturas.get(x, 0) for x in subarbol(b.name))), None)
	raices = {b.name for b in arbol if not b.parent_ve_branch}
	principal = next((b.name for b in arbol if b.parent_ve_branch in raices
	                  and sum(con_facturas.get(x, 0) for x in subarbol(b.name))), None)

	return {"company": c, "from_date": str(d1), "to_date": str(d2),
	        "hoja": hoja, "grupo": grupo, "principal": principal}


class TestLosDosDanElMISMO_Numero(unittest.TestCase):
	"""El cruce de verdad, contra la base."""

	@classmethod
	def setUpClass(cls):
		cls.esc = _escenario()

	def setUp(self):
		if not self.esc:
			self.skipTest("el sitio no tiene facturas emitidas: nada que cruzar")

	def _casos(self) -> list:
		e = self.esc
		base = {"company": e["company"], "from_date": e["from_date"], "to_date": e["to_date"]}
		casos = [("sin filtro de sucursal", base)]
		if e["hoja"]:
			casos.append((f"sucursal HOJA ({e['hoja']})", {**base, "branch": e["hoja"]}))
		if e["grupo"]:
			casos.append((f"sucursal GRUPO ({e['grupo']})", {**base, "branch": e["grupo"]}))
		if e["principal"]:
			casos.append((f"principal ({e['principal']})", {**base, "main_branch": e["principal"]}))
		if e["grupo"] and e["principal"]:
			casos.append(("grupo + principal",
			              {**base, "branch": e["grupo"], "main_branch": e["principal"]}))
		return casos

	def test_las_tarjetas_del_resumen_son_IDENTICAS(self):
		"""Las 12, no solo el gran total: una sola que difiera ya es una declaración mal."""
		for etiqueta, filtros in self._casos():
			with self.subTest(caso=etiqueta):
				_, _, _, _, a = libro.execute(dict(filtros))
				_, _, _, _, b = hq.execute(dict(filtros))
				self.assertEqual([x["label"] for x in a], [x["label"] for x in b])
				for x, y in zip(a, b):
					self.assertAlmostEqual(
						frappe.utils.flt(x["value"]), frappe.utils.flt(y["value"]),
						places=2, msg=f"«{x['label']}» difiere en «{etiqueta}»")

	def test_traen_las_MISMAS_filas_con_los_MISMOS_valores(self):
		"""No alcanza con que el total coincida: dos errores que se compensan lo harían.

		Se comparan los campos que los dos comparten, como multiconjunto ordenado, así
		que un cambio de orden no lo hace fallar pero un valor distinto sí.
		"""
		comunes = [c["fieldname"] for c in libro.get_columns() if c.get("fieldname")]
		for etiqueta, filtros in self._casos():
			with self.subTest(caso=etiqueta):
				lb_main, _ = libro.get_sales_data(dict(filtros))
				hq_main = hq.get_hq_data(dict(filtros))["main_data"]
				self.assertEqual(len(lb_main), len(hq_main),
				                 f"distinta cantidad de filas en «{etiqueta}»")

				def huella(filas):
					return sorted(tuple(str(f.get(k)) for k in comunes) for f in filas)

				self.assertEqual(huella(lb_main), huella(hq_main),
				                 f"alguna fila trae valores distintos en «{etiqueta}»")

	def test_las_columnas_propias_del_HQ_CUADRAN_con_el_resumen(self):
		"""«Base Imponible Total» y «Monto IVA Total» son lo único que el HQ calcula.

		Se derivan sumando las alícuotas del libro, así que tienen que cerrar contra sus
		tarjetas. Si alguien las cambiara por una consulta propia, esto lo agarra.
		"""
		filtros = self._casos()[0][1]
		d = hq.get_hq_data(dict(filtros))
		vivas = [r for r in d["main_data"] if not r.get("is_void")]
		tarjetas = {x["label"]: frappe.utils.flt(x["value"]) for x in d["report_summary"]}

		iva = sum(frappe.utils.flt(r.get("total_vat")) for r in vivas)
		self.assertAlmostEqual(iva, tarjetas["Total IVA"], places=2)

		base = sum(frappe.utils.flt(r.get("taxable_amount")) for r in vivas)
		esperado = sum(tarjetas[k] for k in (
			"Base Imponible General", "Base Imponible Reducida", "Base Imponible Adicional"))
		self.assertAlmostEqual(base, esperado, places=2)
