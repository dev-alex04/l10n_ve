# -*- coding: utf-8 -*-
# Copyright (c) 2026, Alexander and Contributors
# See license.txt

import frappe
import json
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch, MagicMock
from l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download import (
	VEFiscalDocumentDownload,
	get_invoice_count,
	process_download_job
)

class TestVEFiscalDocumentDownload(FrappeTestCase):
	def test_validation_date_order(self):
		"""Throws validation error when from_date is after to_date."""
		doc = frappe.new_doc("VE Fiscal Document Download")
		doc.from_date = "2026-06-15"
		doc.to_date = "2026-06-10"
		self.assertRaises(frappe.ValidationError, doc.validate)

	def test_get_invoice_count(self):
		"""Correctly counts invoices containing HKA remarks."""
		with patch("frappe.get_all") as mock_get_all:
			mock_get_all.return_value = [
				{"name": "INV-1", "remarks": '{"resultado": {"numeroDocumento": "100"}}'},
				{"name": "INV-2", "remarks": "Simulado HKA sin numeroDocumento"},
				{"name": "INV-3", "remarks": '{"resultado": {"numeroDocumento": "101"}}'},
			]
			count = get_invoice_count("2026-06-01", "2026-06-10")
			self.assertEqual(count, 2)

	@patch("l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.save_file")
	@patch("frappe.publish_realtime")
	@patch("frappe.get_doc")
	def test_process_download_job(self, mock_get_doc, mock_publish, mock_save_file):
		"""Successfully runs bulk download job and generates a ZIP attachment."""
		# Create a real test document in DB before patching get_all
		doc = frappe.get_doc({
			"doctype": "VE Fiscal Document Download",
			"from_date": "2026-06-01",
			"to_date": "2026-06-10",
			"customer": None
		})
		doc.insert()

		# Setup side effect for get_doc to mock File reading
		def get_doc_side_effect(doctype, *args, **kwargs):
			if doctype == "File":
				mock_file = MagicMock()
				mock_file.get_content.return_value = b"dummy pdf content"
				return mock_file
			# Return the actual document if it's VE Fiscal Document Download
			if doctype == "VE Fiscal Document Download":
				return doc
			return frappe.get_doc(doctype, *args, **kwargs)
		
		mock_get_doc.side_effect = get_doc_side_effect

		with patch("frappe.get_all") as mock_get_all:
			# Setup mock get_all for Sales Invoice and File doctypes
			def get_all_side_effect(doctype, *args, **kwargs):
				if doctype == "Sales Invoice":
					return [
						{"name": "INV-1", "remarks": '{"resultado": {"numeroDocumento": "100"}}', "bill_no": "100"},
						{"name": "INV-2", "remarks": '{"resultado": {"numeroDocumento": "200"}, "Simulado": true}', "bill_no": "200"},
					]
				elif doctype == "File":
					return [{"name": "mock-file-1", "file_name": "Factura_INV-1_100.pdf"}]
				return []
			mock_get_all.side_effect = get_all_side_effect

			# Setup mock file attachment save
			mock_file_doc = MagicMock()
			mock_file_doc.file_url = "/files/Facturas_HKA_2026-06-01_a_2026-06-10.zip"
			mock_save_file.return_value = mock_file_doc

			# Run the job
			process_download_job(doc.name, "Administrator")

		# Reload document from database
		doc.reload()

		# Verify document saves and updates
		self.assertEqual(doc.downloaded_count, 2)
		self.assertEqual(doc.status, "Completed")
		self.assertTrue("Descargar" in doc.files_html)
		mock_publish.assert_called_with(
			"hka_download_completed",
			{"docname": doc.name, "status": "Completed"},
			user="Administrator"
		)

	def test_get_invoice_count_with_branch(self):
		"""Correctly counts invoices filtering by branch."""
		with patch("frappe.get_all") as mock_get_all:
			def get_all_side_effect(doctype, *args, **kwargs):
				filters = kwargs.get("filters", {})
				if filters.get("branch") == "Sucursal Principal":
					return [
						{"name": "INV-1", "remarks": '{"resultado": {"numeroDocumento": "100"}}'},
					]
				return [
					{"name": "INV-1", "remarks": '{"resultado": {"numeroDocumento": "100"}}'},
					{"name": "INV-2", "remarks": '{"resultado": {"numeroDocumento": "101"}}'},
				]
			mock_get_all.side_effect = get_all_side_effect
			
			# Test filtering by branch
			count = get_invoice_count("2026-06-01", "2026-06-10", branch="Sucursal Principal")
			self.assertEqual(count, 1)

			# Test without branch
			count_no_branch = get_invoice_count("2026-06-01", "2026-06-10")
			self.assertEqual(count_no_branch, 2)

	@patch("frappe.publish_realtime")
	def test_process_download_job_max_limit_exceeded(self, mock_publish):
		"""Fails download job when max limit of 2000 invoices is exceeded."""
		doc = frappe.get_doc({
			"doctype": "VE Fiscal Document Download",
			"from_date": "2026-06-01",
			"to_date": "2026-06-10",
			"customer": None
		})
		doc.insert()

		with patch("frappe.get_all") as mock_get_all:
			# Mock 2001 invoices
			mock_get_all.return_value = [
				{"name": f"INV-{i}", "remarks": '{"resultado": {"numeroDocumento": "100"}}', "bill_no": str(i)}
				for i in range(2001)
			]

			# Run the job
			process_download_job(doc.name, "Administrator")

		doc.reload()
		self.assertEqual(doc.status, "Failed")
		self.assertTrue("Por seguridad, el límite máximo permitido es de 2000 facturas" in doc.error_log)


def run_local_tests():
	import unittest
	suite = unittest.TestLoader().loadTestsFromTestCase(TestVEFiscalDocumentDownload)
	runner = unittest.TextTestRunner(verbosity=2)
	runner.run(suite)
