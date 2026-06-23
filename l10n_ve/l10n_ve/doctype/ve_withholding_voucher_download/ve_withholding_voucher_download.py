# -*- coding: utf-8 -*-
# Copyright (c) 2026, Alexander and Contributors
# For license information, please see license.txt

import frappe
import json
import zipfile
import io
import os
from frappe.model.document import Document
from frappe.utils.file_manager import save_file
from l10n_ve.utils.pdf_utils import safe_get_pdf

class VEWithholdingVoucherDownload(Document):
	def validate(self):
		if self.from_date and self.to_date:
			if self.from_date > self.to_date:
				frappe.throw(frappe._("From Date cannot be after To Date."))

	@frappe.whitelist()
	def start_download(self):
		self.check_permission("write")
		if self.status == "Processing":
			return False
		
		# Validar que existan comprobantes antes de encolar
		vouchers = get_withholding_vouchers(self)
		if not vouchers:
			frappe.throw(frappe._("No withholding vouchers found in the selected range."))

		self.status = "Processing"
		self.error_log = ""
		self.files_html = ""
		self.total_attempted = 0
		self.downloaded_count = 0
		self.save()
		frappe.db.commit()

		frappe.enqueue(
			"l10n_ve.l10n_ve.doctype.ve_withholding_voucher_download.ve_withholding_voucher_download.process_download_job",
			queue="default",
			timeout=1800,
			docname=self.name,
			request_user=frappe.session.user
		)
		return True


