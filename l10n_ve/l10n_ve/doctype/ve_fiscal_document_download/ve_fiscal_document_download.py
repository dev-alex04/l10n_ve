# -*- coding: utf-8 -*-
# Copyright (c) 2026, Alexander and Contributors
# For license information, please see license.txt

import frappe
import json
import zipfile
import io
import base64
import os
from frappe.model.document import Document
from frappe.utils.file_manager import save_file

class VEFiscalDocumentDownload(Document):
	def validate(self):
		if self.from_date and self.to_date:
			if self.from_date > self.to_date:
				frappe.throw(frappe._("La Fecha Desde no puede ser posterior a la Fecha Hasta."))

	@frappe.whitelist()
	def start_download(self):
		if self.status == "Processing":
			return False
		
		# Cambiar estado a Procesando y guardar
		self.status = "Processing"
		self.error_log = ""
		self.files_html = ""
		self.total_attempted = 0
		self.downloaded_count = 0
		self.save()
		frappe.db.commit()

		# Encolar el proceso en segundo plano
		frappe.enqueue(
			"l10n_ve.l10n_ve.doctype.ve_fiscal_document_download.ve_fiscal_document_download.process_download_job",
			queue="default",
			timeout=600,
			docname=self.name,
			request_user=frappe.session.user
		)
		return True


