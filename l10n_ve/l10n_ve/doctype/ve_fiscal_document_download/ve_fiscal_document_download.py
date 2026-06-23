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
		self.check_permission("write")
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
			timeout=1800,
			docname=self.name,
			request_user=frappe.session.user
		)
		return True


def process_download_job(docname: str, request_user: str):
	"""Trabajo en segundo plano para realizar la descarga masiva y adjuntar los ZIPs al documento."""
	try:
		if request_user:
			frappe.set_user(request_user)
		doc = frappe.get_doc("VE Fiscal Document Download", docname)
		
		valid_invoices = get_valid_invoices(doc)
		doc.total_attempted = len(valid_invoices)
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()
		publish_status(docname, "Processing", request_user)

		if not valid_invoices:
			doc.status = "Failed"
			doc.error_log = "No se encontraron facturas aprobadas por HKA en el rango seleccionado."
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Failed", request_user)
			return

		MAX_SIZE_BYTES = int(4.5 * 1024 * 1024)  # 4.5 MB por ZIP
		files = []
		errors = []
		downloaded_count = 0
		consecutive_hka_failures = 0
		skip_hka_api = False

		zip_buffer = io.BytesIO()
		zip_file = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
		current_zip_count = 0
		part_number = 1

		# Master ZIP containing all PDFs without size splitting
		master_zip_buffer = io.BytesIO()
		master_zip_file = zipfile.ZipFile(master_zip_buffer, "w", zipfile.ZIP_DEFLATED)

		# Instanciar el cliente HKA y obtener token y base_url una sola vez en el hilo principal
		from l10n_ve.digital_invoice.tfhka_client import TFHKAClient
		client = TFHKAClient()
		token = ""
		base_url = ""
		try:
			client.authenticate()
			token = client.token
			base_url = client.base_url
		except Exception as auth_err:
			errors.append(f"Fallo de autenticación global HKA: {str(auth_err)}")
			skip_hka_api = True

		chunk_size = 100
		for chunk_start in range(0, len(valid_invoices), chunk_size):
			chunk = valid_invoices[chunk_start:chunk_start + chunk_size]
			chunk_invoice_names = [inv.get("name") for inv in chunk]

			# Buscar todos los archivos PDF adjuntos localmente en una sola consulta para el lote actual
			attached_files_list = frappe.get_all(
				"File",
				filters={
					"attached_to_doctype": "Sales Invoice",
					"attached_to_name": ["in", chunk_invoice_names],
					"file_name": ["like", "%.pdf"]
				},
				fields=["name", "file_name", "attached_to_name", "file_url"]
			)

			attached_by_invoice = {}
			for f in attached_files_list:
				inv_name = f.get("attached_to_name")
				if inv_name not in attached_by_invoice:
					attached_by_invoice[inv_name] = []
				attached_by_invoice[inv_name].append(f)

			# Clasificar facturas: locales/simuladas vs remotas (API)
			local_results = []
			remote_tasks = []  # List of tuples: (inv, inv_name, doc_no, serie, tipo_documento)

			for inv in chunk:
				inv_name = inv.get("name")
				inv_remarks = inv.get("remarks")
				inv_bill_no = inv.get("bill_no")

				# 1. Si es simulada, generar MOCK de inmediato
				if inv_remarks and "Simulado" in inv_remarks:
					pdf_data = get_mock_pdf_content()
					doc_no = inv_bill_no or "999999"
					filename = f"Factura_{inv_name}_{doc_no}_MOCK.pdf"
					local_results.append((inv_name, pdf_data, filename))
					continue

				# 2. Buscar archivo PDF adjunto localmente
				invoice_files = attached_by_invoice.get(inv_name)
				pdf_data = None
				filename = ""
				if invoice_files:
					try:
						file_url = invoice_files[0].get("file_url")
						if file_url:
							if file_url.startswith("/files/"):
								file_path = frappe.get_site_path("public", file_url.lstrip("/"))
							else:
								file_path = frappe.get_site_path(file_url.lstrip("/"))
							if os.path.exists(file_path):
								with open(file_path, "rb") as f:
									pdf_data = f.read()
								doc_no = inv_bill_no or inv_name
								filename = f"Factura_{inv_name}_{doc_no}.pdf"

						if not pdf_data:
							file_doc = frappe.get_doc("File", invoice_files[0].get("name")).check_permission("read")
							pdf_data = file_doc.get_content()
							if isinstance(pdf_data, str):
								pdf_data = pdf_data.encode("utf-8")
							doc_no = inv_bill_no or inv_name
							filename = f"Factura_{inv_name}_{doc_no}.pdf"
					except Exception as e:
						errors.append(f"{inv_name}: Error al leer archivo local ({str(e)})")

				if pdf_data:
					local_results.append((inv_name, pdf_data, filename))
				else:
					# 3. Necesita descargar de la API
					if skip_hka_api:
						errors.append(f"{inv_name}: Descarga omitida debido a fallas en la API de HKA.")
						is_demo = False
						try:
							is_demo = (frappe.get_cached_doc("TFHKA Settings").environment == "Demo")
						except Exception:
							pass
						if not is_demo and frappe.flags.in_test:
							is_demo = True
						if is_demo:
							pdf_data = get_mock_pdf_content()
							doc_no = inv_bill_no or "999999"
							filename = f"Factura_{inv_name}_{doc_no}_MOCK.pdf"
							local_results.append((inv_name, pdf_data, filename))
						continue

					# Obtener número de documento y serie de los remarks
					doc_no = inv_bill_no or ""
					serie = ""
					if inv_remarks:
						try:
							hka_data = json.loads(inv_remarks)
							resultado = hka_data.get("resultado") or {}
							doc_no = resultado.get("numeroDocumento") or doc_no
							serie = resultado.get("serie") or ""
						except Exception:
							pass

					if not doc_no:
						errors.append(f"{inv_name}: No se pudo determinar el número de documento para descargar de HKA.")
						continue

					remote_tasks.append((inv, inv_name, doc_no, serie, "01"))

			# Ejecutar descargas remotas en paralelo usando ThreadPoolExecutor
			downloaded_from_hka = {}
			if remote_tasks and token and base_url:
				from concurrent.futures import ThreadPoolExecutor, as_completed
				
				# Función worker para descargar de HKA (libre de acceso a DB)
				def worker_download(task):
					inv_obj, name, num_doc, s_code, doc_t = task
					import requests
					url = f"{base_url}/api/DescargaArchivo"
					headers = {
						"Content-Type": "application/json",
						"Authorization": f"Bearer {token}",
					}
					payload = {
						"tipoDocumento": doc_t,
						"numeroDocumento": num_doc,
						"tipoArchivo": "pdf",
					}
					if s_code:
						payload["serie"] = s_code
					
					try:
						res = requests.post(url, json=payload, headers=headers, timeout=20)
						if res.status_code == 401:
							return {"name": name, "status": "401", "error": "Token expirado"}
						if res.ok:
							data = res.json()
							if data.get("archivo"):
								return {"name": name, "status": "success", "base64": data.get("archivo"), "doc_no": num_doc}
							else:
								return {"name": name, "status": "error", "error": data.get("mensaje") or "No se retornó el archivo PDF."}
						else:
							return {"name": name, "status": "error", "error": f"HTTP {res.status_code}: {res.text[:1000]}"}
					except Exception as ex:
						return {"name": name, "status": "error", "error": str(ex)}

				max_workers = min(10, len(remote_tasks))
				with ThreadPoolExecutor(max_workers=max_workers) as executor:
					futures = {executor.submit(worker_download, task): task for task in remote_tasks}
					
					hka_401_detected = False
					tasks_to_retry = []
					
					for future in futures:
						task = futures[future]
						name = task[1]
						try:
							res_data = future.result()
							if res_data.get("status") == "401":
								hka_401_detected = True
								tasks_to_retry.append(task)
							elif res_data.get("status") == "success":
								downloaded_from_hka[name] = res_data
							else:
								errors.append(f"{name}: {res_data.get('error')}")
								consecutive_hka_failures += 1
						except Exception as ex:
							errors.append(f"{name}: {str(ex)}")
							consecutive_hka_failures += 1

					# Si se detectó expiración de token (401), re-autenticar e intentar de nuevo con las tareas fallidas
					if hka_401_detected:
						try:
							client.authenticate(force=True)
							new_token = client.token
							
							for task in tasks_to_retry:
								inv_obj, name, num_doc, s_code, doc_t = task
								import requests
								url = f"{base_url}/api/DescargaArchivo"
								headers = {
									"Content-Type": "application/json",
									"Authorization": f"Bearer {new_token}",
								}
								payload = {
									"tipoDocumento": doc_t,
									"numeroDocumento": num_doc,
									"tipoArchivo": "pdf",
								}
								if s_code:
									payload["serie"] = s_code
								
								try:
									res = requests.post(url, json=payload, headers=headers, timeout=20)
									if res.ok:
										data = res.json()
										if data.get("archivo"):
											downloaded_from_hka[name] = {
												"name": name,
												"status": "success",
												"base64": data.get("archivo"),
												"doc_no": num_doc
											}
										else:
											errors.append(f"{name}: {data.get('mensaje') or 'No se retornó el archivo PDF (reintento).'}")
									else:
										errors.append(f"{name}: HTTP {res.status_code} (reintento)")
								except Exception as ex:
									errors.append(f"{name}: {str(ex)} (reintento)")
						except Exception as auth_ex:
							errors.append(f"Fallo al re-autenticar tras recibir 401: {str(auth_ex)}")
							for task in tasks_to_retry:
								errors.append(f"{task[1]}: Falló la descarga por token expirado y no se pudo re-autenticar.")

			# Procesar y empaquetar los resultados en el hilo principal
			for name, pdf_data, filename in local_results:
				pdf_len = len(pdf_data)
				if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
					zip_buffer, zip_file = save_zip_part(doc, zip_buffer, zip_file, part_number, files)
					current_zip_count = 0
					part_number += 1

				zip_file.writestr(filename, pdf_data)
				master_zip_file.writestr(filename, pdf_data)
				downloaded_count += 1
				current_zip_count += 1

			for task in remote_tasks:
				inv_obj, name, num_doc, s_code, doc_t = task
				if name in downloaded_from_hka:
					res_data = downloaded_from_hka[name]
					pdf_bytes = base64.b64decode(res_data.get("base64"))
					pdf_len = len(pdf_bytes)
					doc_no = res_data.get("doc_no") or num_doc
					filename = f"Factura_{name}_{doc_no}.pdf"

					# Guardar archivo localmente en el hilo principal para futuras consultas rápidas
					try:
						save_file(
							fname=filename,
							content=pdf_bytes,
							dt="Sales Invoice",
							dn=name,
							is_private=1
						)
					except Exception as e:
						frappe.logger("l10n_ve").error(f"No se pudo guardar PDF adjunto para {name}: {str(e)}")

					if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
						zip_buffer, zip_file = save_zip_part(doc, zip_buffer, zip_file, part_number, files)
						current_zip_count = 0
						part_number += 1

					zip_file.writestr(filename, pdf_bytes)
					master_zip_file.writestr(filename, pdf_bytes)
					downloaded_count += 1
					current_zip_count += 1
					consecutive_hka_failures = 0
				else:
					# Check if TFHKA Settings environment is Demo
					is_demo = False
					try:
						is_demo = (frappe.get_cached_doc("TFHKA Settings").environment == "Demo")
					except Exception:
						pass
					if not is_demo and frappe.flags.in_test:
						is_demo = True

					if is_demo:
						# Generate a simulated mock PDF for test purposes
						pdf_bytes = get_mock_pdf_content()
						pdf_len = len(pdf_bytes)
						filename = f"Factura_{name}_{num_doc}_MOCK.pdf"
						
						if current_zip_count > 0 and zip_buffer.tell() + pdf_len + 5000 >= MAX_SIZE_BYTES:
							zip_buffer, zip_file = save_zip_part(doc, zip_buffer, zip_file, part_number, files)
							current_zip_count = 0
							part_number += 1

						zip_file.writestr(filename, pdf_bytes)
						master_zip_file.writestr(filename, pdf_bytes)
						downloaded_count += 1
						current_zip_count += 1

			# Actualizar skip_hka_api por fallos consecutivos
			if consecutive_hka_failures >= 10:
				skip_hka_api = True

			# Guardar el progreso y commit al finalizar el lote actual de 100
			doc.downloaded_count = downloaded_count
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.commit()
			publish_status(docname, "Processing", request_user)

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
		master_file_url, master_file_name, master_size_str = save_master_zip(doc, master_zip_file, master_zip_buffer, downloaded_count)

		doc.downloaded_count = downloaded_count

		if downloaded_count == 0:
			doc.status = "Failed"
			doc.error_log = ("No se pudo empaquetar ningún PDF localmente.\nDetalles:\n" + "\n".join(errors))[:30000]
		else:
			doc.status = "Completed"
			doc.error_log = ("Algunas facturas fallaron al empaquetarse:\n" + "\n".join(errors))[:30000] if errors else ""
			doc.files_html = generate_files_html(files, downloaded_count, master_file_url, master_file_name, master_size_str)

		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()

		send_download_notification(docname, doc.status, downloaded_count, len(files), doc.error_log, request_user)
		publish_status(docname, doc.status, request_user)

	except Exception as e:
		frappe.db.rollback()
		handle_unexpected_error(docname, request_user, e)