def process_download_job(docname: str, request_user: str):
	"""Background job to bulk download withholding vouchers in chunks."""
	try:
		if request_user:
			frappe.set_user(request_user)
		doc = frappe.get_doc("VE Withholding Voucher Download", docname)
		
		vouchers = get_withholding_vouchers(doc)
		doc.total_attempted = len(vouchers)

		if not vouchers:
			doc.status = "Failed"
			doc.error_log = frappe._("No withholding vouchers found in the selected range.")
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Failed", request_user)
			return

		MAX_SIZE_BYTES = int(4.5 * 1024 * 1024)  # 4.5 MB per ZIP
		files = []
		errors = []
		downloaded_count = 0

		zip_buffer = io.BytesIO()
		zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
		current_zip_count = 0
		part_number = 1

		master_zip_buffer = io.BytesIO()
		master_zip_file = zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED)

		chunk_size = 1000
		for chunk_start in range(0, len(vouchers), chunk_size):
			chunk = vouchers[chunk_start:chunk_start + chunk_size]

			# 1. Generate HTML sequentially in the main thread (fast and DB safe)
			html_tasks = []
			for inv in chunk:
				doctype = inv.get("doctype")
				name = inv.get("name")
				voucher_num = inv.get("voucher_number") or ""
				
				html = None
				filename = ""
				try:
					if doctype == "VAT Withholding Voucher":
						from l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase import generate_vat_report
						html = generate_vat_report(voucher_name=name)
						clean_num = voucher_num.replace("/", "_").replace("\\", "_")
						filename = f"VAT_Withholding_{name}_{clean_num}.pdf"
					else:
						from l10n_ve.l10n_ve.report.islr_withholding_voucher_purchase.islr_withholding_voucher_purchase import generate_islr_report
						html = generate_islr_report(voucher_name=name)
						clean_num = voucher_num.replace("/", "_").replace("\\", "_")
						filename = f"ISLR_Withholding_{name}_{clean_num}.pdf"
					
					if html:
						html_tasks.append((html, filename, name))
					else:
						errors.append(f"{name}: " + frappe._("Error generating print HTML."))
				except Exception as e:
					errors.append(f"{name}: " + frappe._("Error rendering PDF ({0})").format(str(e)))

			# 2. Convert HTML to PDF in parallel using ThreadPoolExecutor
			if html_tasks:
				from concurrent.futures import ThreadPoolExecutor, as_completed
				
				# Get current site name and sites path to pass to threads
				site_name = frappe.local.site
				sites_path = frappe.local.sites_path

				def worker_generate_pdf(task_data):
					html, filename, name = task_data
					import frappe
					frappe.init(site=site_name, sites_path=sites_path)
					frappe.connect()
					try:
						pdf_bytes = safe_get_pdf(html)
						return {"status": "success", "pdf_data": pdf_bytes, "filename": filename, "name": name}
					except Exception as ex:
						return {"status": "error", "error": str(ex), "name": name}
					finally:
						frappe.db.close()

				max_workers = min(8, os.cpu_count() or 4)
				with ThreadPoolExecutor(max_workers=max_workers) as executor:
					futures = {
						executor.submit(worker_generate_pdf, task): task
						for task in html_tasks
					}
					
					for future in as_completed(futures):
						try:
							res_data = future.result()
							if res_data.get("status") == "success":
								pdf_data = res_data.get("pdf_data")
								filename = res_data.get("filename")
								if pdf_data:
									pdf_len = len(pdf_data)
									# If it exceeds 4.5 MB, save the current ZIP and open a new one
									if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
										zip_buffer, zip_file = save_zip_part(doc, zip_buffer, zip_file, part_number, files)
										current_zip_count = 0
										part_number += 1

									zip_file.writestr(filename, pdf_data)
									master_zip_file.writestr(filename, pdf_data)
									downloaded_count += 1
									current_zip_count += 1
							else:
								errors.append(f"{res_data.get('name')}: " + frappe._("Error rendering PDF ({0})").format(res_data.get("error")))
						except Exception as e:
							task = futures[future]
							errors.append(f"{task[2]}: " + frappe._("Error rendering PDF ({0})").format(str(e)))

			# Save progress and commit at the end of current chunk of 1000
			doc.downloaded_count = downloaded_count
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			publish_status(docname, "Processing", request_user)

		# Save the last ZIP if it has files
		if current_zip_count > 0:
			zip_file.close()
			zip_buffer.seek(0)
			supp_suffix = f"_{doc.supplier}" if doc.supplier else ""
			part_suffix = f"_Part{part_number}" if part_number > 1 else ""
			file_name = f"Withholding_Vouchers_{doc.from_date}_to_{doc.to_date}{supp_suffix}{part_suffix}.zip"
			
			file_doc = save_file(
				fname=file_name,
				content=zip_buffer.getvalue(),
				dt="VE Withholding Voucher Download",
				dn=docname,
				folder="Home/Attachments",
				is_private=1
			)
			files.append(file_doc.file_url)
		else:
			zip_file.close()

		# Save master ZIP containing all vouchers
		master_file_url, master_file_name, master_size_str = save_master_zip(doc, master_zip_file, master_zip_buffer, downloaded_count)

		doc.downloaded_count = downloaded_count

		if downloaded_count == 0:
			doc.status = "Failed"
			doc.error_log = (frappe._("Could not package any withholding vouchers.\nDetails:\n") + "\n".join(errors))[:30000]
		else:
			doc.status = "Completed"
			doc.error_log = (frappe._("Some vouchers failed to package:\n") + "\n".join(errors))[:30000] if errors else ""
			doc.files_html = generate_files_html(files, downloaded_count, master_file_url, master_file_name, master_size_str)

		doc.save()
		frappe.db.commit()

		send_download_notification(docname, doc.status, downloaded_count, len(files), doc.error_log, request_user)
		publish_status(docname, doc.status, request_user)

	except Exception as e:
		frappe.db.rollback()
		handle_unexpected_error(docname, request_user, e)


