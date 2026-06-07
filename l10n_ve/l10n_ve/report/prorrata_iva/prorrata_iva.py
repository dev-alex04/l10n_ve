# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, fmt_money
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
        {"fieldname": "amount", "label": _("Monto Bs"), "fieldtype": "Currency", "width": 200},
        {"fieldname": "ratio", "label": _("Ratio / Porcentaje"), "fieldtype": "Data", "width": 200}
    ]

def get_data(filters):
    company_currency = frappe.get_cached_value("Company", filters.get("company"), "default_currency")
    filters["company_currency"] = company_currency

    # 1. Obtener Ventas
    sales_data, adjustment_data = get_sales_data(filters)
    
    sales_exempt = 0.0
    sales_export = 0.0
    sales_general_base = 0.0
    sales_reduced_base = 0.0
    sales_additional_base = 0.0

    for row in sales_data:
        if row.get("is_void"):
            continue
        sales_exempt += flt(row.get("total_exempt", 0))
        sales_export += flt(row.get("ve_fob", 0))
        sales_general_base += flt(row.get("base_general_taxpayer", 0) + row.get("base_general_non_taxpayer", 0))
        sales_reduced_base += flt(row.get("base_reduced_taxpayer", 0) + row.get("base_reduced_non_taxpayer", 0))
        sales_additional_base += flt(row.get("base_additional_taxpayer", 0) + row.get("base_additional_non_taxpayer", 0))

    # Ventas Gravadas = Ventas Internas + Exportación
    sales_taxable = sales_general_base + sales_reduced_base + sales_additional_base + sales_export
    total_sales = sales_taxable + sales_exempt

    # Calcular porcentaje prorrata
    prorrata_percentage = 100.0
    if total_sales > 0:
        prorrata_percentage = (sales_taxable / total_sales) * 100.0

    # 2. Obtener Compras (Crédito Fiscal del Período)
    purchase_data = get_query_data(filters)
    
    purchases_general_tax = 0.0
    purchases_reduced_tax = 0.0
    purchases_additional_tax = 0.0

    for row in purchase_data:
        purchases_general_tax += flt(row.get("impuesto_general", 0))
        purchases_reduced_tax += flt(row.get("impuesto_reducida", 0))
        purchases_additional_tax += flt(row.get("impuesto_adicional", 0))

    total_credit_common = purchases_general_tax + purchases_reduced_tax + purchases_additional_tax

    # 3. Aplicación de la prorrata
    deductible_credit = total_credit_common * (prorrata_percentage / 100.0)
    non_deductible_credit = total_credit_common * (1.0 - (prorrata_percentage / 100.0))

    data = [
        # SECCION 1: RESUMEN DE VENTAS
        {"concept": "<b>1. RESUMEN DE VENTAS (BASES IMPONIBLES)</b>", "amount": 0, "ratio": ""},
        {"concept": _("Ventas Internas Gravadas (16% / 8% / 31%)"), "amount": sales_general_base + sales_reduced_base + sales_additional_base, "ratio": ""},
        {"concept": _("Ventas de Exportación (FOB)"), "amount": sales_export, "ratio": ""},
        {"concept": _("Total Ventas Gravadas (A)"), "amount": sales_taxable, "ratio": ""},
        {"concept": _("Ventas Exentas / Exoneradas / No Gravadas (B)"), "amount": sales_exempt, "ratio": ""},
        {"concept": "<b>" + _("Total Ventas del Período (A + B)") + "</b>", "amount": total_sales, "ratio": ""},
        
        # SECCION 2: RATIO DE PRORRATA
        {"concept": "<b>2. DETERMINACION DE LA PRORRATA</b>", "amount": 0, "ratio": ""},
        {"concept": "<b>" + _("Porcentaje de Prorrata de IVA") + "</b>", "amount": 0, "ratio": f"{prorrata_percentage:.4f} %"},

        # SECCION 3: CREDITOS FISCALES
        {"concept": "<b>3. CREDITOS FISCALES ADQUIRIDOS (COMPRAS)</b>", "amount": 0, "ratio": ""},
        {"concept": _("Crédito Fiscal Alícuota General (16%)"), "amount": purchases_general_tax, "ratio": ""},
        {"concept": _("Crédito Fiscal Alícuota Reducida (8%)"), "amount": purchases_reduced_tax, "ratio": ""},
        {"concept": _("Crédito Fiscal Alícuota Adicional (31%)"), "amount": purchases_additional_tax, "ratio": ""},
        {"concept": "<b>" + _("Total Crédito Fiscal Común") + "</b>", "amount": total_credit_common, "ratio": ""},

        # SECCION 4: DISTRIBUCION DE CREDITO FISCAL
        {"concept": "<b>4. RESULTADOS DE LA PRORRATA</b>", "amount": 0, "ratio": ""},
        {"concept": "<b>" + _("Crédito Fiscal IVA Deducible") + "</b>", "amount": deductible_credit, "ratio": f"{prorrata_percentage:.4f} %"},
        {"concept": "<b>" + _("Crédito Fiscal IVA No Deducible (Gasto)") + "</b>", "amount": non_deductible_credit, "ratio": f"{(100.0 - prorrata_percentage):.4f} %"}
    ]

    return data