def process_download_job(docname: str, request_user: str):
	"""Trabajo en segundo plano para realizar la descarga masiva y adjuntar los ZIPs al documento."""
	try:
		doc = frappe.get_doc("VE Fiscal Document Download", docname)
		
		filters = {
			"docstatus": 1,
			"posting_date": ["between", [doc.from_date, doc.to_date]],
		}
		if doc.customer:
			filters["customer"] = doc.customer
		if doc.get("branch"):
			filters["branch"] = doc.branch

		invoices = frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks", "bill_no"])
		
		valid_invoices = []
		for inv in invoices:
			remarks = inv.get("remarks")
			if remarks and '"numeroDocumento"' in remarks:
				valid_invoices.append(inv)

		doc.total_attempted = len(valid_invoices)

		if not valid_invoices:
			doc.status = "Failed"
			doc.error_log = "No se encontraron facturas aprobadas por HKA en el rango seleccionado."
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Failed", request_user)
			return

		# Límite de seguridad síncrona para evitar abusos o bloqueos con HKA
		MAX_LIMIT = 500
		if len(valid_invoices) > MAX_LIMIT:
			doc.status = "Failed"
			doc.error_log = (
				f"El rango seleccionado contiene {len(valid_invoices)} facturas. "
				f"Por seguridad, el límite máximo permitido es de {MAX_LIMIT} facturas. "
				"Por favor, seleccione un rango de fechas más corto o filtre por un cliente o sucursal."
			)
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Failed", request_user)
			return

		MAX_SIZE_BYTES = int(4.5 * 1024 * 1024)  # 4.5 MB por ZIP
		files = []
		errors = []
		downloaded_count = 0

		zip_buffer = io.BytesIO()
		zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
		current_zip_count = 0
		part_number = 1

		# Master ZIP containing all PDFs without size splitting
		master_zip_buffer = io.BytesIO()
		master_zip_file = zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED)

		for idx, inv in enumerate(valid_invoices):
			try:
				inv_name = inv.get("name")
				inv_remarks = inv.get("remarks")
				inv_bill_no = inv.get("bill_no")

				pdf_data = None
				pdf_len = 0
				filename = ""

				# 1. Buscar archivo PDF adjunto localmente en Frappe
				attached_files = frappe.get_all(
					"File",
					filters={
						"attached_to_doctype": "Sales Invoice",
						"attached_to_name": inv_name,
						"file_name": ["like", "%.pdf"]
					},
					fields=["name", "file_name"]
				)

				if attached_files:
					try:
						file_doc = frappe.get_doc("File", attached_files[0].get("name"))
						pdf_data = file_doc.get_content()
						if isinstance(pdf_data, str):
							pdf_data = pdf_data.encode("utf-8")
						pdf_len = len(pdf_data)
						doc_no = inv_bill_no or inv_name
						filename = f"Factura_{inv_name}_{doc_no}.pdf"
					except Exception as e:
						errors.append(f"{inv_name}: Error al leer archivo local ({str(e)})")

				# 2. Si no tiene archivo y es simulada, generar un PDF simulado con formato estructurado válido
				if not pdf_data and inv_remarks and "Simulado" in inv_remarks:
					pdf_data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 40 >>\nstream\nBT /F1 12 Tf 72 712 Td (Mock PDF Invoice) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000062 00000 n\n0000000121 00000 n\n0000000223 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n314\n%%EOF"
					pdf_len = len(pdf_data)
					doc_no = inv_bill_no or "999999"
					filename = f"Factura_{inv_name}_{doc_no}_MOCK.pdf"

				if not pdf_data and not filename:
					errors.append(f"{inv_name}: No tiene archivo PDF adjunto localmente.")

				if pdf_data and filename:
					# Si supera 4.5 MB, guardar el ZIP actual y abrir uno nuevo
					if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
						zip_file.close()
						zip_buffer.seek(0)
						cust_suffix = f"_{doc.customer}" if doc.customer else ""
						file_name = f"Facturas_HKA_{doc.from_date}_a_{doc.to_date}{cust_suffix}_Parte{part_number}.zip"
						
						# Guardar y adjuntar archivo al documento
						file_doc = save_file(
							fname=file_name,
							content=zip_buffer.getvalue(),
							dt="VE Fiscal Document Download",
							dn=docname,
							folder="Home/Attachments",
							is_private=1
						)
						files.append(file_doc.file_url)

						# Resetear para la siguiente parte
						zip_buffer = io.BytesIO()
						zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
						current_zip_count = 0
						part_number += 1

					zip_file.writestr(filename, pdf_data)
					master_zip_file.writestr(filename, pdf_data)
					downloaded_count += 1
					current_zip_count += 1
			except Exception as e:
				errors.append(f"{inv.get('name') or 'Desconocida'}: {str(e)}")

		# Guardar el último ZIP si tiene archivos
		if current_zip_count > 0:
			zip_file.close()
			zip_buffer.seek(0)
			cust_suffix = f"_{doc.customer}" if doc.customer else ""
			part_suffix = f"_Parte{part_number}" if part_number > 1 else ""
			file_name = f"Facturas_HKA_{doc.from_date}_a_{doc.to_date}{cust_suffix}{part_suffix}.zip"
			
			file_doc = save_file(
				fname=file_name,
				content=zip_buffer.getvalue(),
				dt="VE Fiscal Document Download",
				dn=docname,
				folder="Home/Attachments",
				is_private=1
			)
			files.append(file_doc.file_url)
		else:
			zip_file.close()

		# Guardar el ZIP maestro con todas las facturas
		master_file_url = None
		master_size_str = "Desconocido"
		master_file_name = ""
		if downloaded_count > 0:
			master_zip_file.close()
			master_zip_buffer.seek(0)
			cust_suffix = f"_{doc.customer}" if doc.customer else ""
			master_file_name = f"Facturas_HKA_{doc.from_date}_a_{doc.to_date}{cust_suffix}_Completo.zip"
			
			master_file_doc = save_file(
				fname=master_file_name,
				content=master_zip_buffer.getvalue(),
				dt="VE Fiscal Document Download",
				dn=docname,
				folder="Home/Attachments",
				is_private=1
			)
			master_file_url = master_file_doc.file_url
			master_size = master_file_doc.file_size
			if master_size and isinstance(master_size, (int, float)):
				if master_size >= 1024 * 1024:
					master_size_str = f"{round(master_size / (1024 * 1024), 2)} MB"
				else:
					master_size_str = f"{round(master_size / 1024, 2)} KB"
		else:
			master_zip_file.close()

		doc.downloaded_count = downloaded_count

		if downloaded_count == 0:
			doc.status = "Failed"
			doc.error_log = ("No se pudo empaquetar ningún PDF localmente.\nDetalles:\n" + "\n".join(errors))[:30000]
		else:
			doc.status = "Completed"
			if errors:
				doc.error_log = ("Algunas facturas fallaron al empaquetarse:\n" + "\n".join(errors))[:30000]
			else:
				doc.error_log = ""
			
			# Generar un cuadro HTML bonito para las descargas
			links_html = []
			
			if master_file_url:
				master_download_url = f"/api/method/l10n_ve.digital_invoice.tfhka_integration.download_zip_file?file_url={master_file_url}"
				links_html.extend([
					'<div style="margin-bottom: 20px; padding: 15px; background-color: var(--alert-bg-info, #e8f4fd); border-left: 5px solid var(--alert-border-info, #2196f3); border-radius: 4px; display: flex; justify-content: space-between; align-items: center; box-shadow: var(--shadow-sm);">',
					'  <div style="flex: 1; padding-right: 15px;">',
					'    <h4 style="margin: 0 0 5px 0; color: var(--text-color); font-weight: bold; font-size: 14px;">Descargar Todas las Facturas juntas (ZIP Único)</h4>',
					f'    <p style="margin: 0; font-size: 12px; color: var(--text-muted);">{master_file_name} ({master_size_str})</p>',
					'  </div>',
					f'  <a href="{master_download_url}" target="_blank" class="btn btn-sm btn-primary" style="font-weight: bold; padding: 6px 16px; font-size: 13px; border-radius: 4px; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; height: 32px;">Descargar ZIP Único</a>',
					'</div>',
				])
				
			links_html.extend([
				'<div class="table-responsive">',
				'  <table class="table table-bordered table-hover" style="border: 1px solid var(--border-color); border-radius: 4px; overflow: hidden; background-color: var(--card-bg, #ffffff); width: 100%;">',
				'    <thead>',
				'      <tr style="background-color: var(--control-bg, #f8f9fa); font-weight: bold; color: var(--text-color);">',
				'        <th style="width: 10%; text-align: center; border-bottom: 2px solid var(--border-color); padding: 10px;">Parte</th>',
				'        <th style="border-bottom: 2px solid var(--border-color); padding: 10px;">Nombre del Archivo</th>',
				'        <th style="width: 20%; text-align: center; border-bottom: 2px solid var(--border-color); padding: 10px;">Tamaño</th>',
				'        <th style="width: 20%; text-align: center; border-bottom: 2px solid var(--border-color); padding: 10px;">Acción</th>',
				'      </tr>',
				'    </thead>',
				'    <tbody>'
			])
			
			for idx, url in enumerate(files, 1):
				download_url = f"/api/method/l10n_ve.digital_invoice.tfhka_integration.download_zip_file?file_url={url}"
				file_name = url.split("/")[-1]
				
				# Obtener tamaño real del archivo
				file_size_str = "Desconocido"
				file_name_db = frappe.get_value("File", {"file_url": url}, "name")
				if file_name_db:
					file_size = frappe.get_value("File", file_name_db, "file_size")
					if file_size and isinstance(file_size, (int, float)):
						if file_size >= 1024 * 1024:
							file_size_str = f"{round(file_size / (1024 * 1024), 2)} MB"
						else:
							file_size_str = f"{round(file_size / 1024, 2)} KB"
				
				links_html.append(
					f'      <tr>'
					f'        <td style="text-align: center; font-weight: bold; vertical-align: middle; padding: 10px; border-top: 1px solid var(--border-color);">{idx}</td>'
					f'        <td style="vertical-align: middle; padding: 10px; border-top: 1px solid var(--border-color);">{file_name}</td>'
					f'        <td style="text-align: center; vertical-align: middle; color: var(--text-muted); padding: 10px; border-top: 1px solid var(--border-color);">{file_size_str}</td>'
					f'        <td style="text-align: center; vertical-align: middle; padding: 10px; border-top: 1px solid var(--border-color);">'
					f'          <a href="{download_url}" target="_blank" class="btn btn-xs btn-primary" '
					f'             style="font-weight: bold; padding: 4px 12px; font-size: 11px;">Descargar</a>'
					f'        </td>'
					f'      </tr>'
				)
			links_html.extend([
				'    </tbody>',
				'  </table>',
				'</div>'
			])
			doc.files_html = "".join(links_html)

		doc.save()
		frappe.db.commit()
		publish_status(docname, doc.status, request_user)

	except Exception as e:
		frappe.db.rollback()
		try:
			doc = frappe.get_doc("VE Fiscal Document Download", docname)
			doc.status = "Failed"
			doc.error_log = f"Ocurrió un error inesperado en el servidor:\n{str(e)}\n\n{frappe.get_traceback()}"[:30000]
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Failed", request_user)
		except Exception:
			pass


def publish_status(docname: str, status: str, request_user: str):
	"""Notifica al cliente en tiempo real que el proceso ha cambiado de estado."""
	frappe.publish_realtime(
		"hka_download_completed",
		{"docname": docname, "status": status},
		user=request_user
	)


@frappe.whitelist()
def start_bulk_download(docname):
	doc = frappe.get_doc("VE Fiscal Document Download", docname)
	doc.start_download()
	return docname


@frappe.whitelist()
def get_invoice_count(from_date, to_date, customer=None, branch=None):
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

