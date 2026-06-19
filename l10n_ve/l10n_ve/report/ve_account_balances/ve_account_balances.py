# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from l10n_ve.utils.accounting import get_hierarchical_balances

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    to_date = filters.get("to_date")
    
    columns = [
        {"fieldname": "account", "label": _("Cuenta"), "fieldtype": "Data", "width": 300},
        {"fieldname": "balance", "label": _("Saldo Neto"), "fieldtype": "Currency", "width": 120}
    ]
    
    balances = get_hierarchical_balances(company, to_date)
    
    data = []
    total_debit = 0.0
    total_credit = 0.0
    
    for b in balances:
        if b.debit == 0 and b.credit == 0 and b.balance == 0:
            continue
        if b.is_group == 1:
            continue
            
        data.append({
            "account": b.account,
            "account_number": b.account_number,
            "debit": b.debit,
            "credit": b.credit,
            "balance": b.balance,
            "is_group": b.is_group
        })
        
        # Accumulate only leaf accounts for grand total
        if b.is_group == 0:
            total_debit += float(b.debit)
            total_credit += float(b.credit)
            
    # Add grand total row
    data.append({
        "account": _("TOTAL GENERAL DE SALDOS"),
        "account_number": "",
        "debit": total_debit,
        "credit": total_credit,
        "balance": total_debit - total_credit,
        "is_group": 1,
        "is_total": 1
    })
    
    return columns, data, None, None, None
