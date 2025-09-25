# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days
from frappe.utils.file_manager import save_file
import json
import datetime

def get_report_summary(totals):
    """
    Returns the summary data for the top of the report.
    """
    summary = [
        {"value": totals.get("grand_total"), "label": "Total Ventas Incl. IVA", "datatype": "Currency"},
        {"value": totals.get("total_exempt"), "label": "Ventas No Gravadas", "datatype": "Currency"},
        {"value": totals.get("base_general_taxpayer") + totals.get("base_general_non_taxpayer"),
         "label": "Base Imponible General", "datatype": "Currency"},
        {"value": totals.get("iva_general_taxpayer") + totals.get("iva_general_non_taxpayer"),
         "label": "Impuesto General", "datatype": "Currency"},
        {"value": totals.get("base_reduced_taxpayer") + totals.get("base_reduced_non_taxpayer"),
         "label": "Base Imponible Reducida", "datatype": "Currency"},
        {"value": totals.get("iva_reduced_taxpayer") + totals.get("iva_reduced_non_taxpayer"),
         "label": "Impuesto Reducido", "datatype": "Currency"},
        {"value": totals.get("base_additional_taxpayer") + totals.get("base_additional_non_taxpayer"),
         "label": "Base Imponible Adicional", "datatype": "Currency"},
        {"value": totals.get("iva_additional_taxpayer") + totals.get("iva_additional_non_taxpayer"),
         "label": "Impuesto Adicional", "datatype": "Currency"},
        {"value": totals.get("iva_retained"), "label": "IVA Retenido", "datatype": "Currency"},
        {"value": totals.get("igtf_amount"), "label": "Monto IGTF", "datatype": "Currency"},

    ]

    return summary

def execute(filters=None):
    """
    Punto de entrada principal para el Reporte de Libro de Ventas.
    Devuelve las columnas y los datos basados en los filtros.
    """
    columns = get_columns()
    data = get_sales_data(filters)

    totals = get_total_row(data)

    if data:
        for i, row in enumerate(data):
            row["sequence_number"] = i + 1
    data.append(totals)

    report_summary = get_report_summary(totals)
    return columns, data, None, None, report_summary

