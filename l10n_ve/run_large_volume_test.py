import frappe
from unittest.mock import patch, MagicMock
import base64
import sys
import traceback

# Define the proposed functions locally to test them
def get_invoice_count_proposed(from_date, to_date, customer=None, branch=None):
	filters = {
		"docstatus": 1,
		"posting_date": ["between", [from_date, to_date]],
	}
	if customer:
		filters["customer"] = customer
	if branch:
		filters["branch"] = branch

	invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks"])
	
	valid_count = 0
	for inv in invoices:
		remarks = inv.get("remarks")
		if remarks and '"numeroDocumento"' in remarks:
			valid_count += 1
			
	return valid_count

def run_debug():
	frappe.connect(site="api.local")
	frappe.db.begin()
	
	try:
		# Test 1: test_get_invoice_count
		with patch("frappe.get_all") as mock_get_all:
			mock_get_all.return_value = [
				{"name": "INV-1", "remarks": '{"resultado": {"numeroDocumento": "100"}}'},
				{"name": "INV-2", "remarks": "Simulado HKA sin numeroDocumento"},
				{"name": "INV-3", "remarks": '{"resultado": {"numeroDocumento": "101"}}'},
			]
			count = get_invoice_count_proposed("2026-06-01", "2026-06-10")
			print(f"Test 1 (get_invoice_count): count={count} (Expected: 2)")
			assert count == 2

		# Test 2: test_get_invoice_count_with_branch
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
			
			count = get_invoice_count_proposed("2026-06-01", "2026-06-10", branch="Sucursal Principal")
			print(f"Test 2 (get_invoice_count_with_branch): count={count} (Expected: 1)")
			assert count == 1

		# Test 3: process_download_job (large volume recursion test)
		from l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download import (
			process_download_job
		)
		
		doc = frappe.get_doc({
			"doctype": "VE Fiscal Document Download",
			"from_date": "2026-06-01",
			"to_date": "2026-06-10",
			"customer": None,
			"name": "TEST-DOWNLOAD-DOC"
		})

		# Mock get_doc
		mock_get_doc = MagicMock()
		def get_doc_side_effect(doctype, *args, **kwargs):
			if doctype == "File":
				mock_file = MagicMock()
				mock_file.get_content.return_value = b"dummy content"
				return mock_file
			if doctype == "VE Fiscal Document Download":
				return doc
			return frappe.get_doc(doctype, *args, **kwargs)
		mock_get_doc.side_effect = get_doc_side_effect

		mock_save_file = MagicMock()
		mock_file_doc = MagicMock()
		mock_file_doc.file_url = "/files/dummy.zip"
		mock_file_doc.file_size = 1000
		mock_save_file.return_value = mock_file_doc

		mock_publish = MagicMock()

		# Patch get_all
		mock_get_all = MagicMock()
		def get_all_side_effect(doctype, *args, **kwargs):
			if doctype == "Sales Invoice":
				return [
					{"name": f"INV-{i}", "remarks": '{"resultado": {"numeroDocumento": "100"}}', "bill_no": str(i)}
					for i in range(2005)
				]
			elif doctype == "File":
				return [{"name": f"mock-file-{i}", "file_name": f"Factura_INV-{i}_100.pdf", "attached_to_name": f"INV-{i}"} for i in range(10)]
			return []
		mock_get_all.side_effect = get_all_side_effect

		print("Starting large volume job execution...")
		with patch("frappe.get_doc", mock_get_doc), \
			 patch("l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.save_file", mock_save_file), \
			 patch("frappe.publish_realtime", mock_publish), \
			 patch("frappe.get_all", mock_get_all):

			with patch("l10n_ve.digital_invoice.tfhka_client.get_fiscal_invoice_pdf") as mock_get_pdf:
				mock_get_pdf.return_value = {"base64": "ZHVtbXk=", "numero_documento": "100"}
				
				doc.save = MagicMock()
				
				process_download_job(doc.name, "Administrator")

		print("\n--- RESULTS ---")
		print(f"Status: {doc.status}")
		print(f"Downloaded Count: {doc.downloaded_count}")
		print(f"Error Log: {doc.error_log}")

	except Exception as e:
		traceback.print_exc()
	finally:
		frappe.db.rollback()

if __name__ == "__main__":
	run_debug()
