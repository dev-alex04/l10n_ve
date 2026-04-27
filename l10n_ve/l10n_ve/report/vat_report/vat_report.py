# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from datetime import date
import calendar
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data

def execute(filters=None):
	if not filters:
		filters = {}

	from_date, to_date = _get_date_range_from_filters(filters)
	if from_date and to_date:
		filters["from_date"] = from_date
		filters["to_date"] = to_date

	if not filters.get("company"):
		frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

	main_data, adjustment_data = get_sales_data(filters)

	columns = get_columns()
	
	data = get_data(main_data)
	
	report_summary = get_report_summary(data)

	return columns, data, None, None, report_summary


def get_columns():
	"""Columnas para el reporte de control de IVA."""
	return [
		{"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Data", "width": 100},
		{"label": _("Sucursal"), "fieldname": "branch", "fieldtype": "Data", "width": 120},
		{"label": _("Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": 250},
		{"label": _("RIF / CI"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": 120},
		{"label": _("Tipo"), "fieldname": "document_type", "fieldtype": "Data", "width": 60},
		{"label": _("Nro. Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 120},
		{"label": _("Nro. Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 120},
		{"label": _("Monto de la base"), "fieldname": "taxable_base", "fieldtype": "Currency", "width": 140},
		{"label": _("Total IVA"), "fieldname": "tax_amount", "fieldtype": "Currency", "width": 140},
		{"label": _("Total"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 140},
	]


def get_data(main_data):
	"""Genera un listado detallado de las facturas del período."""
	rows = []

	for row in main_data:
		if row.get("is_void"):
			doc_type = "ANU"
		elif row.get("is_debit_note"):
			doc_type = "ND"
		elif row.get("is_return"):
			doc_type = "NC"
		else:
			doc_type = "FAC"

		if row.get("is_debit_note"):
			doctype_name = "VE Sales Debit Note"
		elif row.get("is_return"):
			doctype_name = "VE Sales Credit Note"
		else:
			doctype_name = "Sales Invoice"

		if row.get("is_void"):
			rows.append({
				"posting_date": row.get("posting_date"),
				"branch": row.get("branch"),
				"customer_name": "<b>" + _("ANULADO") + "</b>",
				"customer_tax_id": row.get("customer_tax_id"),
				"document_type": doc_type,
				"bill_no": _("ANULADO"),
				"bill_control": row.get("bill_control"),
				"taxable_base": 0,
				"tax_amount": 0,
				"grand_total": 0,
				"name": row.get("name"),
				"doctype_link": doctype_name,
				"is_void": 1,
				"is_return": 0
			})
			continue

		base = flt(row.get("base_general_taxpayer", 0) + row.get("base_general_non_taxpayer", 0) +
				   row.get("base_reduced_taxpayer", 0) + row.get("base_reduced_non_taxpayer", 0) +
				   row.get("base_additional_taxpayer", 0) + row.get("base_additional_non_taxpayer", 0) +
				   row.get("total_exempt", 0))
		
		iva = flt(row.get("iva_general_taxpayer", 0) + row.get("iva_general_non_taxpayer", 0) +
				  row.get("iva_reduced_taxpayer", 0) + row.get("iva_reduced_non_taxpayer", 0) +
				  row.get("iva_additional_taxpayer", 0) + row.get("iva_additional_non_taxpayer", 0))
		
		total = flt(row.get("grand_total", 0))

		rows.append({
			"posting_date": row.get("posting_date"),
			"branch": row.get("branch"),
			"customer_name": row.get("customer_name"),
			"customer_tax_id": row.get("customer_tax_id"),
			"document_type": doc_type,
			"bill_no": row.get("bill_no"),
			"bill_control": row.get("bill_control"),
			"taxable_base": base,
			"tax_amount": iva,
			"grand_total": total,
			"name": row.get("name"),
			"doctype_link": doctype_name,
			"is_void": row.get("is_void"),
			"is_return": row.get("is_return")
		})

	return rows


def get_report_summary(data):
	"""Extrae los totales del período para el dashboard superior."""
	if not data: return []
	
	total_base = sum(flt(row.get("taxable_base", 0)) for row in data if not row.get("is_void"))
	total_iva = sum(flt(row.get("tax_amount", 0)) for row in data if not row.get("is_void"))

	return [
		{
			"value": total_base,
			"label": _("Monto de la Base"),
			"datatype": "Currency",
			"indicator": "Blue"
		},
		{
			"value": total_iva,
			"label": _("Total IVA"),
			"datatype": "Currency",
			"indicator": "Red"
		}
	]


def _get_date_range_from_filters(filters):
	"""Helper para convertir selección de Año/Mes en rango de fechas."""
	from_date = filters.get("from_date")
	to_date = filters.get("to_date")
	fiscal_year = filters.get("fiscal_year")
	fiscal_month_name = filters.get("fiscal_month")

	if fiscal_year and fiscal_month_name:
		try:
			year = int(fiscal_year)
			month_mapping = {
				'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6,
				'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12
			}
			month_num = month_mapping.get(fiscal_month_name)
			if month_num:
				from_date = date(year, month_num, 1).strftime('%Y-%m-%d')
				last_day = calendar.monthrange(year, month_num)[1]
				to_date = date(year, month_num, last_day).strftime('%Y-%m-%d')
		except (ValueError, TypeError, KeyError):
			pass
			
	return from_date, to_date
