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
            "value": totals.get("total_exempt"),
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
    total_exempt = 0
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
        total_exempt += row.get("total_exempt", 0)
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
        "total_exempt": total_exempt,
        "base_reducida": base_reducida,
        "impuesto_reducida": impuesto_reducida,
        "base_general": base_general,
        "impuesto_general": impuesto_general,
        "base_adicional": base_adicional,
        "impuesto_adicional": impuesto_adicional,
        "taxes_and_charges_deducted": taxes_and_charges_deducted,
    }

def execute(filters=None):
    columns = [
        {"fieldname": "nro_oper", "label": "Nro. Oper.", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "posting_date", "label": "Fecha Doc.", "fieldtype": "Date", "width": "auto"},
        {"fieldname": "tax_id", "label": "Rif", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier_name", "label": "Nombre o Razón Social", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier_type", "label": "Tipo", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_no", "label": "Nro. de Factura", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_control", "label": "Nro. de Control", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_nota_credito", "label": "Nro. Nota de Crédito", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_nota_debito", "label": "Nro. Nota de Débito", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "facturas_afectadas", "label": "Facturas Afectadas", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_planilla", "label": "Nro. Planilla", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "nro_expediente_importacion", "label": "Nro. Expediente de Importación", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "tipo_transac", "label": "Tipo de Transac.", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "grand_total", "label": "Total Compras Incluyendo el IVA", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "total_exempt", "label": "Compras sin Derecho a Crédito IVA", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_reducida", "label": "Base (Tasa Red. 8%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_reducida", "label": "Impuesto (Tasa Red. 8%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_general", "label": "Base (Tasa Gen. 16%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_general", "label": "Impuesto (Tasa Gen. 16%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "base_adicional", "label": "Base (Tasa Adic. 31%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "impuesto_adicional", "label": "Impuesto (Tasa Adic. 31%)", "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "nro_comprobante_retencion", "label": "Nro. Comprob. de Retención", "fieldtype": "Data", "width": "auto"},
        {"fieldname": "fecha_entrega", "label": "Fecha de Entrega", "fieldtype": "Date", "width": "auto"},
        {"fieldname": "porcentaje_ret", "label": "% Ret.", "fieldtype": "Percent", "width": "auto"},
        {"fieldname": "taxes_and_charges_deducted", "label": "IVA Reducido (AL VENDEDOR)", "fieldtype": "Currency", "width": "auto"}
    ]

    conditions = "AND tPI.docstatus = 1"
    values = []

    if filters.get("date_from"):
        conditions += " AND tPI.posting_date >= %s"
        values.append(filters.get("date_from"))

    if filters.get("to_date"):
        conditions += " AND tPI.posting_date <= %s"
        values.append(filters.get("to_date"))

    if filters.get("company"):
        conditions += " AND tPI.company = %s"
        values.append(filters.get("company"))
    
    query = f"""
        SELECT
            tPI.name as nro_factura,
            tPI.posting_date as posting_date,
            T4.tax_id as tax_id,
            tPI.supplier_name as supplier_name,
            tPI.is_return as tipo,
            tPI.bill_no as bill_no,
            tPI.bill_control as bill_control,
            tPI.grand_total as grand_total,
            tPI.total_exempt as total_exempt,
            SUM(CASE WHEN T5.rate = 8 THEN tPI.total ELSE 0 END) as base_reducida,
            SUM(CASE WHEN T5.rate = 8 THEN T5.tax_amount ELSE 0 END) as impuesto_reducida,
            SUM(CASE WHEN T5.rate = 16 THEN tPI.total ELSE 0 END) as base_general,
            SUM(CASE WHEN T5.rate = 16 THEN T5.tax_amount ELSE 0 END) as impuesto_general,
            SUM(CASE WHEN T5.rate = 31 THEN tPI.total ELSE 0 END) as base_adicional,
            SUM(CASE WHEN T5.rate = 31 THEN T5.tax_amount ELSE 0 END) as impuesto_adicional,
            MAX(T2.name) as nro_comprobante_retencion,
            MAX(T2.delivery_date) as fecha_entrega,
            MAX(CASE WHEN T5.charge_type = 'Actual' THEN T5.rate ELSE 0 END) as porcentaje_ret,
            MAX(tPI.taxes_and_charges_deducted) as taxes_and_charges_deducted,
            CASE 
                WHEN T4.supplier_type = 'Company' THEN 'PJ' 
                WHEN T4.supplier_type = 'Individual' THEN 'PN' 
                WHEN T4.supplier_type = 'Partnership' THEN 'PJ' 
                ELSE "N/A" 
            END AS supplier_type
        FROM
            `tabPurchase Invoice` as tPI
        LEFT JOIN
            `tabPurchase Taxes and Charges` as T5
            ON T5.parent = tPI.name
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
    """
    
    data = frappe.db.sql(query, tuple(values), as_dict=True)
    totals = get_totals_from_data(data)
    report_summary = get_report_summary(totals)

    return columns, data, None, None, report_summary


@frappe.whitelist()
def generate_xml_islr_file(filters=None):
    """
    Generates an XML string for ISLR retentions based on report filters.
    """
    if not filters:
        frappe.throw(_("Filtros de fecha son requeridos."))

    # Ensure filters is a dictionary
    if isinstance(filters, str):
        filters = json.loads(filters)

  
    invoices = frappe.db.sql("""
        SELECT
            tPI.name,
            tPI.supplier,
            tPI.posting_date,
            tPI.bill_no,
            tPI.bill_control,
            tPI.grand_total,
            tPTC.tax_amount AS retention_amount,
            tPTC.code AS code,
            tPTC.rate AS retention_percentage
        FROM
            `tabPurchase Taxes and Charges` AS tPTC
        JOIN
            `tabPurchase Invoice` AS tPI ON tPTC.parent = tPI.name
        WHERE
            tPTC.charge_type = 'ISLR' AND tPI.docstatus = 1
            AND tPI.posting_date >= %(date_from)s
            AND tPI.posting_date <= %(to_date)s
            AND tPI.company = %(company)s
    """, filters, as_dict=True)

    if not invoices:
        return None

   
    xml_data = '<?xml version="1.0" encoding="UTF-8"?>\n<RelacionRetencionesISLR>\n'


    for i, inv in enumerate(invoices):
        
        supplier_tax_id = frappe.db.get_value("Supplier", inv.supplier, "tax_id")
        
        xml_data += f'    <DetalleRetencion>\n'
        xml_data += f'        <RifRetenido>{supplier_tax_id}</RifRetenido>\n'
        xml_data += f'        <NumeroFactura>{inv.bill_no}</NumeroFactura>\n'
        xml_data += f'        <NumeroControl>{inv.bill_control}</NumeroControl>\n'
        xml_data += f'        <FechaOperacion>{inv.posting_date}</FechaOperacion>\n'
        xml_data += f'        <CodigoConcepto>{inv.code}</CodigoConcepto>\n' 
        xml_data += f'        <MontoOperacion>{inv.grand_total:.2f}</MontoOperacion>\n'
        xml_data += f'        <PorcentajeRetencion>{inv.retention_percentage}</PorcentajeRetencion>\n'
        xml_data += f'    </DetalleRetencion>\n'

   
    xml_data += '</RelacionRetencionesISLR>'

    return xml_data

