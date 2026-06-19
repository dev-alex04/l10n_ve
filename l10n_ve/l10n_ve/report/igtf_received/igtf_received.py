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
	company = filters.get("company")
	sales_igtf_account = frappe.db.get_value("Company", company, "sales_igtf_account")
	igtf_rate = frappe.db.get_single_value("Venezuela Account Settings", "igtf_rate") or 3.0

	if not sales_igtf_account:
		if not company:
			company = frappe.defaults.get_user_default("company") or frappe.db.get_single_value("Global Defaults", "default_company")
			if company:
				sales_igtf_account = frappe.db.get_value("Company", company, "sales_igtf_account")
		
		if not sales_igtf_account:
			frappe.throw(_("No se ha configurado la Cuenta IGTF en ventas para la empresa {0}.").format(company))

	conditions = ""
	if company:
		conditions += " AND gle.company = %(company)s"
	if filters.get("from_date"):
		conditions += " AND gle.posting_date >= %(from_date)s"
	if filters.get("to_date"):
		conditions += " AND gle.posting_date <= %(to_date)s"

	query_params = {
		"company": company,
		"sales_igtf_account": sales_igtf_account,
		"igtf_rate": igtf_rate,
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date")
	}

	data = frappe.db.sql(f"""
		SELECT
			gle.posting_date as date,
			CASE 
				WHEN gle.voucher_type = 'Sales Invoice' THEN gle.voucher_no
				ELSE MIN(per.reference_name)
			END as invoice,
			CASE 
				WHEN gle.voucher_type = 'Sales Invoice' THEN MAX(si_direct.bill_no)
				ELSE MIN(si.bill_no)
			END as bill_no,
			MAX(c.customer_name) as customer,
			MAX(c.tax_id) as tax_id,
			CASE 
				WHEN gle.voucher_type = 'Sales Invoice' THEN MAX(si_direct.base_grand_total)
				ELSE COALESCE(MAX(si.base_grand_total), MAX(pe.paid_amount))
			END as total,
			gle.credit as igtf_amount,
			(gle.credit * 100.0 / %(igtf_rate)s) as base_igtf,
			%(igtf_rate)s as igtf_rate
		FROM
			`tabGL Entry` gle
		LEFT JOIN
			`tabPayment Entry` pe ON gle.voucher_no = pe.name AND gle.voucher_type = 'Payment Entry'
		LEFT JOIN
			`tabPayment Entry Reference` per ON pe.name = per.parent AND per.reference_doctype = 'Sales Invoice'
		LEFT JOIN
			`tabSales Invoice` si ON per.reference_name = si.name
		LEFT JOIN
			`tabSales Invoice` si_direct ON gle.voucher_no = si_direct.name AND gle.voucher_type = 'Sales Invoice'
		LEFT JOIN
			`tabCustomer` c ON COALESCE(pe.party, si_direct.customer, CASE WHEN gle.party_type = 'Customer' THEN gle.party ELSE NULL END) = c.name
		WHERE
			gle.docstatus = 1
			AND gle.account = %(sales_igtf_account)s
			AND gle.credit > 0
			{conditions}
		GROUP BY
			gle.name, gle.posting_date, gle.voucher_type, gle.voucher_no, gle.credit
		ORDER BY
			gle.posting_date DESC
	""", query_params, as_dict=True)

	return data
