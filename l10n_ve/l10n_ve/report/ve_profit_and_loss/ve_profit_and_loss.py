# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from l10n_ve.utils.accounting import get_hierarchical_balances, get_disclosure_note

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    cost_center = filters.get("cost_center")
    presentation = filters.get("presentation") or "1 Columna"
    
    # Query accounts for P&L (Income, Expense)
    root_types = ["Income", "Expense"]
    accounts_data = get_hierarchical_balances(company, to_date, from_date=from_date, cost_center=cost_center, root_types=root_types)
    
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

    # Construct columns
    if presentation == "3 Columnas (por niveles)":
        columns = [
            {"fieldname": "account", "label": _("Cuenta"), "fieldtype": "Data", "width": 300},
            {"fieldname": "account_number", "label": _("Código"), "fieldtype": "Data", "width": 120},
            {"fieldname": "sub_detalle", "label": _("Sub-detalle"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "detalle", "label": _("Detalle"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "total", "label": _("Total"), "fieldtype": "Currency", "width": 120}
        ]
    else:
        columns = [
            {"fieldname": "account", "label": _("Cuenta"), "fieldtype": "Data", "width": 350},
            {"fieldname": "account_number", "label": _("Código"), "fieldtype": "Data", "width": 150},
            {"fieldname": "balance", "label": _("Balance"), "fieldtype": "Currency", "width": 150}
        ]
        
    data = []
    total_revenues = 0.0
    total_expenses = 0.0
    
    # Populate rows
    for acc in accounts_data:
        if acc.balance == 0:
            continue
            
        depth = get_depth(acc.account)
        
        row = {
            "account": acc.account,
            "account_name": acc.account_name,
            "account_number": acc.account_number,
            "is_group": acc.is_group,
            "is_header": (depth == 0),
            "is_total": (acc.is_group == 1 and depth > 0),
        }
        
        # Revenues (Income) typically credit-heavy, expenses typically debit-heavy
        # Multiplier to show positive numbers in the financial statement
        multiplier = -1.0 if acc.root_type == "Income" else 1.0
        display_balance = acc.balance * multiplier
        
        # Accumulate net values for root level accounts
        if depth == 0:
            if acc.root_type == "Income":
                total_revenues += display_balance
            else:
                total_expenses += display_balance
        
        if presentation == "3 Columnas (por niveles)":
            if depth == 0:
                row["total"] = display_balance
            elif depth == 1:
                row["detalle"] = display_balance
            else:
                if acc.is_group == 0:
                    row["sub_detalle"] = display_balance
                else:
                    row["detalle"] = display_balance
        else:
            row["balance"] = display_balance
            
        data.append(row)
        
    # Append Net Profit / Loss Row at the end
    net_profit = total_revenues - total_expenses
    row_profit = {
        "account": _("Utilidad o Pérdida Neta del Ejercicio"),
        "account_name": _("Utilidad o Pérdida Neta del Ejercicio"),
        "account_number": "",
        "is_group": 1,
        "is_header": 0,
        "is_total": 1,
    }
    if presentation == "3 Columnas (por niveles)":
        row_profit["total"] = net_profit
    else:
        row_profit["balance"] = net_profit
        
    data.append(row_profit)
        
    # Notes & signatures
    message = ""
    note = get_disclosure_note(company, to_date, "Estado de Resultados")
    if note:
        message = f"""
            <div class='disclosure-notes' style='margin-top: 30px; border-top: 2px solid #e2e8f0; padding-top: 15px;'>
                <h5 style='font-weight: bold;'>{_("Notas Revelatorias:")}</h5>
                <div style='color: #4a5568;'>{note}</div>
            </div>
        """
        
    # Append signatures section
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