def get_columns():
    """
    Define las columnas de la tabla del reporte. Se han simplificado las etiquetas para evitar errores en el archivo Excel.
    """
    return [

        {"label": _("Fecha"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("RIF del Cliente"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": 150},
        {"label": _("Nombre del Cliente"), "fieldname": "customer_name", "fieldtype": "Data", "width": 200},
        {"label": _("Tipo de Persona"), "fieldname": "customer_type", "fieldtype": "Data", "width": 120},
        {"label": _("Nro. de Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 150},
        {"label": _("Nro. de Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 120},
        {"label": _("Nro. de Maquina Fiscal"), "fieldname": "maquina_fiscal", "fieldtype": "Data", "width": 150},
        {"label": _("Nro. Nota de Credito"), "fieldname": "credit_note_no", "fieldtype": "Data", "width": 150},
        {"label": _("Nro. Nota de Debito"), "fieldname": "debit_note_no", "fieldtype": "Data", "width": 150},
		{"label": _("Facturas afectadas"), "fieldname": "affected_invoice_number", "fieldtype": "Data", "width": 120},
        {"label": _("Tipo de Transaccion"), "fieldname": "transaction_type", "fieldtype": "Data", "width": 150},
		{"label": _("Total Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 120},
        {"label": _("Ventas Export. FOB"), "fieldname": "ve_fob", "fieldtype": "Currency", "width": 120},
        {"label": _("Ventas internas no Gravadas"), "fieldname": "total_exempt", "fieldtype": "Currency", "width": 120},

        # Columnas para Ventas a No Contribuyentes

        {"label": _("Base Imponible No C. R"), "fieldname": "base_reduced_non_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA No C. R"), "fieldname": "iva_reduced_non_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible No C. G"), "fieldname": "base_general_non_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA No C. G"), "fieldname": "iva_general_non_taxpayer", "fieldtype": "Currency", "width": 120},
        {"label": _("Base Imponible No C. A"), "fieldname": "base_additional_non_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA No C. A"), "fieldname": "iva_additional_non_taxpayer", "fieldtype": "Currency", "width": 120},

        # Columnas para Ventas a Contribuyentes

        {"label": _("Base Imponible C. R"), "fieldname": "base_reduced_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA C. R"), "fieldname": "iva_reduced_taxpayer", "fieldtype": "Currency", "width": 120},
		{"label": _("Base Imponible C. G"), "fieldname": "base_general_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA C. G"), "fieldname": "iva_general_taxpayer", "fieldtype": "Currency", "width": 120},
        {"label": _("Base Imponible C. A"), "fieldname": "base_additional_taxpayer", "fieldtype": "Currency", "width": 150},
        {"label": _("IVA C. A"), "fieldname": "iva_additional_taxpayer", "fieldtype": "Currency", "width": 120},

        # Campos de Retencion de IVA
        {"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 120},
        {"label": _("Nro. Comprobante de Retencion IVA"), "fieldname": "vat_withholding_voucher_number", "fieldtype": "Data", "width": 150},
        {"label": _("Fecha Comprobante"), "fieldname": "withholding_date", "fieldtype": "Date", "width": 120},
        {"label": _("Tasa de Retencion IVA"), "fieldname": "vat_withholding_rate", "fieldtype": "Percent", "width": 120},

        # Columnas para IGTF Impuesto a las Grandes Transacciones Financieras
        {"label": _("Base Imponible IGTF"), "fieldname": "igtf_base", "fieldtype": "Currency", "width": 120},
        {"label": _("Tasa de IGTF"), "fieldname": "igtf_rate", "fieldtype": "Percent", "width": 120},
        {"label": _("Monto IGTF"), "fieldname": "igtf_amount", "fieldtype": "Currency", "width": 120},

    ]

def get_sales_data(filters):

	"""
	Obtiene los datos del reporte ejecutando una consulta SQL optimizada.
	"""
	try:
		tax_rates_doc = frappe.get_doc("Taxes Rates", "Taxes Rates")
		general_rate = tax_rates_doc.get("general_rate") or 16.0
		reduced_rate = tax_rates_doc.get("reduced_rate") or 8.0
		additional_rate = tax_rates_doc.get("additional_rate") or 31.0
	except frappe.DoesNotExistError:
		general_rate = 16.0
		reduced_rate = 8.0
		additional_rate = 31.0
	except Exception:
		general_rate = 16.0
		reduced_rate = 8.0
		additional_rate = 31.0

	# La consulta SQL es la parte principal de la optimización
	data = frappe.db.sql("""
		SELECT
			siv.posting_date,
			tc.tax_id AS customer_tax_id,
			siv.customer_name,
			siv.bill_no,
			siv.bill_control,
			CASE
				WHEN siv.is_return = 1 THEN 'NC'
				WHEN siv.is_debit_note = 1 THEN 'ND'
				ELSE 'REG'
			END AS transaction_type,
			CASE
				WHEN tc.customer_type = 'Company' THEN 'PJ'
				WHEN tc.customer_type = 'Individual' THEN 'PN'
				WHEN tc.customer_type = 'Partnership' THEN 'PJ'
				ELSE "N/A"
			END AS customer_type,
			siv.grand_total,
			siv.total,
			siv.total_exempt,
			siv.credit_note_no,
			siv.debit_note_no,
			siv.affected_invoice_number,
			CASE
                WHEN tc.is_special_taxpayer = 1
                     AND siv.vat_withholding_voucher_number IS NOT NULL
                     AND siv.vat_withholding_voucher_number != ''
                THEN COALESCE(ABS(tstac_retained.tax_amount), 0)
                ELSE 0
            END AS iva_retained,
            CASE
                WHEN tc.is_special_taxpayer = 1
                     AND siv.vat_withholding_voucher_number IS NOT NULL
                     AND siv.vat_withholding_voucher_number != ''
                THEN COALESCE(ABS(tstac_retained.rate), 0)
                ELSE 0
            END AS vat_withholding_rate,

			 -- Ventas a NO Contribuyentes
            CASE WHEN tc.is_special_taxpayer = 0 AND tstac_gen.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_general_non_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_gen.tax_amount, 0) ELSE 0 END AS iva_general_non_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 0 AND tstac_red.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_reduced_non_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_red.tax_amount, 0) ELSE 0 END AS iva_reduced_non_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 0 AND tstac_add.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_additional_non_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 0 THEN COALESCE(tstac_add.tax_amount, 0) ELSE 0 END AS iva_additional_non_taxpayer,

            -- Ventas a Contribuyentes
            CASE WHEN tc.is_special_taxpayer = 1 AND tstac_gen.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_general_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_gen.tax_amount, 0) ELSE 0 END AS iva_general_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 1 AND tstac_red.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_reduced_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_red.tax_amount, 0) ELSE 0 END AS iva_reduced_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 1 AND tstac_add.parent IS NOT NULL THEN (siv.total-total_exempt) ELSE 0 END AS base_additional_taxpayer,
            CASE WHEN tc.is_special_taxpayer = 1 THEN COALESCE(tstac_add.tax_amount, 0) ELSE 0 END AS iva_additional_taxpayer,

			siv.vat_withholding_voucher_number,
			siv.withholding_date,
			siv.base_grand_total AS total_in_usd

		FROM
			`tabSales Invoice` siv
		LEFT JOIN
			`tabCustomer` tc ON tc.name = siv.customer
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_ex
			ON tstac_ex.parent = siv.name AND tstac_ex.rate = 0
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_gen
			ON tstac_gen.parent = siv.name AND tstac_gen.rate = %(general_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_red
			ON tstac_red.parent = siv.name AND tstac_red.rate = %(reduced_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_add
			ON tstac_add.parent = siv.name AND tstac_add.rate = %(additional_rate)s
		LEFT JOIN
			`tabSales Taxes and Charges` tstac_retained
			ON tstac_retained.parent = siv.name AND tstac_retained.charge_type = 'VAT withholding'
		WHERE
			siv.company = %(company)s
			AND siv.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND siv.docstatus IN (1)
		ORDER BY
			siv.posting_date ASC
	""", {

		"company": filters.get("company"),
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"general_rate": general_rate,
		"reduced_rate": reduced_rate,
		"additional_rate": additional_rate
	}, as_dict=1)

	return data

def get_total_row(data):
    """
    Calcula los totales para las columnas relevantes y devuelve un diccionario,
    incluyendo el desglose de IVA retenido por alícuota.
    """
    if not data:
        return {}

    iva_retained_general = 0
    iva_retained_reduced = 0
    iva_retained_additional = 0

    totals = frappe._dict({
        "grand_total": 0,
        "exempt_amount": 0,
        "total_exempt": 0,
        "base_general_non_taxpayer": 0,
        "iva_general_non_taxpayer": 0,
        "base_reduced_non_taxpayer": 0,
        "iva_reduced_non_taxpayer": 0,
        "base_additional_non_taxpayer": 0,
        "iva_additional_non_taxpayer": 0,
        "base_general_taxpayer": 0,
        "iva_general_taxpayer": 0,
        "base_reduced_taxpayer": 0,
        "iva_reduced_taxpayer": 0,
        "base_additional_taxpayer": 0,
        "iva_additional_taxpayer": 0,
        "iva_retained": 0,
        "igtf_base": 0,
        "igtf_amount": 0,
    })

    for row in data:
        for key in totals.keys():
            if key not in ["iva_retained_general", "iva_retained_reduced", "iva_retained_additional"]:
                totals[key] += row.get(key, 0)

        ret_monto = row.get("iva_retained", 0)

        if ret_monto > 0:

            bases = {
                "general": row.get("base_general_taxpayer", 0) + row.get("base_general_non_taxpayer", 0),
                "reduced": row.get("base_reduced_taxpayer", 0) + row.get("base_reduced_non_taxpayer", 0),
                "additional": row.get("base_additional_taxpayer", 0) + row.get("base_additional_non_taxpayer", 0),
            }

            if bases["general"] >= bases["reduced"] and bases["general"] >= bases["additional"]:
                iva_retained_general += ret_monto
            elif bases["additional"] >= bases["general"] and bases["additional"] >= bases["reduced"]:
                iva_retained_additional += ret_monto
            elif bases["reduced"] > 0:
                iva_retained_reduced += ret_monto
            else:
                iva_retained_general += ret_monto

    totals["iva_retained_general"] = iva_retained_general
    totals["iva_retained_reduced"] = iva_retained_reduced
    totals["iva_retained_additional"] = iva_retained_additional

    totals.bill_no = _("TOTALES")
    return totals
