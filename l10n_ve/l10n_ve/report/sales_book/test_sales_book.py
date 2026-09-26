"""La base del Libro es la base REAL de la factura, y base + IVA = total.

Hasta este cambio, la base por alícuota del cálculo nuevo se reconstruía desde el
impuesto (``base_tax_amount * 100/tasa``). El IVA guardado tiene 2 decimales y el
×6,25 amplificaba su redondeo: hasta ±0,031 por factura. Medido sobre agosto-2026,
la identidad ``base + IVA + exento = total`` estaba rota en **5.992 filas de 6.199**
--céntimos cada una, Bs. +17,85 en el filtro MIR-01-- y con la base real queda rota
en 2: las de la brecha PREEXISTENTE de tasa 0%, que es otro problema (el neto de un
documento con IVA a 0% no entra a ninguna base ni al exento).

La reconstrucción queda solo como fallback multi-alícuota. Medido: cero facturas
multi-alícuota en todo el histórico, contando TODAS las tasas --incluidas las de 0 por
ciento, que es la parte que hay que contar bien: filtrarlas por monto distinto de cero
las vuelve invisibles y una factura mixta 16/0 entraría por la rama equivocada--.
"""

import inspect
import re
import unittest

import frappe
from frappe.utils import flt

from l10n_ve.l10n_ve.report.sales_book import sales_book as sb

BASES = ("base_general_taxpayer", "base_general_non_taxpayer",
         "base_reduced_taxpayer", "base_reduced_non_taxpayer",
         "base_additional_taxpayer", "base_additional_non_taxpayer")
IVAS = ("iva_general_taxpayer", "iva_general_non_taxpayer",
        "iva_reduced_taxpayer", "iva_reduced_non_taxpayer",
        "iva_additional_taxpayer", "iva_additional_non_taxpayer")


class TestLasDosRamasDelUnionSiguenAlineadas(unittest.TestCase):
	"""Un UNION ALL exige la MISMA lista de columnas en las dos ramas.

	Desalinearlo no falla al escribirlo: falla en runtime, en un reporte fiscal,
	cuando alguien lo corre.
	"""

	def _alias(self, texto: str) -> list:
		return re.findall(r"\bAS\s+(\w+)", texto)

	def test_mismas_columnas_en_el_mismo_orden(self):
		self.assertEqual(
			self._alias(sb._get_legacy_calc_columns()),
			self._alias(sb._get_new_calc_columns()),
		)


