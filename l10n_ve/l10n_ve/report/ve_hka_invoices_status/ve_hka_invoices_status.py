# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	if not filters.get("company"):
		frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

	frappe.has_permission("Company", "read", doc=filters.get("company"), throw=True)

	dt_filter = filters.get("document_type") or "Todos"
	if dt_filter in ("Factura de Venta", "Sales Invoice"):
		allowed_doctypes = ["Sales Invoice"]
	elif dt_filter in ("Nota de Crédito", "Nota de Crédito de Venta", "VE Sales Credit Note"):
		allowed_doctypes = ["VE Sales Credit Note"]
	elif dt_filter in ("Nota de Débito", "Nota de Débito de Venta", "VE Sales Debit Note"):
		allowed_doctypes = ["VE Sales Debit Note"]
	else:
		allowed_doctypes = ["Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note"]

	for dt in allowed_doctypes:
		frappe.has_permission(dt, "read", throw=True)

	columns = get_columns()
	data = get_data(filters)

	# Sumarizar los datos en el resumen del reporte
	total_docs = len(data)
	total_emitida = sum(1 for row in data if row.get("status") == "Emitida")
	total_error = sum(1 for row in data if row.get("status") == "Error")
	total_pendiente = sum(1 for row in data if row.get("status") == "Pendiente")
	total_anulada = sum(1 for row in data if row.get("status") == "Anulada")

	report_summary = [
		{
			"value": total_docs,
			"label": _("Total de Documentos"),
			"datatype": "Int",
		},
		{
			"value": total_emitida,
			"label": _("Emitidas exitosamente"),
			"datatype": "Int",
		},
		{
			"value": total_error,
			"label": _("Con fallas / errores HKA"),
			"datatype": "Int",
		},
		{
			"value": total_pendiente,
			"label": _("Pendientes por enviar"),
			"datatype": "Int",
		},
		{
			"value": total_anulada,
			"label": _("Anuladas ante HKA"),
			"datatype": "Int",
		}
	]

	return columns, data, None, None, report_summary


