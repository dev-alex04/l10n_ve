# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    to_date = filters.get("to_date")
    
    fiscal_year_start = f"{to_date[:4]}-01-01"
    
    columns = [
        {"fieldname": "asset", "label": _("Código Activo"), "fieldtype": "Link", "options": "Asset", "width": 140},
        {"fieldname": "asset_name", "label": _("Descripción"), "fieldtype": "Data", "width": 200},
        {"fieldname": "asset_category", "label": _("Categoría"), "fieldtype": "Link", "options": "Asset Category", "width": 140},
        {"fieldname": "purchase_date", "label": _("Fecha Compra"), "fieldtype": "Date", "width": 110},
        {"fieldname": "gross_value", "label": _("Costo Adquisición"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "opening_accumulated_depr", "label": _("Depr. Acum. Inicial"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "period_depr", "label": _("Depr. del Período"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "closing_accumulated_depr", "label": _("Depr. Acum. Final"), "fieldtype": "Currency", "width": 130},
        {"fieldname": "net_value", "label": _("Valor Neto"), "fieldtype": "Currency", "width": 130}
    ]
    
    # 1. Fetch active assets
    assets = frappe.db.get_all("Asset", filters={
        "company": company,
        "purchase_date": ["<=", to_date],
        "status": ["not in", ["Draft", "Scrapped"]]
    }, fields=["name", "asset_name", "asset_category", "purchase_date", "gross_purchase_amount", "opening_accumulated_depreciation"])
    
    # 2. Fetch posted depreciations
    depr_entries = frappe.db.sql("""
        SELECT 
            parent.asset,
            ds.schedule_date,
            ds.depreciation_amount
        FROM 
            `tabAsset Depreciation Schedule` parent
        JOIN 
            `tabDepreciation Schedule` ds ON ds.parent = parent.name
        WHERE 
            parent.company = %s AND ds.journal_entry IS NOT NULL AND parent.docstatus = 1
    """, (company,), as_dict=True)
    
    # Map depreciations by asset
    asset_deprs = {}
    for entry in depr_entries:
        if entry.asset not in asset_deprs:
            asset_deprs[entry.asset] = []
        asset_deprs[entry.asset].append(entry)
        
    data = []
    
    total_gross = 0.0
    total_opening_depr = 0.0
    total_period_depr = 0.0
    total_closing_depr = 0.0
    total_net = 0.0
    
    for asset in assets:
        deprs = asset_deprs.get(asset.name, [])
        
        # Calculate opening depreciation from postings before current fiscal year
        opening_posted = 0.0
        period_posted = 0.0
        
        for d in deprs:
            d_date = str(d.schedule_date)
            if d_date < fiscal_year_start:
                opening_posted += float(d.depreciation_amount)
            elif d_date <= to_date:
                period_posted += float(d.depreciation_amount)
                
        # Total opening accumulated depreciation includes manually specified opening depreciation
        opening_accum = float(asset.opening_accumulated_depreciation or 0.0) + opening_posted
        closing_accum = opening_accum + period_posted
        gross_value = float(asset.gross_purchase_amount or 0.0)
        net_value = gross_value - closing_accum
        
        data.append({
            "asset": asset.name,
            "asset_name": asset.asset_name,
            "asset_category": asset.asset_category,
            "purchase_date": asset.purchase_date,
            "gross_value": gross_value,
            "opening_accumulated_depr": opening_accum,
            "period_depr": period_posted,
            "closing_accumulated_depr": closing_accum,
            "net_value": net_value
        })
        
        total_gross += gross_value
        total_opening_depr += opening_accum
        total_period_depr += period_posted
        total_closing_depr += closing_accum
        total_net += net_value
        
    # Append total row
    data.append({
        "asset": _("TOTAL GENERAL"),
        "asset_name": "",
        "asset_category": "",
        "purchase_date": None,
        "gross_value": total_gross,
        "opening_accumulated_depr": total_opening_depr,
        "period_depr": total_period_depr,
        "closing_accumulated_depr": total_closing_depr,
        "net_value": total_net,
        "is_total": 1,
        "is_group": 1
    })
    
    return columns, data, None, None, None
