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
    cost_center = filters.get("cost_center")
    
    # Calculate previous day for beginning balances
    prev_date = str(add_days(getdate(from_date), -1))
    
    # Get balances at end of period
    end_balances = get_hierarchical_balances(company, to_date, cost_center=cost_center)
    
    # Get balances at start of period (previous date)
    start_balances = get_hierarchical_balances(company, prev_date, cost_center=cost_center)
    
    # Map balances by account for quick access
    end_map = {b.account: b for b in end_balances}
    start_map = {b.account: b for b in start_balances}
    
    # Helper to calculate change in balance (Ending - Beginning) for an account or category
    def get_change(account_name=None, root_type=None, account_type=None, parent_account=None):
        end_val = 0.0
        start_val = 0.0
        
        # We only sum leaf accounts directly to avoid double counting groups
        for acc_id, acc in end_map.items():
            if acc.is_group == 0:
                match = True
                if account_name and acc.account != account_name:
                    match = False
                if root_type and acc.root_type != root_type:
                    match = False
                if account_type and acc.account_type != account_type:
                    match = False
                if parent_account and acc.parent_account != parent_account:
                    match = False
                    
                if match:
                    end_val += acc.balance
                    
        for acc_id, acc in start_map.items():
            if acc.is_group == 0:
                match = True
                if account_name and acc.account != account_name:
                    match = False
                if root_type and acc.root_type != root_type:
                    match = False
                if account_type and acc.account_type != account_type:
                    match = False
                if parent_account and acc.parent_account != parent_account:
                    match = False
                    
                if match:
                    start_val += acc.balance
                    
        return end_val - start_val

    # Helper to calculate absolute balance at a specific date
    def get_balance_at(date_map, root_type=None, account_type=None):
        val = 0.0
        for acc_id, acc in date_map.items():
            if acc.is_group == 0:
                match = True
                if root_type and acc.root_type != root_type:
                    match = False
                if account_type and acc.account_type != account_type:
                    match = False
                if match:
                    val += acc.balance
        return val

    # Cash and Cash Equivalents (Bank and Cash accounts)
    end_cash = get_balance_at(end_map, account_type="Bank") + get_balance_at(end_map, account_type="Cash")
    start_cash = get_balance_at(start_map, account_type="Bank") + get_balance_at(start_map, account_type="Cash")
    
    # 1. Operating Activities
    # Net Income for the period (Revenues - Expenses)
    revenue_change = -get_change(root_type="Income") # Revenues are credit balances (negative in raw balance, so invert)
    expense_change = get_change(root_type="Expense")
    net_income = revenue_change - expense_change
    
    # Adjustments (depreciation is debited, so it reduces net income, we add it back)
    # Typically depreciation accounts are under expenses or accumulated depreciation under assets
    depreciation_expense = 0.0
    for acc_id, acc in end_map.items():
        if "depreciation" in acc.account_name.lower() and acc.root_type == "Expense" and acc.is_group == 0:
            depreciation_expense += (acc.balance - start_map.get(acc_id, frappe._dict(balance=0)).balance)
            
    # Changes in Working Capital
    ar_change = -get_change(account_type="Receivable") # Increase in AR = decrease in cash
    inventory_change = -get_change(account_type="Stock") # Increase in Stock = decrease in cash
    ap_change = get_change(account_type="Payable") # Increase in AP = increase in cash
    
    # Other assets/liabilities operating changes
    other_asset_change = 0.0
    other_liab_change = 0.0
    for acc_id, acc in end_map.items():
        if acc.is_group == 0:
            # Exclude Cash, AR, Stock, Fixed Assets
            if acc.root_type == "Asset" and acc.account_type not in ["Bank", "Cash", "Receivable", "Stock"] and "fixed" not in acc.account_name.lower():
                other_asset_change -= (acc.balance - start_map.get(acc_id, frappe._dict(balance=0)).balance)
            # Exclude AP, Loans
            elif acc.root_type == "Liability" and acc.account_type not in ["Payable"] and "loan" not in acc.account_name.lower():
                other_liab_change += (acc.balance - start_map.get(acc_id, frappe._dict(balance=0)).balance)
                
    operating_cash_flow = net_income + depreciation_expense + ar_change + inventory_change + ap_change + other_asset_change + other_liab_change

    # 2. Investing Activities
    # Purchase/sale of Fixed Assets (Property, Plant, Equipment)
    fixed_asset_change = 0.0
    for acc_id, acc in end_map.items():
        if acc.is_group == 0 and acc.root_type == "Asset" and ("fixed" in acc.account_name.lower() or acc.account_type == "Capital Work in Progress"):
            # Exclude accumulated depreciation if it's stored in assets with negative balance
            if "accumulated" not in acc.account_name.lower():
                fixed_asset_change -= (acc.balance - start_map.get(acc_id, frappe._dict(balance=0)).balance)
                
    investing_cash_flow = fixed_asset_change

    # 3. Financing Activities
    # Changes in Equity
    equity_change = get_change(root_type="Equity")
    # Changes in Loans
    loans_change = 0.0
    for acc_id, acc in end_map.items():
        if acc.is_group == 0 and acc.root_type == "Liability" and "loan" in acc.account_name.lower():
            loans_change += (acc.balance - start_map.get(acc_id, frappe._dict(balance=0)).balance)
            
    financing_cash_flow = equity_change + loans_change

    # Summary
    net_increase_cash = operating_cash_flow + investing_cash_flow + financing_cash_flow

    columns = [
        {"fieldname": "concept", "label": _("Concepto"), "fieldtype": "Data", "width": 350},
        {"fieldname": "amount", "label": _("Monto"), "fieldtype": "Currency", "width": 150}
    ]

    data = [
        # OPERATING ACTIVITIES
        {"concept": _("Actividades de Operación"), "amount": "", "is_group": 1, "is_header": 1},
        {"concept": _("  Utilidad Neta del Ejercicio"), "amount": net_income},
        {"concept": _("  Ajuste por Depreciación y Amortización"), "amount": depreciation_expense},
        {"concept": _("  Variación en Cuentas por Cobrar"), "amount": ar_change},
        {"concept": _("  Variación en Inventarios"), "amount": inventory_change},
        {"concept": _("  Variación en Cuentas por Pagar"), "amount": ap_change},
        {"concept": _("  Variación en Otros Activos Operativos"), "amount": other_asset_change},
        {"concept": _("  Variación en Otros Pasivos Operativos"), "amount": other_liab_change},
        {"concept": _("Efectivo Neto de Actividades de Operación"), "amount": operating_cash_flow, "is_total": 1},
        
        # INVESTING ACTIVITIES
        {"concept": "", "amount": ""},
        {"concept": _("Actividades de Inversión"), "amount": "", "is_group": 1, "is_header": 1},
        {"concept": _("  Adquisición de Propiedades, Planta y Equipo"), "amount": fixed_asset_change},
        {"concept": _("Efectivo Neto de Actividades de Inversión"), "amount": investing_cash_flow, "is_total": 1},
        
        # FINANCING ACTIVITIES
        {"concept": "", "amount": ""},
        {"concept": _("Actividades de Financiamiento"), "amount": "", "is_group": 1, "is_header": 1},
        {"concept": _("  Variación en Patrimonio Neto"), "amount": equity_change},
        {"concept": _("  Variación en Préstamos y Obligaciones"), "amount": loans_change},
        {"concept": _("Efectivo Neto de Actividades de Financiamiento"), "amount": financing_cash_flow, "is_total": 1},
        
        # SUMMARY
        {"concept": "", "amount": ""},
        {"concept": _("Incremento (Disminución) Neto en Efectivo y Equivalentes"), "amount": net_increase_cash, "is_total": 1, "is_group": 1},
        {"concept": _("Efectivo y Equivalentes al Inicio del Período"), "amount": start_cash, "is_group": 1},
        {"concept": _("Efectivo y Equivalentes al Final del Período"), "amount": end_cash, "is_group": 1, "is_total": 1}
    ]

    message = ""
    note = get_disclosure_note(company, to_date, "Flujo de Efectivo")
    if note:
        message = f"""
            <div class='disclosure-notes' style='margin-top: 30px; border-top: 2px solid #e2e8f0; padding-top: 15px;'>
                <h5 style='font-weight: bold;'>{_("Notas Revelatorias:")}</h5>
                <div style='color: #4a5568;'>{note}</div>
            </div>
        """
        
    message += """
        <div class='report-signatures' style='margin-top: 50px; display: flex; justify-content: space-around; font-size: 13px;'>
            <div style='text-align: center; border-top: 1px solid #718096; width: 200px; padding-top: 5px;'>
                <b>Firma de la Gerencia</b>
            </div>
            <div style='text-align: center; border-top: 1px solid #718096; width: 200px; padding-top: 5px;'>
                <b>Firma del Contador</b><br>
                <span>C.P.C.</span>
            </div>
        </div>
    """

    return columns, data, message, None, None
