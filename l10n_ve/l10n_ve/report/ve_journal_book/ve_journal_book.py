# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from l10n_ve.utils.accounting import get_hierarchical_balances

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    presentation = filters.get("presentation") or "Detallado"
    
    if presentation in ["1° Nivel", "2° Nivel", "3° Nivel", "4° Nivel"]:
        columns = [
            {"fieldname": "account_number", "label": _("Código"), "fieldtype": "Data", "width": 120},
            {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Data", "width": 350},
            {"fieldname": "debit", "label": _("Debe"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "credit", "label": _("Haber"), "fieldtype": "Currency", "width": 140}
        ]
        
        # Determine L based on presentation
        if presentation == "1° Nivel":
            L = 1
        elif presentation == "2° Nivel":
            L = 2
        elif presentation == "3° Nivel":
            L = 3
        else:
            L = 4
            
        accounts_data = get_hierarchical_balances(company, to_date, from_date=from_date)
        
        # Build parent mapping to determine depths/levels
        parent_map = {}
        for acc in accounts_data:
            parent_map[acc.account] = acc.parent_account
            
        depth_cache = {}
        def get_depth(acc_id):
            if acc_id not in parent_map or not parent_map[acc_id]:
                return 0
            if acc_id in depth_cache:
                return depth_cache[acc_id]
            d = 1 + get_depth(parent_map[acc_id])
            depth_cache[acc_id] = d
            return d
            
        # Helper to check if child is descendant of parent
        def is_descendant(child, parent):
            return child.lft > parent.lft and child.rgt < parent.rgt
            
        data = []
        stack = []
        
        # Filter accounts that have depth < L
        filtered_accounts = []
        for acc in accounts_data:
            acc.depth = get_depth(acc.account)
            if acc.depth < L:
                filtered_accounts.append(acc)
                
        for idx, acc in enumerate(filtered_accounts):
            # Close groups that this row does not belong to
            while stack and not is_descendant(acc, stack[-1]):
                closed = stack.pop()
                data.append({
                    "account_number": "",
                    "account": f"Total de {closed.account_number or ''} {closed.account_name}",
                    "debit": closed.debit,
                    "credit": closed.credit,
                    "is_total": 1,
                    "is_group_total": 1,
                    "indent": closed.depth
                })
                
            # If it's a group header (depth < L - 1 and is_group == 1)
            if acc.depth < L - 1 and acc.is_group == 1:
                data.append({
                    "account_number": acc.account_number or "",
                    "account": acc.account_name,
                    "debit": None,
                    "credit": None,
                    "is_group_header": 1,
                    "indent": acc.depth
                })
                stack.append(acc)
            else:
                # Leaf at this level
                data.append({
                    "account_number": acc.account_number or "",
                    "account": acc.account_name,
                    "debit": acc.debit,
                    "credit": acc.credit,
                    "is_leaf": 1,
                    "indent": acc.depth
                })
                
        # Close any remaining groups on stack
        while stack:
            closed = stack.pop()
            data.append({
                "account_number": "",
                "account": f"Total de {closed.account_number or ''} {closed.account_name}",
                "debit": closed.debit,
                "credit": closed.credit,
                "is_total": 1,
                "is_group_total": 1,
                "indent": closed.depth
            })
            
        # Add grand total row
        grand_debit = sum(acc.debit for acc in accounts_data if get_depth(acc.account) == 0)
        grand_credit = sum(acc.credit for acc in accounts_data if get_depth(acc.account) == 0)
        
        data.append({"account_number": "", "account": "", "debit": 0, "credit": 0}) # Spacer
        data.append({
            "account_number": "",
            "account": _("Total Libro Diario:"),
            "debit": grand_debit,
            "credit": grand_credit,
            "is_total": 1,
            "is_group": 1
        })
        
    else:
        # DETAILED/SUMMARIZED (transactional layout)
        columns = [
            {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 100},
            {"fieldname": "voucher_no", "label": _("Referencia / Comprobante"), "fieldtype": "Data", "width": 180},
            {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Data", "width": 250},
            {"fieldname": "narration", "label": _("Descripción / Glosa"), "fieldtype": "Data", "width": 250},
            {"fieldname": "debit", "label": _("Débito (Debe)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "credit", "label": _("Crédito (Haber)"), "fieldtype": "Currency", "width": 120}
        ]
        
        query = """
            SELECT 
                gle.posting_date, 
                gle.voucher_no, 
                gle.voucher_type,
                gle.account, 
                gle.remarks, 
                gle.debit, 
                gle.credit,
                COALESCE(
                    CASE 
                        WHEN gle.voucher_type = 'Sales Invoice' THEN NULLIF(si.bill_no, '')
                        WHEN gle.voucher_type = 'Purchase Invoice' THEN NULLIF(pi.bill_no, '')
                        WHEN gle.voucher_type = 'Payment Entry' THEN NULLIF(pe.reference_no, '')
                        WHEN gle.voucher_type = 'Journal Entry' THEN NULLIF(je.cheque_no, '')
                        WHEN gle.voucher_type = 'VE Sales Debit Note' THEN NULLIF(vsdn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Sales Credit Note' THEN NULLIF(vscn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Purchase Debit Note' THEN NULLIF(vpdn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Purchase Credit Note' THEN NULLIF(vpcn.bill_no, '')
                        ELSE NULL
                    END,
                    gle.voucher_no
                ) as display_ref
            FROM `tabGL Entry` gle
            LEFT JOIN `tabSales Invoice` si ON gle.voucher_no = si.name AND gle.voucher_type = 'Sales Invoice'
            LEFT JOIN `tabPurchase Invoice` pi ON gle.voucher_no = pi.name AND gle.voucher_type = 'Purchase Invoice'
            LEFT JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name AND gle.voucher_type = 'Payment Entry'
            LEFT JOIN `tabJournal Entry` je ON gle.voucher_no = je.name AND gle.voucher_type = 'Journal Entry'
            LEFT JOIN `tabVE Sales Debit Note` vsdn ON gle.voucher_no = vsdn.name AND gle.voucher_type = 'VE Sales Debit Note'
            LEFT JOIN `tabVE Sales Credit Note` vscn ON gle.voucher_no = vscn.name AND gle.voucher_type = 'VE Sales Credit Note'
            LEFT JOIN `tabVE Purchase Debit Note` vpdn ON gle.voucher_no = vpdn.name AND gle.voucher_type = 'VE Purchase Debit Note'
            LEFT JOIN `tabVE Purchase Credit Note` vpcn ON gle.voucher_no = vpcn.name AND gle.voucher_type = 'VE Purchase Credit Note'
            WHERE gle.company = %s AND gle.docstatus = 1 AND gle.posting_date >= %s AND gle.posting_date <= %s
            ORDER BY gle.posting_date, gle.voucher_no, gle.creation
        """
        gl_entries = frappe.db.sql(query, (company, from_date, to_date), as_dict=True)
        
        data = []
        
        if presentation == "Resumido":
            # Group by voucher_no and summarize debits and credits
            summary = {}
            for entry in gl_entries:
                key = entry.voucher_no
                if key not in summary:
                    summary[key] = {
                        "posting_date": entry.posting_date,
                        "voucher_no": entry.display_ref,
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
                    "voucher_no": entry.display_ref,
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

    company_rif = frappe.db.get_value("Company", company, "tax_id") or ""
    company_logo = frappe.db.get_value("Company", company, "company_logo") or ""

    # Resolve company address
    company_address = ""
    try:
        comp_doc = frappe.get_cached_doc("Company", company)
        if comp_doc.get("custom_company_primary_address"):
            addr = frappe.get_cached_doc("Address", comp_doc.custom_company_primary_address)
            addr_parts = [addr.address_line1]
            if addr.address_line2:
                addr_parts.append(addr.address_line2)
            if addr.city:
                addr_parts.append(addr.city)
            if addr.state:
                addr_parts.append(addr.state)
            if addr.country:
                addr_parts.append(addr.country)
            company_address = ", ".join([p for p in addr_parts if p])
    except Exception:
        pass

    for r in data:
        r["company_rif"] = company_rif
        r["company_address"] = company_address
        r["company_logo"] = company_logo

    return columns, data, None, None, None
