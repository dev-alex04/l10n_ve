# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	if not filters.get("company"):
		frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

	frappe.has_permission("Company", "read", doc=filters.get("company"), throw=True)

	doctypes_to_check = ["Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note"] if not filters.get("document_type") or filters.get("document_type") == "All" else [filters.get("document_type")]
	for dt in doctypes_to_check:
		frappe.has_permission(dt, "read", throw=True)

	columns = get_columns()
	data = get_data(filters)

	# Sumarizar los datos en el resumen del reporte
	total_docs = len(data)
	total_emitida = sum(1 for row in data if row.get("status") == "Emitida")
	total_error = sum(1 for row in data if row.get("status") == "Error")
	total_pendiente = sum(1 for row in data if row.get("status") == "Pendiente")

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
		}
	]

	return columns, data, None, None, report_summary


def get_columns():
	return [
		{
			"fieldname": "document_type",
			"label": _("Tipo de Documento"),
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "name",
			"label": _("ID Documento"),
			"fieldtype": "Dynamic Link",
			"options": "document_type",
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
			"label": _("RIF Cliente"),
			"fieldtype": "Data",
			"width": 120
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
			"label": _("Estado Documento"),
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
	target_doctype = filters.get("document_type") or "All"

	# 1. Sales Invoice
	if target_doctype in ("All", "Sales Invoice"):
		query_parts.append(f"""
			SELECT 
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
			WHERE doc.docstatus IN (1, 2) AND {cond_str}
		""")

	# 2. VE Sales Credit Note
	if target_doctype in ("All", "VE Sales Credit Note"):
		query_parts.append(f"""
			SELECT 
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
			WHERE doc.docstatus IN (1, 2) AND {cond_str}
		""")

	# 3. VE Sales Debit Note
	if target_doctype in ("All", "VE Sales Debit Note"):
		query_parts.append(f"""
			SELECT 
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
			WHERE doc.docstatus IN (1, 2) AND {cond_str}
		""")

	full_query = " UNION ALL ".join(query_parts) + " ORDER BY posting_date DESC, name DESC"
	raw_data = frappe.db.sql(full_query, values, as_dict=1)

	processed_data = []
	for row in raw_data:
		# Determinar estado de HKA
		if row.get("bill_control"):
			row["status"] = "Emitida"
		elif row.get("log_status") == "Error":
			row["status"] = "Error"
		else:
			row["status"] = "Pendiente"

		# Aplicar filtro de estado si está presente
		if filters.get("status") and filters.get("status") != "All":
			if row["status"] != filters.get("status"):
				continue

		# Etiqueta de docstatus
		if row.get("docstatus") == 1:
			row["docstatus_label"] = _("Sometido")
		elif row.get("docstatus") == 2:
			row["docstatus_label"] = _("Anulado")
		else:
			row["docstatus_label"] = _("Borrador")

		processed_data.append(row)

	return processed_data
