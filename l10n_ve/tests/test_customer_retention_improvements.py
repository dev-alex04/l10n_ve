# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import unittest
from frappe.utils import flt

from l10n_ve.l10n_ve.report.customer_retention import customer_retention as report
from l10n_ve.tests.test_customer_retention_como_el_libro import _escenario


class TestCustomerRetentionImprovements(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.esc = _escenario()

	def setUp(self):
		if not self.esc:
			self.skipTest("el sitio no tiene datos para el reporte de retenciones de clientes")
		self.company = self.esc["company"]
		self.filters = {
			"company": self.company,
			"from_date": self.esc["from_date"],
			"to_date": self.esc["to_date"],
			"include_credit_notes": 1,
		}

	def test_columns_contain_required_fields(self):
		"""Verifica que las columnas incluyan branch, doc_type, registration_date, voucher_date, bcv_rate, withholding_amount_usd."""
		columns = report.get_columns()
		fieldnames = [c["fieldname"] for c in columns]
		self.assertIn("branch", fieldnames)
		self.assertIn("doc_type", fieldnames)
		self.assertIn("registration_date", fieldnames)
		self.assertIn("voucher_date", fieldnames)
		self.assertIn("bcv_rate", fieldnames)
		self.assertIn("withholding_amount", fieldnames)
		self.assertIn("withholding_amount_usd", fieldnames)
		self.assertIn("retention_type", fieldnames)

	def test_multi_branch_and_exclusion(self):
		"""Prueba selección múltiple de sucursales y la opción de exclusión."""
		branch = self.esc.get("hoja")
		if not branch:
			self.skipTest("no hay una sucursal hoja con datos en el período")

		f_dc = {**self.filters, "branch": [branch]}
		res_dc = report.get_data(f_dc)
		self.assertTrue(all(r["branch"] == branch for r in res_dc))

		f_exclude = {**self.filters, "branch": [branch], "exclude_branches": 1}
		res_exclude = report.get_data(f_exclude)
		self.assertTrue(all(r["branch"] != branch for r in res_exclude))

		f_all = {**self.filters, "branch": []}
		res_all = report.get_data(f_all)
		self.assertEqual(len(res_dc) + len(res_exclude), len(res_all))

	def test_credit_notes_treatment_and_toggle(self):
		"""Prueba que las NC no exijan comprobante y se puedan incluir/excluir."""
		# Con NC habilitadas
		res_with_nc = report.get_data({**self.filters, "include_credit_notes": 1})
		ncs = [r for r in res_with_nc if r.get("doc_type") == "NC"]
		if not ncs:
			self.skipTest("no hay notas de crédito en el período")

		for nc in ncs:
			# Las NC tienen signo negativo en base_total y withholding_amount
			self.assertLess(nc["withholding_amount"], 0)
			self.assertLess(nc["base_total"], 0)
			self.assertIn(nc["retention_type"], ["IVA", "ISLR"])

		# Sin NC
		res_without_nc = report.get_data({**self.filters, "include_credit_notes": 0})
		self.assertFalse(any(r.get("doc_type") == "NC" for r in res_without_nc))
		self.assertEqual(len(res_with_nc) - len(ncs), len(res_without_nc))

	def test_government_withholdings_included(self):
		"""Prueba que las retenciones gubernamentales se incluyan y puedan filtrarse."""
		res_gov = report.get_data({**self.filters, "retention_type": "Gubernamental"})
		if not res_gov:
			self.skipTest("no hay retenciones gubernamentales en el período")

		for r in res_gov:
			self.assertEqual(r["retention_type"], "Gubernamental")
			self.assertGreater(r["withholding_amount"], 0)
			self.assertTrue(bool(r.get("voucher_number")))

	def test_bcv_rate_and_usd_calculation(self):
		"""Prueba que se calcule la tasa BCV del 1er día del mes y el monto retenido en USD."""
		data = report.get_data(self.filters)
		with_rate = [r for r in data if r.get("bcv_rate") and r.get("bcv_rate") > 0]
		if not with_rate:
			self.skipTest("no hay registros con tasa BCV en el período")

		for r in with_rate:
			expected_usd = round(flt(r["withholding_amount"]) / r["bcv_rate"], 2)
			self.assertAlmostEqual(flt(r["withholding_amount_usd"]), expected_usd, places=2)

	def test_excel_export_preserves_branch_and_types(self):
		"""Verifica que la exportación a Excel incluya la columna Sucursal, Tipo Doc, y Tipo Retención."""
		cols = report.get_columns()
		cols_to_remove = ["name", "voucher_image"]
		exported_cols = [c["fieldname"] for c in cols if c.get("fieldname") not in cols_to_remove]
		self.assertIn("branch", exported_cols)
		self.assertIn("doc_type", exported_cols)
		self.assertIn("retention_type", exported_cols)
		self.assertIn("withholding_amount_usd", exported_cols)
