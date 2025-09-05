# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

# import frappe

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days

def execute(filters=None):
	"""
	Punto de entrada principal para el Reporte de Libro de Ventas.
	Devuelve las columnas y los datos basados en los filtros.
	"""
	columns = get_columns()
	data = get_sales_data(filters)
	return columns, data

def get_columns():
	"""
	Define las columnas de la tabla del reporte.
	"""
	return [
		{"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Nombre del Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
		{"label": _("Nro. de Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 150},
		{"label": _("Nro. de Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 120},
		{"label": _("Nro. Nota de Crédito"), "fieldname": "credit_note_no", "fieldtype": "Data", "width": 150},
		{"label": _("Nro. Nota de Débito"), "fieldname": "debit_note_no", "fieldtype": "Data", "width": 150},
		{"label": _("Total Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
		{"label": _("Ventas Exoneradas"), "fieldname": "exempt_amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible (G)"), "fieldname": "base_general", "fieldtype": "Currency", "width": 120},
		{"label": _("IVA (G)"), "fieldname": "iva_general", "fieldtype": "Currency", "width": 100},
		{"label": _("Base Imponible (R)"), "fieldname": "base_reduced", "fieldtype": "Currency", "width": 120},
		{"label": _("IVA (R)"), "fieldname": "iva_reduced", "fieldtype": "Currency", "width": 100},
		{"label": _("Base Imponible (A)"), "fieldname": "base_additional", "fieldtype": "Currency", "width": 120},
		{"label": _("IVA (A)"), "fieldname": "iva_additional", "fieldtype": "Currency", "width": 100},
		{"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 120},
	]

def get_sales_data(filters):
	"""
	Obtiene los datos del reporte ejecutando una consulta SQL optimizada.
	"""
	try:
		tax_rates = frappe.get_doc("Tax Rates", "Tax Rates")
		general_rate = tax_rates.general_rate
		reduced_rate = tax_rates.reduced_rate
		additional_rate = tax_rates.additional_rate
	except Exception:
		general_rate = 16.0
		reduced_rate = 8.0
		additional_rate = 31.0
	
	# La consulta SQL es la parte principal de la optimización
	data = frappe.db.sql("""
		SELECT
			tsi.posting_date,
			tsi.customer_name,
			tsi.bill_no,
			tsi.bill_control,
			NULL AS credit_note_no,
			NULL AS debit_note_no,
			tsi.grand_total,
			COALESCE(tstac_ex.base_tax_amount, 0) AS exempt_amount,
			COALESCE(tstac_gen.base_tax_amount, 0) AS base_general,
			COALESCE(tstac_gen.tax_amount, 0) AS iva_general,
			COALESCE(tstac_red.base_tax_amount, 0) AS base_reduced,
			COALESCE(tstac_red.tax_amount, 0) AS iva_reduced,
			COALESCE(tstac_add.base_tax_amount, 0) AS base_additional,
			COALESCE(tstac_add.tax_amount, 0) AS iva_additional,
			COALESCE(ABS(tstac_retained.tax_amount), 0) AS iva_retained
		FROM
			`tabSales Invoice` tsi
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_ex
			ON tstac_ex.parent = tsi.name AND tstac_ex.rate = 0
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_gen
			ON tstac_gen.parent = tsi.name AND tstac_gen.rate = %(general_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_red
			ON tstac_red.parent = tsi.name AND tstac_red.rate = %(reduced_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_add
			ON tstac_add.parent = tsi.name AND tstac_add.rate = %(additional_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_retained
			ON tstac_retained.parent = tsi.name AND tstac_retained.tax_amount < 0
		WHERE
			tsi.company = %(company)s
			AND tsi.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND tsi.docstatus IN (1, 2)
		ORDER BY
			tsi.posting_date ASC
	""", {
		"company": filters.get("company"),
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"general_rate": general_rate,
		"reduced_rate": reduced_rate,
		"additional_rate": additional_rate
	}, as_dict=1)

	return data