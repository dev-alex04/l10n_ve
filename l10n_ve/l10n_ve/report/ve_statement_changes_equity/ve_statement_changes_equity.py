# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, getdate
from l10n_ve.utils.accounting import get_hierarchical_balances, get_disclosure_note

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    
    prev_date = str(add_days(getdate(from_date), -1))
    
    # Get balances for Equity root type
    end_balances = get_hierarchical_balances(company, to_date, root_types=["Equity"])
    start_balances = get_hierarchical_balances(company, prev_date, root_types=["Equity"])
    
    # Map balances
    end_map = {b.account: b for b in end_balances}
    start_map = {b.account: b for b in start_balances}
    
    # Define equity categories
    def get_category(acc_name):
        acc_lower = acc_name.lower()
        if "capital" in acc_lower:
            return "capital"
        elif "reserva" in acc_lower or "reserve" in acc_lower:
            return "reservas"
        else:
            return "resultados"
            
    # Calculate initial balances
    init_capital = 0.0
    init_reserves = 0.0
    init_retained = 0.0
    
    for acc_id, acc in start_map.items():
        if acc.is_group == 0:
            val = acc.balance * -1.0 # Invert credit balance to positive
            cat = get_category(acc.account_name)
            if cat == "capital":
                init_capital += val
            elif cat == "reservas":
                init_reserves += val
            else:
                init_retained += val
                
    # Calculate ending balances
    end_capital = 0.0
    end_reserves = 0.0
    end_retained = 0.0
    
    for acc_id, acc in end_map.items():
        if acc.is_group == 0:
            val = acc.balance * -1.0
            cat = get_category(acc.account_name)
            if cat == "capital":
                end_capital += val
            elif cat == "reservas":
                end_reserves += val
            else:
                end_retained += val

    # Net Income for the period (Revenue - Expenses) to add to Retained Earnings
    # We query it directly
    net_bal = frappe.db.sql("""
        SELECT SUM(credit - debit)
        FROM `tabGL Entry` gl
        JOIN `tabAccount` a ON gl.account = a.name
        WHERE gl.company = %s AND gl.docstatus = 1 
          AND gl.posting_date >= %s AND gl.posting_date <= %s
          AND a.root_type IN ('Income', 'Expense')
    """, (company, from_date, to_date))
    net_income = float(net_bal[0][0] or 0.0)
    
    # Capital changes
    capital_increase = end_capital - init_capital
    # Reserves changes
    reserves_increase = end_reserves - init_reserves
    # Other changes / dividends (remaining change in retained earnings not accounted by Net Income)
    other_retained_changes = (end_retained - init_retained) - net_income

    columns = [
        {"fieldname": "concept", "label": _("Concepto"), "fieldtype": "Data", "width": 250},
        {"fieldname": "capital", "label": _("Capital Social"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "reservas", "label": _("Reservas"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "resultados", "label": _("Resultados Acumulados"), "fieldtype": "Currency", "width": 160},
        {"fieldname": "total", "label": _("Total Patrimonio"), "fieldtype": "Currency", "width": 160}
    ]

    data = [
        {
            "concept": _("Saldo al Inicio del Período ({})").format(from_date),
            "capital": init_capital,
            "reservas": init_reserves,
            "resultados": init_retained,
            "total": init_capital + init_reserves + init_retained
        },
        {
            "concept": _("Aumentos de Capital"),
            "capital": capital_increase,
            "reservas": 0.0,
            "resultados": 0.0,
            "total": capital_increase
        },
        {
            "concept": _("Incremento de Reservas"),
            "capital": 0.0,
            "reservas": reserves_increase,
            "resultados": 0.0,
            "total": reserves_increase
        },
        {
            "concept": _("Utilidad o Pérdida Neta del Ejercicio"),
            "capital": 0.0,
            "reservas": 0.0,
            "resultados": net_income,
            "total": net_income
        },
        {
            "concept": _("Distribución de Dividendos y Otros Cambios"),
            "capital": 0.0,
            "reservas": 0.0,
            "resultados": other_retained_changes,
            "total": other_retained_changes
        },
        {
            "concept": _("Saldo al Final del Período ({})").format(to_date),
            "capital": end_capital,
            "reservas": end_reserves,
            "resultados": end_retained,
            "total": end_capital + end_reserves + end_retained,
            "is_total": 1,
            "is_group": 1
        }
    ]

    message = ""
    note = get_disclosure_note(company, to_date, "Estado de Situación Patrimonial")
    if note:
        message = f"""
            <div class='disclosure-notes' style='margin-top: 30px; border-top: 2px solid #e2e8f0; padding-top: 15px;'>
                <h5 style='font-weight: bold;'>{_("Notas Revelatorias:")}</h5>
                <div style='color: #4a5568;'>{note}</div>
            </div>
        """

    return columns, data, message, None, None
