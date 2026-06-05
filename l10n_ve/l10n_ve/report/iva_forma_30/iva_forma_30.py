# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data
from l10n_ve.l10n_ve.report.purchase_book.purchase_book import get_query_data

def execute(filters=None):
    if not filters:
        return [], []
        
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {"fieldname": "row_no", "label": "Nro", "fieldtype": "Data", "width": 50},
        {"fieldname": "concept", "label": "Concepto", "fieldtype": "Data", "width": 450},
        {"fieldname": "box_base", "label": "C. Base", "fieldtype": "Data", "width": 80},
        {"fieldname": "base_amount", "label": "Base Imponible Bs", "fieldtype": "Currency", "width": 150},
        {"fieldname": "box_rate", "label": "C. Alícuota", "fieldtype": "Data", "width": 90},
        {"fieldname": "rate_percent", "label": "Alícuota", "fieldtype": "Data", "width": 80},
        {"fieldname": "box_tax", "label": "C. Impuesto", "fieldtype": "Data", "width": 100},
        {"fieldname": "tax_amount", "label": "Impuesto Bs", "fieldtype": "Currency", "width": 150}
    ]

def get_data(filters):
    company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
    filters["company_currency"] = company_currency

    # Obtain the company tax_id (RIF) server-side to avoid relying on client cache
    company_tax_id = frappe.get_cached_value("Company", filters.get("company"), "tax_id") or "J-00000000-0"
    filters["company_tax_id"] = company_tax_id

    # 1. Obtener datos de Libro de Ventas
    sales_data, adjustment_data = get_sales_data(filters)
    
    sales_exempt = 0.0
    sales_export = 0.0
    sales_general_base = 0.0
    sales_general_tax = 0.0
    sales_reduced_base = 0.0
    sales_reduced_tax = 0.0
    sales_additional_base = 0.0
    sales_additional_tax = 0.0
    sales_iva_retained = 0.0

    for row in sales_data:
        if row.get("is_void"):
            continue
        sales_exempt += flt(row.get("total_exempt", 0))
        sales_export += flt(row.get("ve_fob", 0))
        sales_general_base += flt(row.get("base_general_taxpayer", 0) + row.get("base_general_non_taxpayer", 0))
        sales_general_tax += flt(row.get("iva_general_taxpayer", 0) + row.get("iva_general_non_taxpayer", 0))
        sales_reduced_base += flt(row.get("base_reduced_taxpayer", 0) + row.get("base_reduced_non_taxpayer", 0))
        sales_reduced_tax += flt(row.get("iva_reduced_taxpayer", 0) + row.get("iva_reduced_non_taxpayer", 0))
        sales_additional_base += flt(row.get("base_additional_taxpayer", 0) + row.get("base_additional_non_taxpayer", 0))
        sales_additional_tax += flt(row.get("iva_additional_taxpayer", 0) + row.get("iva_additional_non_taxpayer", 0))
        sales_iva_retained += flt(row.get("iva_retained", 0))

    for row in adjustment_data:
        if row.get("is_void"):
            continue
        sales_iva_retained += flt(row.get("iva_retained", 0))

    # 2. Obtener datos de Libro de Compras
    purchase_data = get_query_data(filters)
    
    purchases_exempt = 0.0
    purchases_general_base = 0.0
    purchases_general_tax = 0.0
    purchases_reduced_base = 0.0
    purchases_reduced_tax = 0.0
    purchases_additional_base = 0.0
    purchases_additional_tax = 0.0

    for row in purchase_data:
        purchases_exempt += flt(row.get("total_exempt", 0))
        purchases_general_base += flt(row.get("base_general", 0))
        purchases_general_tax += flt(row.get("impuesto_general", 0))
        purchases_reduced_base += flt(row.get("base_reducida", 0))
        purchases_reduced_tax += flt(row.get("impuesto_reducida", 0))
        purchases_additional_base += flt(row.get("base_adicional", 0))
        purchases_additional_tax += flt(row.get("impuesto_adicional", 0))

    # 3. Autoliquidación y Cálculos de Forma 30
    excedente_anterior = flt(filters.get("excedente_anterior", 0.0))
    retenciones_anteriores = flt(filters.get("retenciones_anteriores", 0.0))

    total_debit_base = sales_exempt + sales_export + sales_general_base + sales_additional_base + sales_reduced_base
    total_debit_tax = sales_general_tax + sales_additional_tax + sales_reduced_tax

    total_credit_base = purchases_exempt + purchases_general_base + purchases_additional_base + purchases_reduced_base
    total_credit_tax = purchases_general_tax + purchases_additional_tax + purchases_reduced_tax

    # Prorrata
    sales_taxable = sales_general_base + sales_additional_base + sales_reduced_base + sales_export
    total_sales = sales_taxable + sales_exempt
    prorrata_percentage = 100.0
    if total_sales > 0 and sales_exempt > 0:
        prorrata_percentage = (sales_taxable / total_sales) * 100.0

    credit_total_deducible = total_credit_tax * (prorrata_percentage / 100.0)
    prorrata_credit_amount = total_credit_tax - credit_total_deducible
    total_credits_available = credit_total_deducible + excedente_anterior

    # Cuota tributaria / Excedente
    net_quota = total_debit_tax - total_credits_available
    if net_quota > 0:
        total_cuota_tributaria = net_quota
        excedente_siguiente = 0.0
    else:
        total_cuota_tributaria = 0.0
        excedente_siguiente = abs(net_quota)

    subtotal_tax_payable = total_cuota_tributaria
    retenciones_periodo = sales_iva_retained
    total_retenciones_disponibles = retenciones_anteriores + retenciones_periodo

    retenciones_descontadas = min(subtotal_tax_payable, total_retenciones_disponibles)
    saldo_retenciones_no_aplicado = max(0.0, total_retenciones_disponibles - subtotal_tax_payable)

    subtotal_after_retenciones = max(0.0, subtotal_tax_payable - retenciones_descontadas)

    percepciones_acumuladas = 0.0
    percepciones_periodo = 0.0
    total_percepciones = percepciones_acumuladas + percepciones_periodo
    percepciones_descontadas = min(subtotal_after_retenciones, total_percepciones)
    saldo_percepciones_no_aplicado = max(0.0, total_percepciones - subtotal_after_retenciones)

    total_a_pagar = max(0.0, subtotal_after_retenciones - percepciones_descontadas)

    data = [
        # SECCION: DEBITOS FISCALES
        {"is_header": 1, "concept": "<b>DEBITOS FISCALES</b>", "box_base": "<b>Base Imponible</b>", "box_tax": "<b>Débito Fiscal</b>"},
        {
            "row_no": "1",
            "concept": "VENTAS INTERNAS NO GRAVADAS",
            "box_base": "40", "base_amount": sales_exempt,
            "box_rate": "", "rate_percent": "",
            "box_tax": "0", "tax_amount": 0.0
        },
        {
            "row_no": "2",
            "concept": "VENTAS DE EXPORTACIÓN",
            "box_base": "41", "base_amount": sales_export,
            "box_rate": "9", "rate_percent": "0%",
            "box_tax": "", "tax_amount": 0.0
        },
        {
            "row_no": "3",
            "concept": "VENTAS INTERNAS GRAVADAS POR ALÍCUOTA GENERAL",
            "box_base": "42", "base_amount": sales_general_base,
            "box_rate": "8", "rate_percent": "16%",
            "box_tax": "43", "tax_amount": sales_general_tax
        },
        {
            "row_no": "4",
            "concept": "VENTAS INTERNAS GRAVADAS POR ALÍCUOTA GENERAL MÁS ADICIONAL",
            "box_base": "442", "base_amount": sales_additional_base,
            "box_rate": "8", "rate_percent": "31%",
            "box_tax": "452", "tax_amount": sales_additional_tax
        },
        {
            "row_no": "5",
            "concept": "VENTAS INTERNAS GRAVADAS POR ALÍCUOTA REDUCIDA",
            "box_base": "443", "base_amount": sales_reduced_base,
            "box_rate": "7", "rate_percent": "8%",
            "box_tax": "453", "tax_amount": sales_reduced_tax
        },
        {
            "row_no": "6",
            "concept": "<b>TOTAL VENTAS Y DÉBITOS FISCALES PARA EFECTOS DE DETERMINACIÓN</b>",
            "box_base": "46", "base_amount": total_debit_base,
            "box_rate": "4", "rate_percent": "",
            "box_tax": "47", "tax_amount": total_debit_tax,
            "is_total": 1
        },
        {
            "row_no": "7",
            "concept": "AJUSTE A LOS DÉBITOS FISCALES DE PERÍODOS ANTERIORES",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "48", "tax_amount": 0.0
        },
        {
            "row_no": "8",
            "concept": "CERTIFICADO DE DÉBITOS FISCALES EXONERADOS (RECIBIDOS DE ENTES EXONERADOS)",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "80", "tax_amount": 0.0
        },
        {
            "row_no": "9",
            "concept": "<b>TOTAL DÉBITOS FISCALES</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "49", "tax_amount": total_debit_tax,
            "is_total": 1
        },
        
        # SECCION: CREDITOS FISCALES
        {"is_header": 1, "concept": "<b>CRÉDITOS FISCALES</b>", "box_base": "<b>Base Imponible</b>", "box_tax": "<b>Crédito Fiscal</b>"},
        {
            "row_no": "10",
            "concept": "COMPRAS NO GRAVADAS Y/O SIN DERECHO A CRÉDITO FISCAL",
            "box_base": "30", "base_amount": purchases_exempt,
            "box_rate": "", "rate_percent": "",
            "box_tax": "0", "tax_amount": 0.0
        },
        {
            "row_no": "11",
            "concept": "IMPORTACIÓN GRAVADA POR ALÍCUOTA GENERAL",
            "box_base": "31", "base_amount": 0.0,
            "box_rate": "9", "rate_percent": "16%",
            "box_tax": "32", "tax_amount": 0.0
        },
        {
            "row_no": "12",
            "concept": "IMPORTACIONES GRAVADAS POR ALÍCUOTA GENERAL MÁS ADICIONAL",
            "box_base": "312", "base_amount": 0.0,
            "box_rate": "8", "rate_percent": "31%",
            "box_tax": "322", "tax_amount": 0.0
        },
        {
            "row_no": "13",
            "concept": "IMPORTACIONES GRAVADAS POR ALÍCUOTA REDUCIDA",
            "box_base": "313", "base_amount": 0.0,
            "box_rate": "7", "rate_percent": "8%",
            "box_tax": "323", "tax_amount": 0.0
        },
        {
            "row_no": "14",
            "concept": "COMPRAS INTERNAS GRAVADAS POR ALÍCUOTA GENERAL",
            "box_base": "33", "base_amount": purchases_general_base,
            "box_rate": "7", "rate_percent": "16%",
            "box_tax": "34", "tax_amount": purchases_general_tax
        },
        {
            "row_no": "15",
            "concept": "COMPRAS INTERNAS GRAVADAS POR ALÍCUOTA GENERAL MÁS ADICIONAL",
            "box_base": "332", "base_amount": purchases_additional_base,
            "box_rate": "8", "rate_percent": "31%",
            "box_tax": "342", "tax_amount": purchases_additional_tax
        },
        {
            "row_no": "16",
            "concept": "COMPRAS INTERNAS GRAVADAS POR ALÍCUOTA REDUCIDA",
            "box_base": "333", "base_amount": purchases_reduced_base,
            "box_rate": "7", "rate_percent": "8%",
            "box_tax": "343", "tax_amount": purchases_reduced_tax
        },
        {
            "row_no": "17",
            "concept": "<b>TOTAL COMPRAS Y CRÉDITOS FISCALES DEL PERÍODO</b>",
            "box_base": "35", "base_amount": total_credit_base,
            "box_rate": "5", "rate_percent": "",
            "box_tax": "36", "tax_amount": total_credit_tax,
            "is_total": 1
        },
        {
            "row_no": "18",
            "concept": "CRÉDITOS FISCALES TOTALMENTE DEDUCIBLES",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "70", "tax_amount": total_credit_tax
        },
        {
            "row_no": "19",
            "concept": "CRÉDITOS FISCALES PRODUCTO DE LA APLICACIÓN DE LA PRORRATA",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "37", "tax_amount": prorrata_credit_amount
        },
        {
            "row_no": "20",
            "concept": "<b>TOTAL CRÉDITOS FISCALES DEDUCIBLES</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "71", "tax_amount": credit_total_deducible,
            "is_total": 1
        },
        {
            "row_no": "21",
            "concept": "EXCEDENTE DE CRÉDITOS FISCALES DEL MES ANTERIOR",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "20", "tax_amount": excedente_anterior
        },
        {
            "row_no": "22",
            "concept": "REINTEGRO SOLICITADO (SOLO EXPORTADORES)",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "21", "tax_amount": 0.0
        },
        {
            "row_no": "23",
            "concept": "REINTEGRO SOLICITADO (SOLO QUIEN SUMINISTRE BIENES A ENTES EXONERADOS)",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "81", "tax_amount": 0.0
        },
        {
            "row_no": "24",
            "concept": "AJUSTES A LOS CRÉDITOS DE PERÍODOS ANTERIORES",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "38", "tax_amount": 0.0
        },
        {
            "row_no": "25",
            "concept": "CERTIFICADO DE DEBITOS FISCALES EXONERADOS (EMITIDOS POR ENTES EXONERADOS)",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "82", "tax_amount": 0.0
        },
        {
            "row_no": "26",
            "concept": "<b>TOTAL CRÉDITOS FISCALES</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "39", "tax_amount": total_credits_available,
            "is_total": 1
        },
        
        # SECCION: AUTOLIQUIDACION
        {"is_header": 1, "concept": "<b>AUTOLIQUIDACION</b>", "box_base": "", "box_tax": "<b>Monto Bs</b>"},
        {
            "row_no": "27",
            "concept": "TOTAL CUOTA TRIBUTARIA",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "53", "tax_amount": total_cuota_tributaria
        },
        {
            "row_no": "28",
            "concept": "EXCEDENTE DE CRÉDITOS FISCAL PARA EL MES SIGUIENTE",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "60", "tax_amount": excedente_siguiente
        },
        {
            "row_no": "29",
            "concept": "IMPUESTO PAGADO EN DECLARACIÓN SUSTITUIDA",
            "box_base": "22", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "8", "tax_amount": 0.0
        },
        {
            "row_no": "30",
            "concept": "RETENCIONES DESCONTADAS EN DECLARACIÓN SUSTITUIDA",
            "box_base": "51", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "9", "tax_amount": 0.0
        },
        {
            "row_no": "31",
            "concept": "PERCEPCIONES DESCONTADAS EN DECLARACIÓN SUSTITUIDA",
            "box_base": "24", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "6", "tax_amount": 0.0
        },
        {
            "row_no": "32",
            "concept": "<b>SUB TOTAL IMPUESTO A PAGAR</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "78", "tax_amount": subtotal_tax_payable,
            "is_total": 1
        },
        {
            "row_no": "33",
            "concept": "RETENCIONES ACUMULADAS POR DESCONTAR",
            "box_base": "54", "base_amount": retenciones_anteriores,
            "box_rate": "", "rate_percent": "",
            "box_tax": "6", "tax_amount": 0.0
        },
        {
            "row_no": "34",
            "concept": "RETENCIONES DEL PERÍODO",
            "box_base": "66", "base_amount": retenciones_periodo,
            "box_rate": "", "rate_percent": "",
            "box_tax": "4", "tax_amount": 0.0
        },
        {
            "row_no": "35",
            "concept": "CRÉDITOS ADQUIRIDOS POR CESIÓN DE RETENCIONES",
            "box_base": "72", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "8", "tax_amount": 0.0
        },
        {
            "row_no": "36",
            "concept": "RECUPERACIÓN DE RETENCIONES SOLICITADO",
            "box_base": "73", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "7", "tax_amount": 0.0
        },
        {
            "row_no": "37",
            "concept": "<b>TOTAL RETENCIONES</b>",
            "box_base": "74", "base_amount": total_retenciones_disponibles,
            "box_rate": "", "rate_percent": "",
            "box_tax": "6", "tax_amount": total_retenciones_disponibles,
            "is_total": 1
        },
        {
            "row_no": "38",
            "concept": "RETENCIONES SOPORTADAS Y DESCONTADAS EN ESTA DECLARACIÓN",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "55", "tax_amount": retenciones_descontadas
        },
        {
            "row_no": "39",
            "concept": "SALDO DE RETENCIONES DE IVA NO APLICADO",
            "box_base": "67", "base_amount": saldo_retenciones_no_aplicado,
            "box_rate": "", "rate_percent": "",
            "box_tax": "3", "tax_amount": 0.0
        },
        {
            "row_no": "40",
            "concept": "<b>SUB - TOTAL IMPUESTO A PAGAR</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "56", "tax_amount": subtotal_after_retenciones,
            "is_total": 1
        },
        {
            "row_no": "41",
            "concept": "PERCEPCIONES ACUMULADAS EN IMPORTACIONES POR DESCONTAR",
            "box_base": "57", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "3", "tax_amount": 0.0
        },
        {
            "row_no": "42",
            "concept": "PERCEPCIONES DEL PERÍODO",
            "box_base": "68", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "2", "tax_amount": 0.0
        },
        {
            "row_no": "43",
            "concept": "CRÉDITOS ADQUIRIDOS POR CESIÓN DE PERCEPCIONES",
            "box_base": "75", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "5", "tax_amount": 0.0
        },
        {
            "row_no": "44",
            "concept": "RECUPERACIÓN DE PERCEPCIONES SOLICITADO",
            "box_base": "76", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "4", "tax_amount": 0.0
        },
        {
            "row_no": "45",
            "concept": "<b>TOTAL PERCEPCIONES</b>",
            "box_base": "77", "base_amount": total_percepciones,
            "box_rate": "", "rate_percent": "",
            "box_tax": "3", "tax_amount": total_percepciones,
            "is_total": 1
        },
        {
            "row_no": "46",
            "concept": "PERCEPCIONES EN ADUANAS DESCONTADAS EN ESTA DECLARACIÓN",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "58", "tax_amount": percepciones_descontadas
        },
        {
            "row_no": "47",
            "concept": "SALDO DE PERCEPCIONES EN ADUANAS NO APLICADO",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "1", "tax_amount": saldo_percepciones_no_aplicado
        },
        {
            "row_no": "48",
            "concept": "<b>TOTAL A PAGAR ( 61 + 62 + 65 )</b>",
            "box_base": "", "base_amount": 0.0,
            "box_rate": "", "rate_percent": "",
            "box_tax": "90", "tax_amount": total_a_pagar,
            "is_total": 1
        }
    ]

    return data
