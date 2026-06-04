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
    cost_center = filters.get("cost_center")
    
    columns = [
        {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 100},
        {"fieldname": "reference", "label": _("Referencia / Comprobante"), "fieldtype": "Data", "width": 180},
        {"fieldname": "remarks", "label": _("Glosa / Detalle"), "fieldtype": "Data", "width": 250},
        {"fieldname": "debit", "label": _("Débito (Debe)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "credit", "label": _("Crédito (Haber)"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "balance", "label": _("Saldo"), "fieldtype": "Currency", "width": 130}
    ]
    
    # Pre-calculate CC condition
    cc_cond = ""
    cc_args = []
    if cost_center:
        cc_cond = " AND cost_center = %s"
        cc_args = [cost_center]

    # 1. Fetch beginning balances (before from_date)
    init_query = f"""
        SELECT account, SUM(debit - credit) as balance
        FROM `tabGL Entry`
        WHERE company = %s AND docstatus = 1 AND posting_date < %s {cc_cond}
        GROUP BY account
    """
    init_balances_raw = frappe.db.sql(init_query, tuple([company, from_date] + cc_args), as_dict=True)
    init_balances = {b.account: float(b.balance) for b in init_balances_raw}
    
    # 2. Fetch all GL entries in date range
    entries_query = f"""
        SELECT posting_date, voucher_no, account, remarks, debit, credit
        FROM `tabGL Entry`
        WHERE company = %s AND docstatus = 1 AND posting_date >= %s AND posting_date <= %s {cc_cond}
        ORDER BY account, posting_date, creation
    """
    entries = frappe.db.sql(entries_query, tuple([company, from_date, to_date] + cc_args), as_dict=True)
    
    # Group entries by account
    account_entries = {}
    for entry in entries:
        if entry.account not in account_entries:
            account_entries[entry.account] = []
        account_entries[entry.account].append(entry)
        
    # Get all active accounts in the period or with opening balance
    all_accounts = set(init_balances.keys()) | set(account_entries.keys())
    
    data = []
    
    # Sort accounts by name or code to display sequentially
    for acc in sorted(all_accounts):
        acc_entries = account_entries.get(acc, [])
        opening_bal = init_balances.get(acc, 0.0)
        
        # Header row for the account
        data.append({
            "posting_date": "",
            "reference": f"CUENTA: {acc}",
            "remarks": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": 0.0,
            "is_header": 1
        })
        
        # Opening balance row
        data.append({
            "posting_date": from_date,
            "reference": _("SALDO INICIAL"),
            "remarks": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": opening_bal,
            "is_opening": 1
        })
        
        running_balance = opening_bal
        total_debit = 0.0
        total_credit = 0.0
        
        # Entry rows
        for entry in acc_entries:
            deb = float(entry.debit)
            cred = float(entry.credit)
            running_balance += (deb - cred)
            total_debit += deb
            total_credit += cred
            
            data.append({
                "posting_date": entry.posting_date,
                "reference": entry.voucher_no,
                "remarks": entry.remarks,
                "debit": deb,
                "credit": cred,
                "balance": running_balance
            })
            
        # Total row for the account
        data.append({
            "posting_date": "",
            "reference": _("  Total Cuenta"),
            "remarks": "",
            "debit": total_debit,
            "credit": total_credit,
            "balance": running_balance,
            "is_total": 1
        })
        
        # Spacer row
        data.append({"posting_date": "", "reference": "", "remarks": "", "debit": 0, "credit": 0, "balance": 0})
        
    return columns, data, None, None, None
