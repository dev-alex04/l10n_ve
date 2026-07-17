# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from datetime import datetime


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)

	total_invoice = 0.0
	total_base_igtf = 0.0
	total_igtf = 0.0

	for row in data:
		total_invoice += row.get("total") or 0.0
		total_base_igtf += row.get("base_igtf") or 0.0
		total_igtf += row.get("igtf_amount") or 0.0

	report_summary = [
		{
			"value": len(data),
			"label": _("Número total de operaciones"),
			"datatype": "Int",
		},
		{
			"value": total_invoice,
			"label": _("Total Facturado"),
			"datatype": "Currency",
		},
		{
			"value": total_base_igtf,
			"label": _("Total Base IGTF"),
			"datatype": "Currency",
		},
		{
			"value": total_igtf,
			"label": _("Total IGTF"),
			"datatype": "Currency",
		}
	]

	return columns, data, None, None, report_summary


def get_columns():
	return [
		{
			"fieldname": "date",
			"label": _("Fecha"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "invoice",
			"label": _("Factura"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 140
		},
		{
			"fieldname": "bill_no",
			"label": _("Nro. Factura"),
			"fieldtype": "Data",
			"width": 140
		},
		{
			"fieldname": "customer",
			"label": _("Cliente"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 200
		},
		{
			"fieldname": "tax_id",
			"label": _("Documento"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "total",
			"label": _("Monto De Factura"),
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"fieldname": "base_igtf",
			"label": _("Monto Sujeto"),
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"fieldname": "igtf_rate",
			"label": _("% IGTF"),
			"fieldtype": "Percent",
			"width": 80
		},
		{
			"fieldname": "igtf_amount",
			"label": _("Monto IGTF"),
			"fieldtype": "Currency",
			"width": 120
		}
	]


def get_data(filters):
	"""Construye los datos del reporte usando EXACTAMENTE la misma fuente que el
	Libro de Ventas (sales_book.get_sales_data), de modo que el IGTF percibido
	cuadre al céntimo con el IGTF mostrado en el Libro de Ventas.

	Antes este reporte leía los créditos de la cuenta IGTF en el libro mayor
	(tabGL Entry). Eso generaba diferencias respecto al Libro de Ventas porque:
	  - contabilizaba IGTF de comprobantes anulados (cuyo reverso es un débito),
	  - duplicaba cuando una factura se pagaba en varios abonos,
	  - e ignoraba que el Libro de Ventas usa el campo total_igtf de la factura.
	Ahora se reusa la consulta del Libro de Ventas para garantizar paridad total.
	"""
	from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data

	main_data, adjustment_data = get_sales_data(filters)
	rows = main_data + adjustment_data

	data = []
	for row in rows:
		total_igtf = flt(row.get("total_igtf") or 0.0)
		base_igtf = flt(row.get("base_amount_igtf") or 0.0)

		# Solo incluir documentos que efectivamente tengan IGTF.
		# (El Libro de Ventas deja en 0 el IGTF de facturas anuladas, así que
		# al filtrar por ~0 se excluyen automáticamente y se mantiene la paridad.)
		if abs(total_igtf) < 0.001 and abs(base_igtf) < 0.001:
			continue

		posting_date = row.get("posting_date")
		# get_sales_data devuelve posting_date como texto DD/MM/YYYY; lo
		# normalizamos a date para la columna Date del reporte.
		if isinstance(posting_date, str) and "/" in posting_date:
			try:
				posting_date = datetime.strptime(posting_date, "%d/%m/%Y").date()
			except ValueError:
				pass

		data.append({
			"date": posting_date,
			"invoice": row.get("name"),
			"bill_no": row.get("bill_no"),
			"customer": row.get("customer_name"),
			"tax_id": row.get("customer_tax_id"),
			"total": flt(row.get("grand_total") or 0.0),
			"base_igtf": base_igtf,
			"igtf_rate": row.get("igtf_rate") or 0,
			"igtf_amount": total_igtf,
		})

	return data