def get_withholding_vouchers(doc):
	vouchers = []
	
	# Filtros comunes
	vat_filters = {
		"docstatus": 1,
		"empresa": doc.empresa,
		"issue_date": ["between", [doc.from_date, doc.to_date]]
	}
	islr_filters = {
		"docstatus": 1,
		"empresa": doc.empresa,
		"posting_date": ["between", [doc.from_date, doc.to_date]]
	}
	
	if doc.supplier:
		vat_filters["supplier"] = doc.supplier
		islr_filters["supplier"] = doc.supplier

	if doc.withholding_type in ("VAT", "Both"):
		vat_list = frappe.get_all(
			"VAT Withholding Voucher",
			filters=vat_filters,
			fields=["name", "voucher_number"]
		)
		for v in vat_list:
			vouchers.append({
				"doctype": "VAT Withholding Voucher",
				"name": v.get("name"),
				"voucher_number": v.get("voucher_number")
			})

	if doc.withholding_type in ("ISLR", "Both"):
		islr_list = frappe.get_all(
			"ISLR Withholding Voucher",
			filters=islr_filters,
			fields=["name", "voucher_number"]
		)
		for v in islr_list:
			vouchers.append({
				"doctype": "ISLR Withholding Voucher",
				"name": v.get("name"),
				"voucher_number": v.get("voucher_number")
			})
			
	return vouchers


def download_voucher_pdf(inv, errors):
	doctype = inv.get("doctype")
	name = inv.get("name")
	voucher_num = inv.get("voucher_number") or ""
	
	pdf_data = None
	filename = ""

	try:
		if doctype == "VAT Withholding Voucher":
			from l10n_ve.l10n_ve.report.vat_withholding_voucher_purchase.vat_withholding_voucher_purchase import generate_vat_report
			html = generate_vat_report(voucher_name=name)
			clean_num = voucher_num.replace("/", "_").replace("\\", "_")
			filename = f"VAT_Withholding_{name}_{clean_num}.pdf"
		else:
			from l10n_ve.l10n_ve.report.islr_withholding_voucher_purchase.islr_withholding_voucher_purchase import generate_islr_report
			html = generate_islr_report(voucher_name=name)
			clean_num = voucher_num.replace("/", "_").replace("\\", "_")
			filename = f"ISLR_Withholding_{name}_{clean_num}.pdf"

		if html:
			pdf_data = safe_get_pdf(html)
		else:
			errors.append(f"{name}: " + frappe._("Error generating print HTML."))
	except Exception as e:
		errors.append(f"{name}: " + frappe._("Error rendering PDF ({0})").format(str(e)))

	return pdf_data, filename


def save_zip_part(doc, zip_buffer, zip_file, part_number, files):
	zip_file.close()
	zip_buffer.seek(0)
	supp_suffix = f"_{doc.supplier}" if doc.supplier else ""
	file_name = f"Withholding_Vouchers_{doc.from_date}_to_{doc.to_date}{supp_suffix}_Part{part_number}.zip"
	
	file_doc = save_file(
		fname=file_name,
		content=zip_buffer.getvalue(),
		dt="VE Withholding Voucher Download",
		dn=doc.name,
		folder="Home/Attachments",
		is_private=1
	)
	files.append(file_doc.file_url)

	new_buffer = io.BytesIO()
	new_zip_file = zipfile.ZipFile(new_buffer, "w", zipfile.ZIP_DEFLATED)
	return new_buffer, new_zip_file