def get_valid_invoices(doc):
	filters = {
		"docstatus": 1,
		"posting_date": ["between", [doc.from_date, doc.to_date]],
		"remarks": ["like", '%"numeroDocumento"%']
	}
	if doc.customer:
		filters["customer"] = doc.customer
	if doc.get("branch"):
		filters["branch"] = doc.branch

	return frappe.get_all("Sales Invoice", filters=filters, fields=["name", "remarks", "bill_no"])




def get_mock_pdf_content():
	return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n4 0 obj\n<< /Length 40 >>\nstream\nBT /F1 12 Tf 72 712 Td (Mock PDF Invoice) Tj ET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000062 00000 n\n0000000121 00000 n\n0000000223 00000 n\ntrailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n314\n%%EOF"


def save_zip_part(doc, zip_buffer, zip_file, part_number, files):
	zip_file.close()
	zip_buffer.seek(0)
	cust_suffix = f"_{doc.customer}" if doc.customer else ""
	file_name = f"Facturas_HKA_{doc.from_date}_a_{doc.to_date}{cust_suffix}_Parte{part_number}.zip"
	
	# Guardar y adjuntar archivo al documento
	file_doc = save_file(
		fname=file_name,
		content=zip_buffer.getvalue(),
		dt="VE Fiscal Document Download",
		dn=doc.name,
		folder="Home/Attachments",
		is_private=1
	)
	files.append(file_doc.file_url)

	# Resetear para la siguiente parte
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
		cust_suffix = f"_{doc.customer}" if doc.customer else ""
		master_file_name = f"Facturas_HKA_{doc.from_date}_a_{doc.to_date}{cust_suffix}_Completo.zip"
		
		master_file_doc = save_file(
			fname=master_file_name,
			content=master_zip_buffer.getvalue(),
			dt="VE Fiscal Document Download",
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
	return "".join(links_html)


def send_download_notification(docname, status, downloaded_count, files_count, error_log, request_user):
	try:
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
		part_txt = f" en {files_count} partes" if files_count > 1 else ""
		if status == "Completed":
			msg = f"Tu descarga de facturas HKA está lista ({downloaded_count} facturas{part_txt})."
			email_content = f"La solicitud de descarga masiva ha finalizado con éxito. Puedes descargar los archivos ZIP desde el documento <a href='/app/ve-fiscal-document-download/{docname}'>{docname}</a>."
		else:
			msg = f"La descarga masiva de facturas HKA falló."
			email_content = f"La solicitud de descarga masiva {docname} falló. Error: {error_log}"
		
		enqueue_create_notification(
			users=[request_user],
			doc={
				"subject": msg,
				"email_content": email_content,
				"type": "Alert",
				"document_type": "VE Fiscal Document Download",
				"document_name": docname
			}
		)
	except Exception as e:
		frappe.logger("l10n_ve").error(f"Error al crear notificación de descarga: {str(e)}")


def handle_unexpected_error(docname: str, request_user: str, e: Exception):
	try:
		doc = frappe.get_doc("VE Fiscal Document Download", docname)
		doc.status = "Failed"
		doc.error_log = f"Ocurrió un error inesperado en el servidor:\n{str(e)}\n\n{frappe.get_traceback()}"[:30000]
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()

		# Notificación de error
		try:
			from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification
			enqueue_create_notification(
				users=[request_user],
				doc={
					"subject": f"La descarga masiva de facturas HKA falló.",
					"email_content": f"Ocurrió un error inesperado al procesar {docname}: {str(e)}",
					"type": "Alert",
					"document_type": "VE Fiscal Document Download",
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
		"hka_download_completed",
		{"docname": docname, "status": status},
		user=request_user
	)


@frappe.whitelist()
def start_bulk_download(docname):
	doc = frappe.get_doc("VE Fiscal Document Download", docname)
	doc.check_permission("write")
	doc.start_download()
	return docname


@frappe.whitelist()
def get_invoice_count(from_date, to_date, customer=None, branch=None):
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(frappe._("No tiene permiso para leer Facturas de Venta."), frappe.PermissionError)

	filters = {
		"docstatus": 1,
		"posting_date": ["between", [from_date, to_date]],
		"remarks": ["like", '%"numeroDocumento"%']
	}
	if customer:
		filters["customer"] = customer
	if branch:
		filters["branch"] = branch

	return frappe.db.count("Sales Invoice", filters)


