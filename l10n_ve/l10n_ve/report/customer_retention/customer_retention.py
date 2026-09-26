# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.utils import flt, get_first_day

from l10n_ve.utils.utils import get_exchange_rate
from l10n_ve.l10n_ve.report.sales_book.sales_book import (
	_FISCAL_CUTOFF_DATE,
	branch_scope_condition,
	get_branch_subtree,
	get_sales_data,
)


def execute(filters=None):
	if not filters:
		filters = {}

	if not filters.get("company"):
		frappe.throw(_("Debe seleccionar una Empresa para generar el reporte."))

	columns = get_columns()
	data = get_data(filters)
	currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
	return columns, data, None, None, get_report_summary(data, currency)


def get_columns():
	"""Define las columnas del reporte de retenciones al estilo legal."""
	return [
		{"fieldname": "posting_date", "label": _("Fecha Doc."), "fieldtype": "Date", "width": 100},
		{"fieldname": "branch", "label": _("Sucursal"), "fieldtype": "Data", "width": 120},
		{"fieldname": "doc_type", "label": _("Tipo"), "fieldtype": "Data", "width": 70},
		{"fieldname": "bill_no", "label": _("Nro. Factura"), "fieldtype": "Data", "width": 120},
		{"fieldname": "bill_control", "label": _("Nro. Control"), "fieldtype": "Data", "width": 120},
		{"fieldname": "customer_name", "label": _("Cliente"), "fieldtype": "Data", "width": 220},
		{"fieldname": "tax_id", "label": _("RIF/CI"), "fieldtype": "Data", "width": 110},
		{"fieldname": "base_total", "label": _("Base Imponible"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "grand_total", "label": _("Monto Factura"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "retention_type", "label": _("Tipo"), "fieldtype": "Data", "width": 90},
		{"fieldname": "withholding_amount", "label": _("Monto Retenido (Bs.)"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "withholding_amount_usd", "label": _("Monto Retenido (USD)"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "voucher_number", "label": _("Nro. Comprobante"), "fieldtype": "Data", "width": 150},
		{"fieldname": "registration_date", "label": _("Fecha de Registro"), "fieldtype": "Date", "width": 110},
		{"fieldname": "voucher_date", "label": _("Fecha Comprobante"), "fieldtype": "Date", "width": 110},
		{"fieldname": "bcv_rate", "label": _("Tasa BCV"), "fieldtype": "Float", "width": 100},
		{"fieldname": "retention_percentage", "label": _("% Ret."), "fieldtype": "Percent", "width": 80},
	]


def get_data(filters):
	"""
	Obtiene las retenciones consolidando Facturas, Notas de Crédito, Débito y Retenciones Gubernamentales.

	Es el detalle de las tarjetas «Retención IVA» y «Retención ISLR» del panel, que salen
	del Libro de Ventas, así que usa sus MISMAS dos reglas:

	- Sucursal: el subárbol entero (`branch_scope_condition`). Con igualdad simple, una
	  sucursal de grupo --MIR-01, sin facturas a su nombre-- daba el reporte vacío mientras
	  la tarjeta decía Bs 252.690,50 (agosto-2026). Admite selección múltiple y exclusión.
	- Período: la retención cuenta en el mes de su COMPROBANTE, como el `iva_retained` del
	  libro. Una factura del mes con comprobante fechado en otro no se cuenta aquí: el libro
	  la declara en ese otro mes, como ajuste.
	  - Para IVA: delega la consulta directamente a `sales_book.get_sales_data(sb_filters)`
	    para garantizar paridad exacta de 0,00 de diferencia con el Libro de Ventas.
	    (si.withholding_date NOT BETWEEN %(from_date)s AND %(to_date)s)
	    (nc.withholding_date NOT BETWEEN %(from_date)s AND %(to_date)s)
	  - Para ISLR: se consulta la base de datos excluyendo comprobantes fuera de rango:
	    (si.islr_date NOT BETWEEN %(from_date)s AND %(to_date)s)
	    (nc.islr_date NOT BETWEEN %(from_date)s AND %(to_date)s)
	"""
	raw_branches = filters.get("branch")
	branches = []
	if isinstance(raw_branches, str):
		if raw_branches.startswith("[") and raw_branches.endswith("]"):
			try:
				branches = json.loads(raw_branches)
			except Exception:
				branches = [raw_branches]
		elif "," in raw_branches:
			branches = [b.strip() for b in raw_branches.split(",") if b.strip()]
		elif raw_branches:
			branches = [raw_branches]
	elif isinstance(raw_branches, (list, tuple, set)):
		branches = list(raw_branches)

	branches = [b.strip() for b in branches if b and str(b).strip()]
	exclude_branches = bool(filters.get("exclude_branches"))

	ret_type_filter = filters.get("retention_type")
	include_iva = (not ret_type_filter or ret_type_filter == "IVA")
	include_islr = (not ret_type_filter or ret_type_filter == "ISLR")
	include_gov = (not ret_type_filter or ret_type_filter == "Gubernamental")
	include_nc = bool(filters.get("include_credit_notes", 1))

	if not include_iva and not include_islr and not include_gov:
		return []

	company = filters.get("company")
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	fiscal_cutoff = _FISCAL_CUTOFF_DATE

	sql_filters = dict(filters)
	sql_filters["company_currency"] = company_currency
	sql_filters["fiscal_cutoff"] = fiscal_cutoff
	sql_filters.setdefault("from_date", None)
	sql_filters.setdefault("to_date", None)

	if branches:
		resolved_branches = set()
		for b in branches:
			sub = get_branch_subtree(b)
			if sub:
				resolved_branches.update(sub)
			else:
				resolved_branches.add(b)
		sql_filters["branch_scope"] = sorted(resolved_branches) if resolved_branches else ["__ninguna__"]
	else:
		sql_filters.update(branch_scope_condition(filters.get("branch"), "branch")[1])

	rates_cache = {}
	processed_data = []

	# 1. IVA: Delegado directamente desde Sales Book
	if include_iva:
		sb_filters = dict(filters)
		if branches:
			sb_filters["branches"] = sql_filters.get("branch_scope", branches)
			sb_filters["exclude_branches"] = exclude_branches
			sb_filters.pop("branch", None)
		elif filters.get("branch"):
			subtree = get_branch_subtree(filters.get("branch"))
			if subtree:
				sb_filters["branches"] = sorted(subtree)
				sb_filters.pop("branch", None)

		main_data, _adj = get_sales_data(sb_filters)

		for r in main_data:
			iva_ret = flt(r.get("iva_retained", 0))
			if abs(iva_ret) < 0.001:
				continue

			if r.get("is_return") == 1 and not include_nc:
				continue

			is_return = r.get("is_return", 0)
			is_debit = r.get("is_debit_note", 0)
			is_void = r.get("is_void", 0)

			if is_void:
				doc_type = "ANU"
				doctype = "Sales Invoice"
			elif is_return:
				doc_type = "NC"
				doctype = "VE Sales Credit Note"
			elif is_debit:
				doc_type = "ND"
				doctype = "VE Sales Debit Note"
			else:
				doc_type = "FAC"
				doctype = "Sales Invoice"

			p_date = r.get("posting_date_sort")
			w_date = r.get("withholding_date_sort")

			base_tot = (
				flt(r.get("base_general_taxpayer", 0)) + flt(r.get("base_general_non_taxpayer", 0)) +
				flt(r.get("base_reduced_taxpayer", 0)) + flt(r.get("base_reduced_non_taxpayer", 0)) +
				flt(r.get("base_additional_taxpayer", 0)) + flt(r.get("base_additional_non_taxpayer", 0))
			)
			if abs(base_tot) < 0.001 and abs(flt(r.get("grand_total", 0))) > 0.001:
				base_tot = flt(r.get("grand_total", 0))

			ref_date = w_date or p_date
			bcv_rate = 0.0
			if ref_date:
				try:
					first_day = str(get_first_day(ref_date))
					if first_day not in rates_cache:
						rates_cache[first_day] = flt(get_exchange_rate(first_day, "USD"))
					bcv_rate = rates_cache[first_day]
				except Exception:
					bcv_rate = 0.0

			usd_amount = round(iva_ret / bcv_rate, 2) if bcv_rate > 0 else 0.0

			processed_data.append({
				"name": r.get("name"),
				"posting_date": p_date,
				"registration_date": w_date or p_date,
				"voucher_date": w_date or p_date,
				"withholding_date": w_date,
				"bill_no": r.get("bill_no") if not is_void else _("ANULADO"),
				"bill_control": r.get("bill_control"),
				"customer_name": r.get("customer_name"),
				"tax_id": r.get("customer_tax_id"),
				"branch": r.get("branch"),
				"base_total": base_tot,
				"grand_total": flt(r.get("grand_total", 0)),
				"charge_type": "VAT Withholding",
				"retention_type": "IVA",
				"retention_percentage": flt(r.get("vat_withholding_rate", 0)),
				"voucher_number": r.get("vat_withholding_voucher_number"),
				"is_void": is_void,
				"is_return": is_return,
				"is_debit_note": is_debit,
				"doctype": doctype,
				"doc_type": doc_type,
				"bcv_rate": bcv_rate,
				"withholding_amount": iva_ret,
				"withholding_amount_usd": usd_amount,
			})

	# 2. ISLR y Retenciones Gubernamentales
	def get_conditions(alias):
		conds = f" AND {alias}.company = %(company)s"
		if filters.get("from_date"):
			conds += f" AND {alias}.posting_date >= %(from_date)s"
		if filters.get("to_date"):
			conds += f" AND {alias}.posting_date <= %(to_date)s"
		if filters.get("customer"):
			conds += f" AND {alias}.customer = %(customer)s"

		if branches:
			if exclude_branches:
				conds += f" AND IFNULL({alias}.branch, '') NOT IN %(branch_scope)s"
			else:
				conds += f" AND {alias}.branch IN %(branch_scope)s"
		else:
			conds += branch_scope_condition(filters.get("branch"), f"{alias}.branch")[0]
		return conds

	other_queries = []
	if include_islr:
		other_queries.append(f"""
			SELECT 
				si.name, si.posting_date, si.bill_no, si.bill_control, si.customer_name, si.branch,
				COALESCE(NULLIF(si.tax_id, ''), c.tax_id) as tax_id,
				si.base_total, si.base_grand_total AS grand_total,
				stc.charge_type,
				CASE 
					WHEN si.posting_date <= %(fiscal_cutoff)s THEN ABS(stc.tax_amount) * (CASE WHEN si.currency != %(company_currency)s THEN si.conversion_rate ELSE 1 END) 
					ELSE 
						CASE 
							WHEN stc.charge_type = 'ISLR' AND (si.islr_receipt_number IS NULL OR si.islr_receipt_number = '') THEN 0
							WHEN stc.charge_type = 'ISLR' AND si.islr_date IS NOT NULL
							     AND si.islr_date NOT BETWEEN %(from_date)s AND %(to_date)s THEN 0
							ELSE ABS(stc.base_tax_amount) 
						END
				END AS withholding_amount,
				si.islr_receipt_number as voucher_number,
				si.islr_date as registration_date,
				COALESCE(si.islr_registration_date, si.islr_date, si.posting_date) as voucher_date,
				si.islr_date as withholding_date,
				stc.rate AS retention_percentage,
				si.is_void, 0 AS is_return, 0 AS is_debit_note, 'Sales Invoice' as doctype,
				1 AS amount_sign
			FROM `tabSales Invoice` si
			LEFT JOIN `tabCustomer` c ON si.customer = c.name
			JOIN `tabSales Taxes and Charges` stc ON si.name = stc.parent
			WHERE si.company = %(company)s AND (si.docstatus = 1 OR (si.docstatus = 2 AND si.is_void = 1))
			  AND stc.charge_type = 'ISLR' AND stc.tax_amount != 0
			  {get_conditions('si')}
		""")

		if include_nc:
			other_queries.append(f"""
				SELECT 
					nc.name, nc.posting_date, nc.bill_no, nc.bill_control, nc.customer_name, nc.branch,
					COALESCE(NULLIF(nc.tax_id, ''), c.tax_id) as tax_id,
					nc.base_total, nc.base_grand_total AS grand_total,
					stc.charge_type,
					CASE 
						WHEN nc.posting_date <= %(fiscal_cutoff)s THEN ABS(stc.tax_amount) * (CASE WHEN nc.currency != %(company_currency)s THEN nc.conversion_rate ELSE 1 END) 
						ELSE 
							CASE 
								WHEN stc.charge_type = 'ISLR' AND (nc.islr_receipt_number IS NULL OR nc.islr_receipt_number = '') THEN 0
								WHEN stc.charge_type = 'ISLR' AND nc.islr_date IS NOT NULL
								     AND nc.islr_date NOT BETWEEN %(from_date)s AND %(to_date)s THEN 0
								ELSE ABS(stc.base_tax_amount) 
							END
					END AS withholding_amount,
					nc.islr_receipt_number as voucher_number,
					COALESCE(nc.islr_date, nc.posting_date) as registration_date,
					COALESCE(nc.islr_date, nc.posting_date) as voucher_date,
					nc.islr_date as withholding_date,
					stc.rate AS retention_percentage,
					0 AS is_void, 1 AS is_return, 0 AS is_debit_note, 'VE Sales Credit Note' as doctype,
					-1 AS amount_sign
				FROM `tabVE Sales Credit Note` nc
				LEFT JOIN `tabCustomer` c ON nc.customer = c.name
				JOIN `tabSales Taxes and Charges` stc ON nc.name = stc.parent
				WHERE nc.company = %(company)s AND nc.docstatus = 1
				  AND stc.charge_type = 'ISLR' AND stc.tax_amount != 0
				  {get_conditions('nc')}
			""")

		other_queries.append(f"""
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
				nd.posting_date as registration_date,
				nd.posting_date as voucher_date,
				NULL as withholding_date,
				stc.rate AS retention_percentage,
				nd.is_void, 0 AS is_return, 1 AS is_debit_note, 'VE Sales Debit Note' as doctype,
				1 AS amount_sign
			FROM `tabVE Sales Debit Note` nd
			LEFT JOIN `tabCustomer` c ON nd.customer = c.name
			JOIN `tabSales Taxes and Charges` stc ON nd.name = stc.parent
			WHERE nd.company = %(company)s AND (nd.docstatus = 1 OR (nd.docstatus = 2 AND nd.is_void = 1))
			  AND stc.charge_type = 'ISLR' AND stc.tax_amount != 0
			  {get_conditions('nd')}
		""")

	if include_gov:
		gov_accounts = frappe.get_all(
			"Account",
			filters={"account_name": ["like", "%Gubernamental%"], "company": company},
			pluck="name"
		)
		if gov_accounts:
			sql_filters["gov_accounts"] = tuple(gov_accounts)
			je_conditions = " AND je.company = %(company)s"
			if filters.get("from_date"):
				je_conditions += " AND je.posting_date >= %(from_date)s"
			if filters.get("to_date"):
				je_conditions += " AND je.posting_date <= %(to_date)s"
			if filters.get("customer"):
				je_conditions += " AND si.customer = %(customer)s"

			if branches:
				if exclude_branches:
					je_conditions += " AND IFNULL(si.branch, '') NOT IN %(branch_scope)s"
				else:
					je_conditions += " AND si.branch IN %(branch_scope)s"
			else:
				je_conditions += branch_scope_condition(filters.get("branch"), "si.branch")[0]

			other_queries.append(f"""
				SELECT 
					si.name, si.posting_date, si.bill_no, si.bill_control, si.customer_name, si.branch,
					COALESCE(NULLIF(si.tax_id, ''), c.tax_id) as tax_id,
					si.base_total, si.base_grand_total AS grand_total,
					'Government' as charge_type,
					jec_gov.debit as withholding_amount,
					COALESCE(NULLIF(si.municipal_receipt_number, ''), 
						TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(je.user_remark, 'Comprobante N°:', -1), '-', 1)),
						je.name
					) as voucher_number,
					je.posting_date as registration_date,
					COALESCE(si.municipal_registration_date, si.municipal_date, je.posting_date) as voucher_date,
					je.posting_date as withholding_date,
					CASE 
						WHEN si.base_total > 0 THEN ROUND((jec_gov.debit / si.base_total) * 100, 2)
						ELSE 0.0 
					END as retention_percentage,
					si.is_void, 0 AS is_return, 0 AS is_debit_note, 'Sales Invoice' as doctype,
					1 AS amount_sign
				FROM `tabJournal Entry` je
				JOIN `tabJournal Entry Account` jec_gov ON je.name = jec_gov.parent
				JOIN `tabJournal Entry Account` jec_inv ON je.name = jec_inv.parent
				JOIN `tabSales Invoice` si ON jec_inv.reference_name = si.name
				LEFT JOIN `tabCustomer` c ON si.customer = c.name
				WHERE je.docstatus = 1
				  AND jec_inv.reference_type = 'Sales Invoice'
				  AND jec_gov.account IN %(gov_accounts)s
				  {je_conditions}
			""")

	if other_queries:
		query = f"""
			SELECT * FROM (
				{" UNION ALL ".join(other_queries)}
			) AS combined
			ORDER BY posting_date DESC, name DESC
		"""
		raw_other = frappe.db.sql(query, sql_filters, as_dict=1)
		for d in raw_other:
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
			d["base_total"] = flt(d.get("base_total", 0)) * sign * (1 - is_void)
			d["grand_total"] = flt(d.get("grand_total", 0)) * sign * (1 - is_void)
			d["withholding_amount"] = flt(d.get("withholding_amount", 0)) * sign * (1 - is_void)

			if flt(d["withholding_amount"]) == 0.0:
				continue

			ct = d.get("charge_type")
			if ct == "VAT Withholding":
				d["retention_type"] = "IVA"
			elif ct == "ISLR":
				d["retention_type"] = "ISLR"
			else:
				d["retention_type"] = "Gubernamental"

			ref_date = d.get("registration_date") or d.get("voucher_date") or d.get("posting_date")
			bcv_rate = 0.0
			if ref_date:
				try:
					first_day = str(get_first_day(ref_date))
					if first_day not in rates_cache:
						rates_cache[first_day] = flt(get_exchange_rate(first_day, "USD"))
					bcv_rate = rates_cache[first_day]
				except Exception:
					bcv_rate = 0.0

			d["bcv_rate"] = bcv_rate
			d["withholding_amount_usd"] = flt(d["withholding_amount"] / bcv_rate, 2) if bcv_rate > 0 else 0.0
			processed_data.append(d)

	processed_data.sort(key=lambda x: (str(x.get("posting_date") or ""), str(x.get("name") or "")), reverse=True)
	return processed_data


def get_report_summary(data, currency=None):
	"""Totales en la moneda de la empresa y equivalente en USD."""
	if not data:
		return []

	total_base = sum(flt(d.get("base_total", 0)) for d in data)
	total_invoiced = sum(flt(d.get("grand_total", 0)) for d in data)
	total_withheld = sum(flt(d.get("withholding_amount", 0)) for d in data)
	total_withheld_usd = sum(flt(d.get("withholding_amount_usd", 0)) for d in data)

	summary = [
		{"value": total_base, "label": _("Total Base Imponible"), "datatype": "Currency", "currency": currency},
		{"value": total_invoiced, "label": _("Total Facturado"), "datatype": "Currency", "currency": currency},
		{"value": total_withheld, "label": _("Total Retenido (Bs.)"), "datatype": "Currency", "currency": currency, "indicator": "Red"},
	]

	if any(flt(d.get("withholding_amount_usd", 0)) != 0 for d in data):
		summary.append(
			{"value": total_withheld_usd, "label": _("Total Retenido (USD)"), "datatype": "Currency", "currency": "USD", "indicator": "Blue"}
		)

	return summary
