# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _, throw
from frappe.utils import flt, getdate, format_date
from collections import defaultdict
import calendar
from datetime import date
from io import StringIO
import json
import re

def get_report_summary(totals):
    summary = [
        {
            "value": totals.get("grand_total"),
            "label": "Total Compras",
            "datatype": "Currency"
        },
        {
            "value": totals.get("compras_sin_credito"),
            "label": "Total Compras Sin Crédito",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_reducida"),
            "label": "Total Base Reducida",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_reducida"),
            "label": "Total Impuesto Reducido",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_general"),
            "label": "Total Base General",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_general"),
            "label": "Total Impuesto 16%",
            "datatype": "Currency"
        },
        {
            "value": totals.get("base_adicional"),
            "label": "Total Base Adicional",
            "datatype": "Currency"
        },
        {
            "value": totals.get("impuesto_adicional"),
            "label": "Total Impuesto 31%",
            "datatype": "Currency"
        },
        {
            "value": totals.get("taxes_and_charges_deducted"),
            "label": "Total IVA Retenido",
            "datatype": "Currency"
        },
    ]
    
    return summary

def get_totals_from_data(data):
    # Inicializar los contadores
    grand_total = 0
    compras_sin_credito = 0
    base_reducida = 0
    impuesto_reducida = 0
    base_general = 0
    impuesto_general = 0
    base_adicional = 0
    impuesto_adicional = 0
    taxes_and_charges_deducted = 0

    # Iterar sobre cada fila de la data
    for row in data:
        grand_total += row.get("grand_total", 0)
        compras_sin_credito += row.get("compras_sin_credito", 0)
        base_reducida += row.get("base_reducida", 0)
        impuesto_reducida += row.get("impuesto_reducida", 0)
        base_general += row.get("base_general", 0)
        impuesto_general += row.get("impuesto_general", 0)
        base_adicional += row.get("base_adicional", 0)
        impuesto_adicional += row.get("impuesto_adicional", 0)
        taxes_and_charges_deducted += row.get("taxes_and_charges_deducted", 0)

    # Retornar un diccionario con los totales
    return {
        "grand_total": grand_total,
        "compras_sin_credito": compras_sin_credito,
        "base_reducida": base_reducida,
        "impuesto_reducida": impuesto_reducida,
        "base_general": base_general,
        "impuesto_general": impuesto_general,
        "base_adicional": base_adicional,
        "impuesto_adicional": impuesto_adicional,
        "taxes_and_charges_deducted": taxes_and_charges_deducted,
    }

