# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    presentation = filters.get("presentation") or "Detallado"
    
    columns = [
        {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 100},
        {"fieldname": "voucher_no", "label": _("Referencia / Comprobante"), "fieldtype": "Data", "width": 180},
        {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Data", "width": 250},
        {"fieldname": "narration", "label": _("Descripción / Glosa"), "fieldtype": "Data", "width": 250},
        {"fieldname": "debit", "label": _("Débito (Debe)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "credit", "label": _("Crédito (Haber)"), "fieldtype": "Currency", "width": 120}
    ]
    
    gl_entries = frappe.get_all("GL Entry", filters={
        "company": company,
        "posting_date": ["between", [from_date, to_date]],
        "docstatus": 1
    }, fields=["name", "posting_date", "voucher_type", "voucher_no", "account", "remarks", "debit", "credit"], order_by="posting_date, voucher_no, creation")
    
    data = []
    
    if presentation == "Resumido":
        # Group by voucher_no and summarize debits and credits
        summary = {}
        for entry in gl_entries:
            key = entry.voucher_no
            if key not in summary:
                summary[key] = {
                    "posting_date": entry.posting_date,
                    "voucher_no": entry.voucher_no,
                    "account": f"{entry.voucher_type}",
                    "narration": entry.remarks,
                    "debit": 0.0,
                    "credit": 0.0
                }
            summary[key]["debit"] += float(entry.debit)
            summary[key]["credit"] += float(entry.credit)
            
        for key in sorted(summary.keys(), key=lambda k: summary[k]["posting_date"]):
            data.append(summary[key])
            
    else:
        # Detailed presentation: List every transaction line-by-line grouped by voucher
        current_voucher = None
        voucher_debit = 0.0
        voucher_credit = 0.0
        
        for entry in gl_entries:
            if current_voucher and current_voucher != entry.voucher_no:
                # Append a subtotal line for the previous voucher
                data.append({
                    "posting_date": "",
                    "voucher_no": "",
                    "account": _("  Total Comprobante"),
                    "narration": "",
                    "debit": voucher_debit,
                    "credit": voucher_credit,
                    "is_total": 1
                })
                data.append({"posting_date": "", "voucher_no": "", "account": "", "narration": "", "debit": 0, "credit": 0}) # Spacer row
                voucher_debit = 0.0
                voucher_credit = 0.0
                
            current_voucher = entry.voucher_no
            voucher_debit += float(entry.debit)
            voucher_credit += float(entry.credit)
            
            data.append({
                "posting_date": entry.posting_date,
                "voucher_no": entry.voucher_no,
                "account": entry.account,
                "narration": entry.remarks,
                "debit": entry.debit,
                "credit": entry.credit
            })
            
        # Append final voucher subtotal
        if current_voucher:
            data.append({
                "posting_date": "",
                "voucher_no": "",
                "account": _("  Total Comprobante"),
                "narration": "",
                "debit": voucher_debit,
                "credit": voucher_credit,
                "is_total": 1
            })
            
    # Append grand total row
    grand_debit = sum(float(r["debit"]) for r in data if r.get("posting_date") != "" and not r.get("is_total"))
    grand_credit = sum(float(r["credit"]) for r in data if r.get("posting_date") != "" and not r.get("is_total"))
    
    data.append({"posting_date": "", "voucher_no": "", "account": "", "narration": "", "debit": 0, "credit": 0}) # Spacer
    data.append({
        "posting_date": "",
        "voucher_no": "",
        "account": _("TOTAL GENERAL LIBRO DIARIO"),
        "narration": "",
        "debit": grand_debit,
        "credit": grand_credit,
        "is_total": 1,
        "is_group": 1
    })

    return columns, data, None, None, None
