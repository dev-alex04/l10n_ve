# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	if not filters:
		filters = {}

	if not filters.get("company"):
		frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, None, get_report_summary(data)


def get_columns():
	"""Define las columnas del reporte de retenciones al estilo legal."""
	return [
		{"fieldname": "posting_date", "label": _("Fecha Doc."), "fieldtype": "Date", "width": 100},
		{"fieldname": "branch", "label": _("Sucursal"), "fieldtype": "Data", "width": 120},
		{"fieldname": "doc_type", "label": _("Tipo"), "fieldtype": "Data", "width": 60},
		{"fieldname": "bill_no", "label": _("Nro. Factura"), "fieldtype": "Data", "width": 120},
		{"fieldname": "bill_control", "label": _("Nro. Control"), "fieldtype": "Data", "width": 120},
		{"fieldname": "customer_name", "label": _("Cliente"), "fieldtype": "Data", "width": 220},
		{"fieldname": "tax_id", "label": _("RIF/CI"), "fieldtype": "Data", "width": 110},
		{"fieldname": "base_total", "label": _("Base Imponible"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "grand_total", "label": _("Monto Factura"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "retention_type", "label": _("Tipo"), "fieldtype": "Data", "width": 80},
		{"fieldname": "withholding_amount", "label": _("Monto Retenido"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "voucher_number", "label": _("Nro. Comprobante"), "fieldtype": "Data", "width": 150},
		{"fieldname": "withholding_date", "label": _("Fecha Retención"), "fieldtype": "Date", "width": 100},
		{"fieldname": "retention_percentage", "label": _("% Ret."), "fieldtype": "Percent", "width": 80},
	]


def get_data(filters):
	"""
	Obtiene las retenciones consolidando Facturas, Notas de Crédito y Débito.
	Alineado con la lógica del Libro de Ventas legal.
	"""
	# Función auxiliar para construir condiciones con alias específicos
	def get_conditions(alias):
		conds = f" AND {alias}.company = %(company)s"
		if filters.get("from_date"):
			conds += f" AND {alias}.posting_date >= %(from_date)s"
		if filters.get("to_date"):
			conds += f" AND {alias}.posting_date <= %(to_date)s"
		if filters.get("customer"):
			conds += f" AND {alias}.customer = %(customer)s"
		if filters.get("branch"):
			conds += f" AND {alias}.branch = %(branch)s"
		return conds

	# Tipos de retención a consultar
	ret_type_filter = filters.get("retention_type")
	charge_types = []
	if not ret_type_filter or ret_type_filter == "IVA":
		charge_types.append("'VAT Withholding'")
	if not ret_type_filter or ret_type_filter == "ISLR":
		charge_types.append("'ISLR'")
	
	if not charge_types:
		return []

	charge_types_str = ", ".join(charge_types)

	company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	fiscal_cutoff = '2026-04-15'
	filters["company_currency"] = company_currency
	filters["fiscal_cutoff"] = fiscal_cutoff

	# Query unificado para todas las fuentes
	query = f"""
		SELECT * FROM (
			-- FUENTE A: Sales Invoices
			SELECT 
				si.name, si.posting_date, si.bill_no, si.bill_control, si.customer_name, si.branch,
				COALESCE(NULLIF(si.tax_id, ''), c.tax_id) as tax_id,
				si.base_total, si.base_grand_total AS grand_total,
				stc.charge_type,
				CASE 
					WHEN si.posting_date <= %(fiscal_cutoff)s THEN ABS(stc.tax_amount) * (CASE WHEN si.currency != %(company_currency)s THEN si.conversion_rate ELSE 1 END) 
					ELSE 
						CASE 
							WHEN stc.charge_type = 'VAT Withholding' AND (si.vat_withholding_voucher_number IS NULL OR si.vat_withholding_voucher_number = '') THEN 0
							WHEN stc.charge_type = 'ISLR' AND (si.islr_receipt_number IS NULL OR si.islr_receipt_number = '') THEN 0
							ELSE ABS(stc.base_tax_amount) 
						END
				END AS withholding_amount,
				CASE WHEN stc.charge_type = 'VAT Withholding' THEN si.vat_withholding_voucher_number ELSE si.islr_receipt_number END as voucher_number,
				CASE WHEN stc.charge_type = 'VAT Withholding' THEN si.withholding_date ELSE si.islr_date END as withholding_date,
				stc.rate AS retention_percentage,
				si.is_void, 0 AS is_return, 0 AS is_debit_note, 'Sales Invoice' as doctype,
				1 AS amount_sign
			FROM `tabSales Invoice` si
			LEFT JOIN `tabCustomer` c ON si.customer = c.name
			JOIN `tabSales Taxes and Charges` stc ON si.name = stc.parent
			WHERE si.company = %(company)s AND (si.docstatus = 1 OR (si.docstatus = 2 AND si.is_void = 1))
			  AND stc.charge_type IN ({charge_types_str}) AND stc.tax_amount != 0
			  {get_conditions('si')}

			UNION ALL

			-- FUENTE B: Credit Notes
			SELECT 
				nc.name, nc.posting_date, nc.bill_no, nc.bill_control, nc.customer_name, nc.branch,
				COALESCE(NULLIF(nc.tax_id, ''), c.tax_id) as tax_id,
				nc.base_total, nc.base_grand_total AS grand_total,
				stc.charge_type,
				CASE 
					WHEN nc.posting_date <= %(fiscal_cutoff)s THEN ABS(stc.tax_amount) * (CASE WHEN nc.currency != %(company_currency)s THEN nc.conversion_rate ELSE 1 END) 
					ELSE 
						CASE 
							WHEN stc.charge_type = 'VAT Withholding' AND (nc.vat_withholding_voucher_number IS NULL OR nc.vat_withholding_voucher_number = '') THEN 0
							WHEN stc.charge_type = 'ISLR' AND (nc.islr_receipt_number IS NULL OR nc.islr_receipt_number = '') THEN 0
							ELSE ABS(stc.base_tax_amount) 
						END
				END AS withholding_amount,
				CASE WHEN stc.charge_type = 'VAT Withholding' THEN nc.vat_withholding_voucher_number ELSE nc.islr_receipt_number END as voucher_number,
				CASE WHEN stc.charge_type = 'VAT Withholding' THEN nc.withholding_date ELSE nc.islr_date END as withholding_date,
				stc.rate AS retention_percentage,
				0 AS is_void, 1 AS is_return, 0 AS is_debit_note, 'VE Sales Credit Note' as doctype,
				-1 AS amount_sign
			FROM `tabVE Sales Credit Note` nc
			LEFT JOIN `tabCustomer` c ON nc.customer = c.name
			JOIN `tabSales Taxes and Charges` stc ON nc.name = stc.parent
			WHERE nc.company = %(company)s AND nc.docstatus = 1
			  AND stc.charge_type IN ({charge_types_str}) AND stc.tax_amount != 0
			  {get_conditions('nc')}

			UNION ALL

			-- FUENTE C: Notas de Débito
			SELECT 
				nd.name, nd.posting_date, nd.bill_no, nd.bill_control, nd.customer_name, nd.branch,
				COALESCE(NULLIF(nd.tax_id, ''), c.tax_id) as tax_id,
				nd.base_total, nd.base_grand_total AS grand_total,
				stc.charge_type,
				CASE 
					WHEN nd.posting_date <= %(fiscal_cutoff)s THEN ABS(stc.tax_amount) * (CASE WHEN nd.currency != %(company_currency)s THEN nd.conversion_rate ELSE 1 END) 
					ELSE ABS(stc.base_tax_amount)
				END AS withholding_amount,
				NULL as voucher_number,
				NULL as withholding_date,
				stc.rate AS retention_percentage,
				nd.is_void, 0 AS is_return, 1 AS is_debit_note, 'VE Sales Debit Note' as doctype,
				1 AS amount_sign
			FROM `tabVE Sales Debit Note` nd
			LEFT JOIN `tabCustomer` c ON nd.customer = c.name
			JOIN `tabSales Taxes and Charges` stc ON nd.name = stc.parent
			WHERE nd.company = %(company)s AND (nd.docstatus = 1 OR (nd.docstatus = 2 AND nd.is_void = 1))
			  AND stc.charge_type IN ({charge_types_str}) AND stc.tax_amount != 0
			  {get_conditions('nd')}
		) AS combined
		ORDER BY posting_date DESC, name DESC
	"""

	raw_data = frappe.db.sql(query, filters, as_dict=1)
	
	processed_data = []
	for d in raw_data:
		# Lógica para siglas de tipo de documento
		is_void = d.get("is_void")
		if is_void:
			d["doc_type"] = "ANU"
		elif d.get("is_debit_note"):
			d["doc_type"] = "ND"
		elif d.get("is_return"):
			d["doc_type"] = "NC"
		else:
			d["doc_type"] = "FAC"

		sign = d.get("amount_sign", 1)
		
		d["bill_no"] = d.get("bill_no") if not is_void else _("ANULADO")
		
		# Ajustar montos finales
		d["base_total"] = flt(d.get("base_total", 0)) * sign * (1 - is_void)
		d["grand_total"] = flt(d.get("grand_total", 0)) * sign * (1 - is_void)
		d["withholding_amount"] = flt(d.get("withholding_amount", 0)) * sign * (1 - is_void)
		
		# Si la retención tiene un saldo de 0 bolívares, no se incluye en la lista
		if flt(d["withholding_amount"]) == 0.0:
			continue
			
		d["retention_type"] = "IVA" if d.get("charge_type") == "VAT Withholding" else "ISLR"
		
		processed_data.append(d)

	return processed_data


def get_report_summary(data):
	if not data:
		return []

	total_base = sum(flt(d.get("base_total", 0)) for d in data)
	total_invoiced = sum(flt(d.get("grand_total", 0)) for d in data)
	total_withheld = sum(flt(d.get("withholding_amount", 0)) for d in data)

	return [
		{"value": total_base, "label": _("Total Base Imponible"), "datatype": "Currency"},
		{"value": total_invoiced, "label": _("Total Facturado"), "datatype": "Currency"},
		{"value": total_withheld, "label": _("Total Retenido"), "datatype": "Currency", "indicator": "Red"},
	]