def get_processed_data(filters):
    conditions = "AND tPI.docstatus = 1"
    values = {}

    if filters.get("fiscal_year") and filters.get("fiscal_month"):
        year = int(filters.fiscal_year)
        month = int(filters.fiscal_month)
        last_day = calendar.monthrange(year, month)[1]
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

        conditions += " AND tPI.posting_date BETWEEN %(start_date)s AND %(end_date)s"
        values["start_date"] = start_date
        values["end_date"] = end_date

    if filters.get("company"):
        conditions += " AND tPI.company = %(company)s"
        values["company"] = filters.get("company")

    query = f"""
        SELECT
            tPI.name as nro_factura,
            tPI.posting_date as posting_date,
            T4.tax_id as tax_id,
            tPI.supplier_name as supplier_name,
            tPI.is_return as is_return,
            tPI.bill_no as bill_no,
            tPI.bill_control as bill_control,
            tPI.grand_total as grand_total,
            tPI.return_against as facturas_afectadas,
            tPI.grand_total as total,
            SUM(CASE WHEN T5.rate = 8 THEN tPI.total ELSE 0 END) as base_reducida,
            SUM(CASE WHEN T5.rate = 8 THEN T5.tax_amount ELSE 0 END) as impuesto_reducida,
            SUM(CASE WHEN T5.rate = 16 THEN tPI.total ELSE 0 END) as base_general,
            SUM(CASE WHEN T5.rate = 16 THEN T5.tax_amount ELSE 0 END) as impuesto_general,
            SUM(CASE WHEN T5.rate = 31 THEN tPI.total ELSE 0 END) as base_adicional,
            SUM(CASE WHEN T5.rate = 31 THEN T5.tax_amount ELSE 0 END) as impuesto_adicional,
            MAX(T2.name) as nro_comprobante_retencion,
            MAX(tPI.taxes_and_charges_deducted) as taxes_and_charges_deducted,
            MAX(CASE WHEN T5.charge_type = 'Actual' THEN T5.rate ELSE 0 END) as porcentaje_ret,
            SUM(CASE WHEN T5.rate = 0 AND T5.charge_type != 'Actual' THEN T5.tax_amount ELSE 0 END) AS compras_sin_credito,
            CASE
                WHEN T4.supplier_type = 'Company' THEN 'PJ'
                WHEN T4.supplier_type = 'Individual' THEN 'PN'
                WHEN T4.supplier_type = 'Partnership' THEN 'PJ'
                ELSE "N/A"
            END AS supplier_type,
            tPI.total AS taxable_base
        FROM
            `tabPurchase Invoice` as tPI
        LEFT JOIN
            `tabPurchase Taxes and Charges` as T5
            ON T5.parent = tPI.name AND T5.parenttype = 'Purchase Invoice'
        LEFT JOIN
            `tabVAT Withholding Voucher Item` as T3
            ON T3.purchase_invoice = tPI.name
        LEFT JOIN
            `tabVAT Withholding Voucher` as T2
            ON T3.parent = T2.name
        LEFT JOIN
            `tabSupplier` as T4
            ON T4.name = tPI.supplier
        WHERE
            1=1 {conditions}
        GROUP BY tPI.name
        ORDER BY tPI.posting_date ASC
    """
    data = frappe.db.sql(query, values, as_dict=True)

    # Añadir el número de operación
    for i, row in enumerate(data):
        row["nro_oper"] = i + 1
    
    # Manejo de notas de crédito y débito
    for row in data:
        if row.get("is_return"):
            row["nro_nota_credito"] = row["bill_no"]
            row["bill_no"] = ""
            row["nro_nota_debito"] = ""
        else:
            row["nro_nota_credito"] = ""
            row["nro_nota_debito"] = ""
            
    return data