class TestLaBaseEsLaRealDeLaFactura(unittest.TestCase):
	"""Estructural: el cálculo nuevo usa el neto del documento, no una derivada."""

	def test_las_seis_columnas_salen_del_generador(self):
		"""Si alguien reescribe UNA a mano, las reglas se separan sin que se note."""
		f = sb._get_new_calc_columns()
		for alias in BASES:
			with self.subTest(columna=alias):
				# La marca del camino real: el neto menos el exento, no el impuesto.
				i = f.index(f"AS {alias}")
				bloque = f[max(0, i - 1400):i]
				self.assertIn("COALESCE(MAX(siv.base_net_total), 0)", bloque)
				self.assertIn("COALESCE(MAX(siv.base_total_exempt), 0)", bloque)

	def test_la_tasa_UNICA_cuenta_tambien_las_lineas_al_CERO_por_ciento(self):
		"""Salió de la revisión del PR, y el modo de fallar es silencioso.

		Filtrar el conteo por ``base_tax_amount <> 0`` es lo natural de escribir --una
		línea al 0 por ciento aporta impuesto cero-- pero las vuelve INVISIBLES: una
		factura que mezcle 16 por ciento con 0 por ciento contaría UNA sola tasa,
		entraría por la rama de base real y le asignaría a la columna del 16 por ciento
		también el neto de las líneas al 0, declarando como gravado algo que no lo está.

		Contando todas, esa factura da dos tasas y cae al fallback, que reconstruye
		desde el impuesto y por construcción deja fuera lo que no tributa.

		Hoy no existe ninguna factura mixta --cero en las tres tablas, contando TODAS
		las tasas-- así que ningún test contra la base puede ejercitarlo. Por eso se
		verifica el predicado en el SQL, que es donde vive la decisión.
		"""
		f = sb._get_new_calc_columns()
		i = f.index("COUNT(DISTINCT CASE WHEN tstac.charge_type = 'VAT'")
		predicado = f[i:f.index("THEN tstac.rate END) = 1", i)]
		self.assertNotIn("base_tax_amount", predicado)

	#: El MISMO universo que el CTE del reporte. Sin esto el test miraba TODAS las
	#: filas de ``Sales Taxes and Charges``, incluidas las de 3.100 documentos que
	#: nunca llegan al libro --borradores y cancelados sin anular--: cualquiera de
	#: ellos ganando una segunda tasa habría tumbado el test sin que al reporte le
	#: importara, justo lo contrario de lo que su docstring promete.
	DOCS_DEL_REPORTE: str = "(d.docstatus = 1 OR (d.docstatus = 2 AND d.is_void = 1))"

	#: Doctype -> tabla, para poder unir contra el documento. Es la MISMA lista que
	#: el CTE une en su UNION.
	TABLAS: dict = {
		"Sales Invoice": "tabSales Invoice",
		"VE Sales Credit Note": "tabVE Sales Credit Note",
		"VE Sales Debit Note": "tabVE Sales Debit Note",
	}

	def test_el_universo_medido_es_el_MISMO_que_el_del_reporte(self):
		"""Dos relojes es peor que uno: si el CTE cambia su criterio, el de abajo
		queda midiendo otra cosa y nadie se entera. Se falla acá primero.
		"""
		cte = sb._get_cte()
		for alias in ("siv", "nc", "nd"):
			with self.subTest(rama=alias):
				self.assertIn(
					self.DOCS_DEL_REPORTE.replace("d.", f"{alias}."), cte)

	def test_hoy_NO_hay_ninguna_factura_con_dos_tasas(self):
		"""La medición que justifica que la rama de base real sea la normal.

		Se cuenta sobre TODAS las tasas --sin filtrar por monto-- porque contarlas
		filtradas es justamente el error que el test de arriba previene: daría cero
		mixtas aunque las hubiera.

		Y solo sobre los documentos que ENTRAN al libro: un borrador con dos tasas no
		le importa al reporte, y hacerlo fallar por eso sería una señal falsa.

		Si algún día esto falla, no es que el código esté mal: es que apareció el caso
		que el fallback existe para cubrir, y conviene ir a mirarlo.
		"""
		for parenttype, tabla in self.TABLAS.items():
			with self.subTest(doctype=parenttype):
				n = frappe.db.sql(
					f"""SELECT COUNT(*) FROM (
					      SELECT t.parent
					      FROM `tabSales Taxes and Charges` t
					      JOIN `{tabla}` d ON d.name = t.parent
					      WHERE t.charge_type = 'VAT' AND t.parenttype = %s
					        AND {self.DOCS_DEL_REPORTE}
					      GROUP BY t.parent HAVING COUNT(DISTINCT t.rate) > 1
					    ) x""",
					parenttype,
				)[0][0]
				self.assertEqual(n, 0)

	def test_el_fallback_multialicuota_sigue_vivo(self):
		"""Cero casos hoy, pero si aparece uno, reconstruir es la única forma de
		partir el neto por tasa. Quitar el fallback rompería justo ese día.
		"""
		f = sb._get_new_calc_columns()
		self.assertIn("COUNT(DISTINCT CASE WHEN tstac.charge_type = 'VAT'", f)
		self.assertEqual(f.count("* (100.0 / %("), 6)

	def test_la_rama_LEGACY_no_se_toca(self):
		"""Son períodos YA DECLARADOS: cambiarles la base ahora es reescribir una
		declaración entregada. La reconstrucción se queda ahí a propósito.
		"""
		# El SQL devuelto, no el fuente: el docstring nombra `base_net_total`
		# justamente para decir que NO lo usa, y un assertNotIn sobre el fuente
		# fallaria por la mencion.
		f = sb._get_legacy_calc_columns()
		self.assertNotIn("base_net_total", f)
		self.assertNotIn("COUNT(DISTINCT", f)