def save_master_zip(doc, master_zip_file, master_zip_buffer, downloaded_count):
	master_file_url = None
	master_size_str = "Desconocido"
	master_file_name = ""
	if downloaded_count > 0:
		master_zip_file.close()
		master_zip_buffer.seek(0)
		supp_suffix = f"_{doc.supplier}" if doc.supplier else ""
		master_file_name = f"Withholding_Vouchers_{doc.from_date}_to_{doc.to_date}{supp_suffix}_Full.zip"
		
		master_file_doc = save_file(
			fname=master_file_name,
			content=master_zip_buffer.getvalue(),
			dt="VE Withholding Voucher Download",
			dn=doc.name,
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
	return master_file_url, master_file_name, master_size_str


def generate_files_html(files, downloaded_count, master_file_url, master_file_name, master_size_str):
	links_html = []
	
	if master_file_url:
		master_download_url = f"/api/method/l10n_ve.digital_invoice.tfhka_integration.download_zip_file?file_url={master_file_url}"
		links_html.extend([
			'<div style="margin-bottom: 20px; padding: 15px; background-color: var(--alert-bg-info, #e8f4fd); border-left: 5px solid var(--alert-border-info, #2196f3); border-radius: 4px; display: flex; justify-content: space-between; align-items: center; box-shadow: var(--shadow-sm);">',
			'  <div style="flex: 1; padding-right: 15px;">',
			'    <h4 style="margin: 0 0 5px 0; color: var(--text-color); font-weight: bold; font-size: 14px;">Descargar Todos los Comprobantes juntos (ZIP Único)</h4>',
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
	return "".join(links_html)


def send_download_notification(docname, status, downloaded_count, files_count, error_log, request_user):
	try:
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
		part_txt = f" en {files_count} partes" if files_count > 1 else ""
		if status == "Completed":
			msg = f"Tu descarga de comprobantes de retención está lista ({downloaded_count} archivos{part_txt})."
			email_content = f"La solicitud de descarga masiva ha finalizado con éxito. Puedes descargar los archivos ZIP desde el documento <a href='/app/ve-withholding-voucher-download/{docname}'>{docname}</a>."
		else:
			msg = "La descarga masiva de comprobantes de retención falló."
			email_content = f"La solicitud de descarga masiva {docname} falló. Error: {error_log}"
		
		enqueue_create_notification(
			users=[request_user],
			doc={
				"subject": msg,
				"email_content": email_content,
				"type": "Alert",
				"document_type": "VE Withholding Voucher Download",
				"document_name": docname
			}
		)
	except Exception as e:
		frappe.logger("l10n_ve").error(f"Error creating notification: {str(e)}")


def handle_unexpected_error(docname: str, request_user: str, e: Exception):
	try:
		doc = frappe.get_doc("VE Withholding Voucher Download", docname)
		doc.status = "Failed"
		doc.error_log = (frappe._("An unexpected server error occurred:") + f"\n{str(e)}\n\n{frappe.get_traceback()}")[:30000]
		doc.save()
		frappe.db.commit()

		try:
			from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
			enqueue_create_notification(
				users=[request_user],
				doc={
					"subject": frappe._("The bulk download of withholding vouchers failed."),
					"email_content": frappe._("An unexpected error occurred while processing {0}: {1}").format(docname, str(e)),
					"type": "Alert",
					"document_type": "VE Withholding Voucher Download",
					"document_name": docname
				}
			)
		except Exception:
			pass

		publish_status(docname, "Failed", request_user)
	except Exception:
		pass


def publish_status(docname: str, status: str, request_user: str):
	"""Notifica al cliente en tiempo real que el proceso ha cambiado de estado."""
	frappe.publish_realtime(
		"withholding_download_completed",
		{"docname": docname, "status": status},
		user=request_user
	)


@frappe.whitelist()
def start_bulk_download(docname):
	doc = frappe.get_doc("VE Withholding Voucher Download", docname)
	doc.check_permission("write")
	doc.start_download()
	return docname


@frappe.whitelist()
def get_voucher_count(from_date, to_date, company, supplier=None, withholding_type="Both"):
	if not frappe.has_permission("VAT Withholding Voucher", "read") and not frappe.has_permission("ISLR Withholding Voucher", "read"):
		frappe.throw(frappe._("No permission to read Withholding Vouchers."), frappe.PermissionError)

	vat_filters = {
		"docstatus": 1,
		"empresa": company,
		"issue_date": ["between", [from_date, to_date]]
	}
	islr_filters = {
		"docstatus": 1,
		"empresa": company,
		"posting_date": ["between", [from_date, to_date]]
	}
	
	if supplier:
		vat_filters["supplier"] = supplier
		islr_filters["supplier"] = supplier

	count = 0
	if withholding_type in ("VAT", "Both"):
		count += frappe.db.count("VAT Withholding Voucher", vat_filters)

	if withholding_type in ("ISLR", "Both"):
		count += frappe.db.count("ISLR Withholding Voucher", islr_filters)

	return count

