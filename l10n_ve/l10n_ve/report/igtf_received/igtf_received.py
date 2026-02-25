# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _


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
			"label": _("RIF"),
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
	conditions = ""
	if filters.get("company"):
		conditions += " AND si.company = %(company)s"
	if filters.get("from_date"):
		conditions += " AND si.posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND si.posting_date <= %(to_date)s"

	data = frappe.db.sql("""
		SELECT
			si.posting_date as date,
			si.name as invoice,
			si.bill_no as bill_no,
			si.customer_name as customer,
			COALESCE(NULLIF(si.tax_id, ''), c.tax_id) as tax_id,
			si.base_grand_total as total,
			si.base_amount_igtf as base_igtf,
			si.total_igtf as igtf_amount
		FROM
			`tabSales Invoice` si
		LEFT JOIN
			`tabCustomer` c ON si.customer = c.name
		WHERE
			si.docstatus = 1
			AND si.total_igtf > 0
			{conditions}
		ORDER BY
			si.posting_date DESC
	""".format(conditions=conditions), filters, as_dict=1)

	for row in data:
		if row.get("base_igtf") and row.get("igtf_amount"):
			row["igtf_rate"] = (row["igtf_amount"] / row["base_igtf"]) * 100
		else:
			row["igtf_rate"] = 0.0

	return data