def _mes_post_corte() -> dict | None:
	"""El mes con más facturas DESPUÉS del corte fiscal, o ``None`` para saltar."""
	fila = frappe.db.sql(
		"""
		SELECT company, YEAR(posting_date) AS anio, MONTH(posting_date) AS mes,
		       COUNT(*) AS n
		FROM `tabSales Invoice`
		WHERE docstatus = 1 AND posting_date > %(corte)s
		GROUP BY company, anio, mes
		ORDER BY n DESC
		LIMIT 1
		""",
		{"corte": sb._FISCAL_CUTOFF_DATE},
		as_dict=True,
	)
	if not fila or not fila[0].n:
		return None
	d1 = f"{int(fila[0].anio):04d}-{int(fila[0].mes):02d}-01"
	return {"company": fila[0].company, "from_date": d1,
	        "to_date": str(frappe.utils.get_last_day(d1))}


class TestBaseMasIvaDaElTotal(unittest.TestCase):
	"""La identidad, contra la base y FILA POR FILA — el total puede cerrar por
	compensación aunque las filas estén mal (pasó: la factura a tasa 0% y su
	devolución se cancelan)."""

	@classmethod
	def setUpClass(cls):
		cls.f = _mes_post_corte()

	def setUp(self):
		if not self.f:
			self.skipTest("sin facturas después del corte fiscal: nada que verificar")
		if not hasattr(type(self), "_main"):
			type(self)._main, _ = sb.get_sales_data(dict(self.f))

	def _vivas_con_iva(self):
		"""Las filas donde la identidad DEBE dar. Quedan fuera las de tasa 0% --su
		neto no entra a ninguna base ni al exento; brecha PREEXISTENTE y aparte--.
		"""
		for r in self._main:
			if r.get("is_void"):
				continue
			if not any(flt(r.get(k)) for k in IVAS):
				continue
			yield r

	def test_cada_fila_cierra_al_centimo(self):
		peor, rotas, n = 0.0, 0, 0
		for r in self._vivas_con_iva():
			n += 1
			d = abs(sum(flt(r.get(k)) for k in BASES) + sum(flt(r.get(k)) for k in IVAS)
			        + flt(r.get("total_exempt")) - flt(r.get("grand_total")))
			peor = max(peor, d)
			rotas += d > 0.005
		if not n:
			# Mismo criterio que el setUp: hay facturas, pero ninguna viva con IVA.
			self.skipTest("sin facturas con IVA después del corte fiscal: nada que verificar")
		self.assertEqual(rotas, 0, f"{rotas} filas rotas; peor residuo {peor:.4f}")

	def test_la_base_por_su_tasa_da_el_IVA_dentro_del_redondeo(self):
		"""Con la base real, ``base × 16%`` cae a medio céntimo del IVA guardado.
		La reconstrucción daba esto EXACTO a costa de falsear la base; ahora la base
		es la del documento y la diferencia es el redondeo normal del impuesto.
		"""
		# La misma fuente y el mismo fallback que usa `get_sales_data`.
		try:
			tasa = flt(frappe.get_cached_doc("Taxes Rates", "Taxes Rates")
			           .get("general_rate")) or 16.0
		except Exception:
			tasa = 16.0
		rotas = 0
		for r in self._vivas_con_iva():
			base = flt(r.get("base_general_taxpayer")) + flt(r.get("base_general_non_taxpayer"))
			iva = flt(r.get("iva_general_taxpayer")) + flt(r.get("iva_general_non_taxpayer"))
			if not base:
				continue
			rotas += abs(base * tasa / 100.0 - iva) > 0.011
		self.assertEqual(rotas, 0)

	def test_el_total_del_libro_cierra(self):
		t = sb.get_total_row(self._main)
		suma = (sum(flt(t.get(k)) for k in BASES) + sum(flt(t.get(k)) for k in IVAS)
		        + flt(t.get("total_exempt")))
		self.assertAlmostEqual(suma, flt(t.get("grand_total")), places=1)