def execute(filters=None):
    columns = [
        {"fieldname": "nro_oper", "label": "Nro. Oper.", "fieldtype": "Data", "width": 80},
        {"fieldname": "posting_date", "label": "Fecha Doc.", "fieldtype": "Date", "width": 120},
        {"fieldname": "tax_id", "label": "Rif", "fieldtype": "Data", "width": 120},
        {"fieldname": "supplier_name", "label": "Nombre o Razón Social", "fieldtype": "Data", "width": 200},
        {"fieldname": "supplier_type", "label": "Tipo", "fieldtype": "Data", "width": 60},
        {"fieldname": "bill_no", "label": "Nro. de Factura", "fieldtype": "Data", "width": 100},
        {"fieldname": "bill_control", "label": "Nro. de Control", "fieldtype": "Data", "width": 100},
        {"fieldname": "nro_nota_credito", "label": "Nro. Nota de Crédito", "fieldtype": "Data", "width": 100},
        {"fieldname": "nro_nota_debito", "label": "Nro. Nota de Débito", "fieldtype": "Data", "width": 100},
        {"fieldname": "facturas_afectadas", "label": "Facturas Afectadas", "fieldtype": "Data", "width": 100},
        {"fieldname": "nro_planilla", "label": "Nro. Planilla", "fieldtype": "Data", "width": 120},
        {"fieldname": "nro_expediente_importacion", "label": "Nro. Expediente de Importación", "fieldtype": "Data", "width": 180},
        {"fieldname": "tipo_transac", "label": "Tipo de Transac.", "fieldtype": "Data", "width": 120},
        {"fieldname": "grand_total", "label": "Total Compras Incluyendo el IVA", "fieldtype": "Currency", "width": 150},
        {"fieldname": "compras_sin_credito", "label": "Compras sin Derecho a Crédito IVA", "fieldtype": "Currency", "width": 150},
        {"fieldname": "base_reducida", "label": "Base (Tasa Red. 8%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "impuesto_reducida", "label": "Impuesto (Tasa Red. 8%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "base_general", "label": "Base (Tasa Gen. 16%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "impuesto_general", "label": "Impuesto (Tasa Gen. 16%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "base_adicional", "label": "Base (Tasa Adic. 31%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "impuesto_adicional", "label": "Impuesto (Tasa Adic. 31%)", "fieldtype": "Currency", "width": 120},
        {"fieldname": "nro_comprobante_retencion", "label": "Nro. Comprob. de Retención", "fieldtype": "Data", "width": 150},
        {"fieldname": "fecha_entrega", "label": "Fecha de Entrega", "fieldtype": "Date", "width": 120},
        {"fieldname": "porcentaje_ret", "label": "% Ret.", "fieldtype": "Percent", "width": 80},
        {"fieldname": "taxes_and_charges_deducted", "label": "IVA Reducido (AL VENDEDOR)", "fieldtype": "Currency", "width": 150}
    ]

    data = get_processed_data(filters)
    totals = get_totals_from_data(data)
    report_summary = get_report_summary(totals)

    return columns, data, None, None, report_summary

@frappe.whitelist()
def generate_txt_file(filters):
    frappe.msgprint(_("Iniciando la generación del archivo TXT..."))
    
    try:
        filters = frappe.parse_json(filters)
        
        # Reutilizamos la función get_processed_data para obtener la información
        data = get_processed_data(filters)

        if not data:
            frappe.throw(_("No se encontraron datos para el período seleccionado."))

        company_doc = frappe.get_doc("Company", filters.get("company"))
        company_rif = company_doc.tax_id or ""
        
        if not company_rif:
            frappe.throw(_("El RIF de la compañía no está configurado. Por favor, agregue el RIF en la configuración de la compañía."))

        month = str(filters.get("fiscal_month")).zfill(2)
        year = str(filters.get("fiscal_year"))
        periodo = f"{year}{month}"

        content = ""
        for row in data:
            # Determinamos la alícuota a mostrar
            tax_rate = ""
            if flt(row.get("base_general")) > 0:
                tax_rate = "16"
            elif flt(row.get("base_reducida")) > 0:
                tax_rate = "8"
            elif flt(row.get("base_adicional")) > 0:
                tax_rate = "31"
            else:
                tax_rate = "0"
                
            line_data = [
                str(company_rif) or "",
                str(periodo) or "",
                format_date(row.get("posting_date"), "YYYYMMDD") if row.get("posting_date") else "",
                "D" if flt(row.get("is_return")) == 1 else "C",
                "01", # Tipo de transacción (por defecto 01)
                row.get("tax_id") or "",
                row.get("bill_no") or "",
                row.get("bill_control") or "",
                f"{flt(row.get('grand_total')):.2f}".replace('.', ','),
                f"{flt(row.get('taxable_base')):.2f}".replace('.', ','),
                f"{flt(row.get('taxes_and_charges_deducted')):.2f}".replace('.', ','),
                row.get("facturas_afectadas") or "",
                row.get("nro_comprobante_retencion") or "",
                f"{flt(row.get('compras_sin_credito')):.2f}".replace('.', ','),
                tax_rate,
                "0,00",


            ]
            content += "\t".join(line_data) + "\n"
        
        file_doc = frappe.get_doc({
            "doctype": "File",
            "file_name": f"IVA_TXT-{company_doc.abbr}-{frappe.generate_hash(length=8)}.txt",
            "attached_to_doctype": "Report",
            "attached_to_name": "purchasebook",
            "content": content,
            "is_private": 1
        })
        file_doc.insert(ignore_permissions=True)
        
        frappe.msgprint(_("Archivo TXT generado con éxito."))

        return file_doc.file_url

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en generate_txt_file")
        frappe.throw(_(f"Ocurrió un error al generar el archivo TXT: {e}"))