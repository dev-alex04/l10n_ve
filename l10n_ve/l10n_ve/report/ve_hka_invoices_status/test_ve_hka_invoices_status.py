import unittest
from unittest.mock import patch

import frappe

from l10n_ve.l10n_ve.report.ve_hka_invoices_status import ve_hka_invoices_status as report


class TestPermisosDelReporte(unittest.TestCase):
	"""En «Todos», un doctype sin lectura se omite; si no hay ninguno, el reporte se niega."""

	def _execute(self, permitidos):
		def has_permission(doctype, ptype="read", doc=None, user=None, throw=False, **kwargs):
			return doctype == "Company" or doctype in permitidos

		with (
			patch("frappe.has_permission", side_effect=has_permission),
			patch.object(report.frappe.db, "sql", return_value=[]) as sql,
			patch.object(report.frappe.db, "has_column", return_value=True),
		):
			return report.execute({"company": "Empresa", "document_type": "Todos"}), sql

	def test_sin_permiso_sobre_ningun_doctype_el_reporte_se_niega(self):
		with self.assertRaises(frappe.PermissionError):
			self._execute(set())

	def test_con_permiso_sobre_uno_solo_consulta_solo_ese(self):
		_, sql = self._execute({"VAT Withholding Voucher"})
		consulta = sql.call_args.args[0]
		self.assertIn("tabVAT Withholding Voucher", consulta)
		self.assertNotIn("tabSales Invoice", consulta)

	def test_lista_vacia_de_permitidos_no_vuelve_a_todos(self):
		"""get_data no reinterpreta `[]` como «sin filtro»."""
		with patch.object(report.frappe.db, "sql") as sql:
			self.assertEqual(report.get_data({"company": "Empresa", "_allowed_doctypes": []}), [])
		sql.assert_not_called()