def get_columns():
	return [
		{
			"fieldname": "document_type",
			"label": _("Tipo de Documento"),
			"fieldtype": "Data",
			"width": 160
		},
		{
			"fieldname": "name",
			"label": _("ID Documento"),
			"fieldtype": "Dynamic Link",
			"options": "doctype",
			"width": 180
		},
		{
			"fieldname": "posting_date",
			"label": _("Fecha Emisión"),
			"fieldtype": "Date",
			"width": 110
		},
		{
			"fieldname": "customer_tax_id",
			"label": _("Documento del Cliente"),
			"fieldtype": "Data",
			"width": 140
		},
		{
			"fieldname": "customer_name",
			"label": _("Nombre del Cliente"),
			"fieldtype": "Data",
			"width": 200
		},
		{
			"fieldname": "grand_total",
			"label": _("Total Facturado"),
			"fieldtype": "Currency",
			"width": 130
		},
		{
			"fieldname": "bill_no",
			"label": _("Factura HKA (Nro)"),
			"fieldtype": "Data",
			"width": 130
		},
		{
			"fieldname": "bill_control",
			"label": _("Nro. Control"),
			"fieldtype": "Data",
			"width": 130
		},
		{
			"fieldname": "status",
			"label": _("Estado HKA"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "docstatus_label",
			"label": _("Estado Factura"),
			"fieldtype": "Data",
			"width": 140
		},
		{
			"fieldname": "log_creation",
			"label": _("Último Intento"),
			"fieldtype": "Datetime",
			"width": 160
		},
		{
			"fieldname": "log_notes",
			"label": _("Detalles / Error HKA"),
			"fieldtype": "Small Text",
			"width": 300
		}
	]


def get_data(filters):
	conditions = ["doc.company = %(company)s"]
	values = {"company": filters.get("company")}

	if filters.get("from_date"):
		conditions.append("doc.posting_date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("doc.posting_date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")

	cond_str = " AND ".join(conditions)

	query_parts = []
	target_doctype = filters.get("document_type") or "Todos"

	if target_doctype in ("Factura de Venta", "Sales Invoice"):
		allowed_doctypes = ["Sales Invoice"]
	elif target_doctype in ("Nota de Crédito", "Nota de Crédito de Venta", "VE Sales Credit Note"):
		allowed_doctypes = ["VE Sales Credit Note"]
	elif target_doctype in ("Nota de Débito", "Nota de Débito de Venta", "VE Sales Debit Note"):
		allowed_doctypes = ["VE Sales Debit Note"]
	else:
		allowed_doctypes = ["Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note"]

	# 1. Sales Invoice
	if "Sales Invoice" in allowed_doctypes:
		query_parts.append(f"""
			SELECT 
				'Sales Invoice' AS doctype,
				'Sales Invoice' AS document_type,
				doc.name,
				doc.posting_date,
				doc.customer,
				doc.customer_name,
				tc.tax_id AS customer_tax_id,
				doc.grand_total,
				doc.bill_no,
				doc.bill_control,
				doc.docstatus,
				doc.status AS raw_doc_status,
				doc.is_void,
				doc.remarks,
				doc.hka_status,
				log.status AS log_status,
				log.notes AS log_notes,
				log.creation AS log_creation
			FROM `tabSales Invoice` doc
			LEFT JOIN `tabCustomer` tc ON tc.name = doc.customer
			LEFT JOIN (
				SELECT 
					sales_invoice,
					document_type,
					status,
					notes,
					creation,
					ROW_NUMBER() OVER (PARTITION BY sales_invoice, document_type ORDER BY creation DESC) as rn
				FROM `tabVE Digital Invoice Log`
				WHERE document_type = 'Sales Invoice'
			) log ON log.sales_invoice = doc.name AND log.rn = 1
			WHERE doc.docstatus IN (1, 2) AND doc.status != 'Draft' AND {cond_str}
		""")

	# 2. VE Sales Credit Note
	if "VE Sales Credit Note" in allowed_doctypes:
		query_parts.append(f"""
			SELECT 
				'VE Sales Credit Note' AS doctype,
				'VE Sales Credit Note' AS document_type,
				doc.name,
				doc.posting_date,
				doc.customer,
				doc.customer_name,
				tc.tax_id AS customer_tax_id,
				doc.grand_total,
				doc.bill_no,
				doc.bill_control,
				doc.docstatus,
				doc.status AS raw_doc_status,
				doc.is_void,
				doc.remarks,
				doc.hka_status,
				log.status AS log_status,
				log.notes AS log_notes,
				log.creation AS log_creation
			FROM `tabVE Sales Credit Note` doc
			LEFT JOIN `tabCustomer` tc ON tc.name = doc.customer
			LEFT JOIN (
				SELECT 
					sales_invoice,
					document_type,
					status,
					notes,
					creation,
					ROW_NUMBER() OVER (PARTITION BY sales_invoice, document_type ORDER BY creation DESC) as rn
				FROM `tabVE Digital Invoice Log`
				WHERE document_type = 'VE Sales Credit Note'
			) log ON log.sales_invoice = doc.name AND log.rn = 1
			WHERE doc.docstatus IN (1, 2) AND doc.status != 'Draft' AND {cond_str}
		""")

	# 3. VE Sales Debit Note
	if "VE Sales Debit Note" in allowed_doctypes:
		query_parts.append(f"""
			SELECT 
				'VE Sales Debit Note' AS doctype,
				'VE Sales Debit Note' AS document_type,
				doc.name,
				doc.posting_date,
				doc.customer,
				doc.customer_name,
				tc.tax_id AS customer_tax_id,
				doc.grand_total,
				doc.bill_no,
				doc.bill_control,
				doc.docstatus,
				doc.status AS raw_doc_status,
				doc.is_void,
				doc.remarks,
				doc.hka_status,
				log.status AS log_status,
				log.notes AS log_notes,
				log.creation AS log_creation
			FROM `tabVE Sales Debit Note` doc
			LEFT JOIN `tabCustomer` tc ON tc.name = doc.customer
			LEFT JOIN (
				SELECT 
					sales_invoice,
					document_type,
					status,
					notes,
					creation,
					ROW_NUMBER() OVER (PARTITION BY sales_invoice, document_type ORDER BY creation DESC) as rn
				FROM `tabVE Digital Invoice Log`
				WHERE document_type = 'VE Sales Debit Note'
			) log ON log.sales_invoice = doc.name AND log.rn = 1
			WHERE doc.docstatus IN (1, 2) AND doc.status != 'Draft' AND {cond_str}
		""")

	full_query = " UNION ALL ".join(query_parts) + " ORDER BY posting_date DESC, name DESC"
	raw_data = frappe.db.sql(full_query, values, as_dict=1)

	# Semántica estricta compartida con el backfill (una sola fuente de verdad):
	# el estado solo afirma lo que HKA registró; sin evidencia -> "No aplica".
	from l10n_ve.digital_invoice.hka_status import derive_hka_status, get_hka_cutoff

	cutoff = get_hka_cutoff()

	doc_type_map = {
		"Sales Invoice": _("Factura de Venta"),
		"VE Sales Credit Note": _("Nota de Crédito"),
		"VE Sales Debit Note": _("Nota de Débito"),
	}

	invoice_status_map = {
		"Draft": _("Borrador"),
		"Submitted": _("Validada"),
		"Unpaid": _("Por Cobrar"),
		"Paid": _("Pagada"),
		"Partially Paid": _("Parcialmente Pagada"),
		"Overdue": _("Vencida"),
		"Cancelled": _("Anulada"),
		"Credit Note Issued": _("Nota de Crédito Emitida"),
		"Return": _("Devolución"),
	}

	processed_data = []
	for row in raw_data:
		# Excluir documentos en Borrador
		if row.get("docstatus") == 0 or row.get("raw_doc_status") == "Draft":
			continue

		raw_dt = row.get("doctype") or row.get("document_type")
		row["document_type"] = doc_type_map.get(raw_dt, raw_dt)

		# Preferir el campo persistido (lo mantiene el flujo en vivo);
		# derivar como fallback (sites donde el backfill aún no corrió).
		success_log = {"exists": 1} if row.get("log_status") == "Success" else None
		row["status"] = (
			row.get("hka_status")
			or derive_hka_status(row, row.get("log_status"), success_log, cutoff)
			or "No aplica"
		)

		# Aplicar filtro de estado si está presente
		if filters.get("status") and filters.get("status") not in ("All", "Todos"):
			if row["status"] != filters.get("status"):
				continue

		# Etiqueta de docstatus / Estado Factura
		raw_status = row.get("raw_doc_status")
		if raw_status in invoice_status_map:
			row["docstatus_label"] = invoice_status_map[raw_status]
		elif row.get("docstatus") == 1:
			row["docstatus_label"] = _("Validada")
		elif row.get("docstatus") == 2:
			row["docstatus_label"] = _("Anulada")
		else:
			row["docstatus_label"] = _("Borrador")

		processed_data.append(row)

	return processed_data

