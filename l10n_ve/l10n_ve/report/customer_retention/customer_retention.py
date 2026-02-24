# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data, None, None, get_report_summary(data)


def get_columns():
	"""Define las columnas que se mostrarán en el reporte."""
	return [
		{
			"fieldname": "posting_date",
			"label": _("Fecha"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "name",
			"label": _("Nombre de Documento"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 180
		},
		{
			"fieldname": "bill_no",
			"label": _("Nro. de Factura"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "bill_control",
			"label": _("Nro. Control"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "customer_name",
			"label": _("Cliente"),
			"fieldtype": "Data",
			"width": 220
		},
		{
			"fieldname": "tax_id",
			"label": _("RIF/CI"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "base_total",
			"label": _("Base Imponible"),
			"fieldtype": "Currency",
			"width": 140
		},
		{
			"fieldname": "grand_total",
			"label": _("Monto Factura"),
			"fieldtype": "Currency",
			"width": 140
		},
		{
			"fieldname": "retention_type",
			"label": _("Tipo de Retención"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "withholding_amount",
			"label": _("Monto Retenido"),
			"fieldtype": "Currency",
			"width": 140
		},
		{
			"fieldname": "voucher_number",
			"label": _("Nro. Comprobante"),
			"fieldtype": "Data",
			"width": 180
		},
		{
			"fieldname": "withholding_date",
			"label": _("Fecha Retención"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "voucher_image",
			"label": _("Imagen Comprobante"),
			"fieldtype": "Attach Image",
			"width": 120
		},
		{
			"fieldname": "retention_percentage",
			"label": _("% Retención"),
			"fieldtype": "Percent",
			"width": 100
		},
		{
			"fieldname": "description",
			"label": _("Descripción"),
			"fieldtype": "Data",
			"width": 200
		}
	]


def get_data(filters):
	"""Obtiene los datos de las facturas con retención según los filtros."""
	conditions = ""
	if filters.get("company"):
		conditions += " AND si.company = %(company)s"
	if filters.get("from_date"):
		conditions += " AND si.posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND si.posting_date <= %(to_date)s"
	if filters.get("customer"):
		conditions += " AND si.customer = %(customer)s"

	iva_query = f"""
		SELECT
			si.posting_date,	
			si.name,
			si.bill_no,
			si.bill_control,
			si.customer_name,
			si.tax_id,
			si.base_total,
			si.base_grand_total AS grand_total,
			'IVA' as retention_type,
			stc.base_tax_amount AS withholding_amount,
			si.vat_withholding_voucher_number as voucher_number,
			si.withholding_date,
			si.voucher_image,
			stc.rate AS retention_percentage,
			stc.description
		FROM
			`tabSales Invoice` AS si
		JOIN
			`tabSales Taxes and Charges` AS stc ON si.name = stc.parent
		WHERE
			si.docstatus = 1
			AND stc.charge_type = 'VAT Withholding'
			AND stc.tax_amount != 0
			{conditions}
	"""

	islr_query = f"""
		SELECT
			si.posting_date,
			si.name,
			si.bill_no,
			si.bill_control,
			si.customer_name,
			si.tax_id,
			si.base_total,
			si.base_grand_total AS grand_total,
			'ISLR' as retention_type,
			atc.tax_amount AS withholding_amount,
			si.islr_receipt_number as voucher_number,
			si.islr_date as withholding_date,
			si.voucher_image_islr as voucher_image,
			atc.rate as retention_percentage,
			atc.description
		FROM
			`tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON pe.name = per.parent
		JOIN `tabSales Invoice` si ON si.name = per.reference_name
		JOIN `tabAdvance Taxes and Charges` atc ON pe.name = atc.parent
		WHERE
			pe.docstatus = 1
			AND per.reference_doctype = 'Sales Invoice'
			AND atc.charge_type = 'ISLR'
			AND atc.tax_amount != 0
			{conditions}
	"""

	queries = []
	retention_type = filters.get("retention_type")

	if not retention_type or retention_type == "IVA":
		queries.append(iva_query)

	if not retention_type or retention_type == "ISLR":
		queries.append(islr_query)

	query = " UNION ALL ".join(queries)
	query += " ORDER BY posting_date DESC"

	data = frappe.db.sql(query, filters, as_dict=1)
	return data


def get_report_summary(data):
	if not data:
		return None

	total_base = sum(d.base_total for d in data)
	total_invoiced = sum(d.grand_total for d in data)
	total_withheld = sum(d.withholding_amount for d in data)

	return [
		{
			"value": total_base,
			"label": _("Total Base Imponible"),
			"datatype": "Currency",
		},
		{
			"value": total_invoiced,
			"label": _("Total Facturado"),
			"datatype": "Currency",
		},
		{
			"value": total_withheld,
			"label": _("Total Retenido"),
			"datatype": "Currency",
		},
	]
