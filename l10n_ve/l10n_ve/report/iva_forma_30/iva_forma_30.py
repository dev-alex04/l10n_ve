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
        {"fieldname": "concept", "label": _("Concepto"), "fieldtype": "Data", "width": 400},
        {"fieldname": "base_amount", "label": _("Base Imponible Bs"), "fieldtype": "Currency", "width": 200},
        {"fieldname": "tax_amount", "label": _("Monto Impuesto Bs"), "fieldtype": "Currency", "width": 200}
    ]

def get_data(filters):
    # Obtener moneda de la empresa
    company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
    filters["company_currency"] = company_currency

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
    # El reporte de Libro de Compras requiere y espera filtros con company_currency
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

    # 3. Totales y Autoliquidación
    total_debit_tax = sales_general_tax + sales_reduced_tax + sales_additional_tax
    total_credit_tax = purchases_general_tax + purchases_reduced_tax + purchases_additional_tax
    
    net_tax = total_debit_tax - total_credit_tax
    if net_tax > 0:
        tax_payable = net_tax
        tax_credit_forward = 0.0
    else:
        tax_payable = 0.0
        tax_credit_forward = abs(net_tax)

    net_to_pay = tax_payable - sales_iva_retained

    data = [
        # SECCION 1: DEBITO FISCAL
        {"concept": "<b>1. DEBITO FISCAL (VENTAS)</b>", "base_amount": 0, "tax_amount": 0},
        {"concept": _("Ventas Internas No Gravadas / Exentas"), "base_amount": sales_exempt, "tax_amount": 0.0},
        {"concept": _("Ventas de Exportación"), "base_amount": sales_export, "tax_amount": 0.0},
        {"concept": _("Ventas Gravadas por Alícuota General (16%)"), "base_amount": sales_general_base, "tax_amount": sales_general_tax},
        {"concept": _("Ventas Gravadas por Alícuota Reducida (8%)"), "base_amount": sales_reduced_base, "tax_amount": sales_reduced_tax},
        {"concept": _("Ventas Gravadas por Alícuota Adicional (31%)"), "base_amount": sales_additional_base, "tax_amount": sales_additional_tax},
        {"concept": "<b>" + _("Total Débito Fiscal del Período") + "</b>", "base_amount": sales_general_base + sales_reduced_base + sales_additional_base + sales_exempt + sales_export, "tax_amount": total_debit_tax},
        
        # SECCION 2: CREDITO FISCAL
        {"concept": "<b>2. CREDITO FISCAL (COMPRAS)</b>", "base_amount": 0, "tax_amount": 0},
        {"concept": _("Compras Internas No Gravadas / Exentas"), "base_amount": purchases_exempt, "tax_amount": 0.0},
        {"concept": _("Compras Gravadas por Alícuota General (16%)"), "base_amount": purchases_general_base, "tax_amount": purchases_general_tax},
        {"concept": _("Compras Gravadas por Alícuota Reducida (8%)"), "base_amount": purchases_reduced_base, "tax_amount": purchases_reduced_tax},
        {"concept": _("Compras Gravadas por Alícuota Adicional (31%)"), "base_amount": purchases_additional_base, "tax_amount": purchases_additional_tax},
        {"concept": "<b>" + _("Total Crédito Fiscal del Período") + "</b>", "base_amount": purchases_general_base + purchases_reduced_base + purchases_additional_base + purchases_exempt, "tax_amount": total_credit_tax},

        # SECCION 3: AUTOLIQUIDACION
        {"concept": "<b>3. DETERMINACION Y AUTOLIQUIDACION</b>", "base_amount": 0, "tax_amount": 0},
        {"concept": _("Total Débito Fiscal"), "base_amount": 0, "tax_amount": total_debit_tax},
        {"concept": _("Menos: Total Crédito Fiscal"), "base_amount": 0, "tax_amount": total_credit_tax},
        {"concept": _("Cuota Tributaria (IVA a pagar antes de retenciones)"), "base_amount": 0, "tax_amount": tax_payable},
        {"concept": _("Excedente de Crédito Fiscal del Período"), "base_amount": 0, "tax_amount": tax_credit_forward},
        {"concept": _("Menos: Retenciones de IVA Recibidas (Clientes)"), "base_amount": 0, "tax_amount": sales_iva_retained},
        {"concept": "<b>" + _("Total IVA Neto a Pagar / (Excedente)") + "</b>", "base_amount": 0, "tax_amount": net_to_pay}
    ]

    return data
