# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Pruebas de las mejoras en los reportes de retenciones de compra:
- Columnas de sucursal, tasa BCV y montos en USD.
- Filtros multi-sucursal y exclusión.
- Prevención de duplicados por códigos de tabulador ISLR (fan-out bug).
"""

import unittest
import frappe
from frappe.utils import flt

from l10n_ve.l10n_ve.report.vat_withholding import vat_withholding as reporte_iva
from l10n_ve.l10n_ve.report.islr_withholding import islr_withholding as reporte_islr
from l10n_ve.tests.test_purchase_retention_como_el_libro import _escenario_compras


class TestPurchaseWithholdingImprovements(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.esc = _escenario_compras()

	def setUp(self):
		if not self.esc:
			self.skipTest("el sitio no tiene datos para el reporte de retenciones de compras")
		self.company = self.esc["company"]
		self.filters = {
			"company": self.company,
			"from_date": self.esc["from_date"],
			"to_date": self.esc["to_date"],
		}

	def test_columnas_requeridas_retencion_iva(self):
		"""Verifica que las columnas de IVA incluyan branch, bcv_rate y tax_amount_vat_usd."""
		columns = reporte_iva.get_columns()
		fieldnames = [c["fieldname"] for c in columns]
		self.assertIn("branch", fieldnames)
		self.assertIn("bcv_rate", fieldnames)
		self.assertIn("tax_amount_vat_usd", fieldnames)

	def test_columnas_requeridas_retencion_islr(self):
		"""Verifica que las columnas de ISLR incluyan branch, bcv_rate e islr_amount_usd."""
		columns = reporte_islr.get_columns({"group_by": "Detalle"})
		fieldnames = [c["fieldname"] for c in columns]
		self.assertIn("branch", fieldnames)
		self.assertIn("bcv_rate", fieldnames)
		self.assertIn("islr_amount_usd", fieldnames)

	def test_multi_sucursal_y_exclusion_iva(self):
		"""Prueba selección múltiple de sucursales y la opción de exclusión en IVA."""
		branch = self.esc.get("hoja")
		if not branch:
			self.skipTest("no hay una sucursal hoja en el escenario")

		f_single = {**self.filters, "branch": [branch]}
		res_single = reporte_iva.get_data(f_single)
		self.assertTrue(all(r["branch"] == branch for r in res_single if r.get("branch")))

		f_exclude = {**self.filters, "branch": [branch], "exclude_branches": 1}
		res_exclude = reporte_iva.get_data(f_exclude)
		self.assertTrue(all(r["branch"] != branch for r in res_exclude if r.get("branch")))

	def test_tabulador_islr_sin_duplicados_fan_out(self):
		"""Verifica que un código de tabulador con múltiples descripciones no duplique registros."""
		# Forzar o probar con el código 005 si existe en tabulador
		data = reporte_islr.get_data({**self.filters, "group_by": "Detalle"})
		# Cada item de comprobante (parent + doc_no + concept_code) no debe aparecer repetido
		claves = []
		for r in data:
			claves.append((r.get("parent"), r.get("doc_no"), r.get("concept_code"), r.get("islr_amount")))
		self.assertEqual(len(claves), len(set(claves)), "Se encontraron filas duplicadas en el reporte de ISLR")
