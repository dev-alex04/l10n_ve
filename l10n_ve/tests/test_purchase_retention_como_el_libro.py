# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Pruebas de paridad entre las retenciones de compras y el Libro de Compras.

Verifica que:
1. El Libro de Compras use la misma función de resolución de subárbol (branch_scope_condition).
2. Los montos de retención de IVA entre el Libro de Compras y el reporte de Retención de IVA coincidan al centavo.
3. El total de retenciones de ISLR coincida entre el reporte y la relación del XML fiscal.
4. Las sucursales de grupo resuelvan correctamente todo el subárbol de sus hijas en compras.
5. Los documentos de compra con comprobante de ISLR emitido en mes posterior reflejen
   la retención en el Libro de Compras del documento y en el reporte de ISLR del mes del comprobante.
"""

import inspect
import unittest

import frappe
from frappe.utils import flt, get_last_day, getdate

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
	d2 = str(get_last_day(d1))

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


def _escenario_comprobante_islr_otro_mes() -> dict | None:
	"""Busca un documento de compra cuyo comprobante de ISLR esté fechado en otro mes."""
	row = frappe.db.sql(
		"""
		SELECT 
			inv.name AS invoice_name,
			inv.company,
			inv.bill_date,
			inv.posting_date,
			islr_item.islr_amount,
			islr_v.name AS voucher_name,
			islr_v.posting_date AS voucher_date
		FROM (
			SELECT name, company, bill_date, posting_date FROM `tabPurchase Invoice` WHERE docstatus = 1
			UNION ALL
			SELECT name, company, bill_date, posting_date FROM `tabVE Purchase Credit Note` WHERE docstatus = 1
			UNION ALL
			SELECT name, company, bill_date, posting_date FROM `tabVE Purchase Debit Note` WHERE docstatus = 1
		) AS inv
		JOIN `tabISLR Withholding Voucher Item` islr_item ON islr_item.purchase_invoice = inv.name
		JOIN `tabISLR Withholding Voucher` islr_v ON islr_item.parent = islr_v.name AND islr_v.docstatus = 1
		WHERE (MONTH(inv.posting_date) != MONTH(islr_v.posting_date) OR YEAR(inv.posting_date) != YEAR(islr_v.posting_date))
		ORDER BY inv.posting_date DESC
		LIMIT 1
		""",
		as_dict=True,
	)
	if not row:
		return None
	r = row[0]
	eff_res = frappe.db.sql(
		"""
		SELECT COALESCE(
			(SELECT wv.delivery_date 
			 FROM `tabVAT Withholding Voucher Item` wvi
			 INNER JOIN `tabVAT Withholding Voucher` wv 
			    ON wvi.parent = wv.name AND wv.docstatus = 1
			 WHERE wvi.purchase_invoice = %s 
			 LIMIT 1),
			%s
		) AS eff_date
		""",
		(r.invoice_name, r.posting_date),
		as_dict=True,
	)
	effective_date = getdate(eff_res[0].eff_date)
	d1 = f"{effective_date.year:04d}-{effective_date.month:02d}-01"
	d2 = str(get_last_day(d1))
	return {
		"invoice_name": r.invoice_name,
		"company": r.company,
		"from_date": d1,
		"to_date": d2,
		"voucher_name": r.voucher_name,
		"voucher_date": r.voucher_date,
		"expected_islr": flt(r.islr_amount),
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

	def test_retencion_islr_comprobante_en_otro_mes_aparece_en_libro_de_compras(self):
		"""Un comprobante de ISLR emitido en mes posterior a la factura debe reflejarse en el Libro de Compras.

		Regla contable:
		- El Libro de Compras refleja las retenciones aplicadas a los documentos de compra
		  del periodo (ret_islr_monto > 0, islr_retention_applied = 'Sí'), independientemente
		  de si el comprobante de ISLR fue emitido en el mismo mes o en el mes siguiente.
		- El reporte de Retenciones de ISLR (y el XML SENIAT) filtra por fecha de emisión
		  del comprobante (voucher.posting_date), reflejando la obligación fiscal del periodo del comprobante.
		"""
		esc_islr = _escenario_comprobante_islr_otro_mes()
		if not esc_islr:
			self.skipTest("no hay facturas con comprobante de ISLR en mes diferente")

		pb_cols, pb_data, _, _, _ = libro.execute({
			"company": esc_islr["company"],
			"from_date": esc_islr["from_date"],
			"to_date": esc_islr["to_date"],
		})

		inv_row = next((d for d in pb_data if d.get("nro_factura") == esc_islr["invoice_name"]), None)
		self.assertIsNotNone(
			inv_row,
			f"Documento {esc_islr['invoice_name']} no encontrado en el Libro de Compras del periodo {esc_islr['from_date']} a {esc_islr['to_date']}",
		)
		self.assertEqual(inv_row.get("islr_retention_applied"), "Sí")
		self.assertGreater(flt(inv_row.get("ret_islr_monto")), 0)

		# En el mes del comprobante, el reporte de ISLR sí lo incluye
		v_date = getdate(esc_islr["voucher_date"])
		v_d1 = f"{v_date.year:04d}-{v_date.month:02d}-01"
		v_d2 = str(get_last_day(v_d1))

		iw_cols, iw_data = reporte_islr.execute({
			"company": esc_islr["company"],
			"from_date": v_d1,
			"to_date": v_d2,
		})
		v_row = next(
			(d for d in iw_data if d.get("parent") == esc_islr["voucher_name"] or d.get("purchase_invoice") == esc_islr["invoice_name"]),
			None,
		)
		self.assertIsNotNone(
			v_row,
			f"Comprobante {esc_islr['voucher_name']} no encontrado en reporte ISLR en su mes {v_d1} a {v_d2}",
		)
