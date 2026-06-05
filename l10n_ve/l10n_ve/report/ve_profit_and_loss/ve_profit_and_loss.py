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
    
    val_ingresos = 0.0
    val_costos = 0.0
    val_gastos = 0.0
    inserted_ub = False
    inserted_uo = False
    
    # Populate rows
    for acc in accounts_data:
        if acc.balance == 0:
            continue
            
        depth = get_depth(acc.account)
        
        # Revenues (Income) typically credit-heavy, expenses typically debit-heavy
        # Multiplier to show positive numbers in the financial statement
        multiplier = -1.0 if acc.root_type == "Income" else 1.0
        display_balance = acc.balance * multiplier
        
        # Extract totals for intermediate calculations
        code = acc.account_number or ""
        if code == '4' or (code.startswith('4') and depth == 0):
            val_ingresos = display_balance
        elif code == '5' or (code.startswith('5') and depth == 0):
            val_costos = display_balance
        elif code == '6' or (code.startswith('6') and depth == 0):
            val_gastos = display_balance
            
        # Check if we need to insert Utilidad Bruta
        if not inserted_ub and code and (code.startswith('6') or code.startswith('7') or code.startswith('8')):
            utilidad_bruta = val_ingresos - val_costos
            row_ub = {
                "account": _("Utilidad Bruta"),
                "account_name": _("Utilidad Bruta"),
                "account_number": "",
                "parent_account": None,
                "is_group": 0,
                "is_header": 1,
                "is_total": 0,
                "root_type": "Income",
                "depth": 0,
                "lft": 999990,
                "rgt": 999991,
            }
            if presentation == "3 Columnas (por niveles)":
                row_ub["total"] = utilidad_bruta
            else:
                row_ub["balance"] = utilidad_bruta
            data.append(row_ub)
            inserted_ub = True
            
        # Check if we need to insert Utilidad Operativa
        if not inserted_uo and code and (code.startswith('7') or code.startswith('8')):
            utilidad_operativa = val_ingresos - val_costos - val_gastos
            row_uo = {
                "account": _("Utilidad Operativa (EBIT)"),
                "account_name": _("Utilidad Operativa (EBIT)"),
                "account_number": "",
                "parent_account": None,
                "is_group": 0,
                "is_header": 1,
                "is_total": 0,
                "root_type": "Income",
                "depth": 0,
                "lft": 999992,
                "rgt": 999993,
            }
            if presentation == "3 Columnas (por niveles)":
                row_uo["total"] = utilidad_operativa
            else:
                row_uo["balance"] = utilidad_operativa
            data.append(row_uo)
            inserted_uo = True

        row = {
            "account": acc.account,
            "account_name": acc.account_name,
            "account_number": acc.account_number,
            "parent_account": acc.parent_account,
            "is_group": acc.is_group,
            "is_header": (depth == 0),
            "is_total": (acc.is_group == 1 and depth > 0),
            "root_type": acc.root_type,
            "depth": depth,
            "lft": acc.lft,
            "rgt": acc.rgt,
        }
        
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
        
    # Append fallback intermediate rows if not inserted
    if not inserted_ub:
        utilidad_bruta = val_ingresos - val_costos
        row_ub = {
            "account": _("Utilidad Bruta"),
            "account_name": _("Utilidad Bruta"),
            "account_number": "",
            "parent_account": None,
            "is_group": 0,
            "is_header": 1,
            "is_total": 0,
            "root_type": "Income",
            "depth": 0,
            "lft": 999990,
            "rgt": 999991,
        }
        if presentation == "3 Columnas (por niveles)":
            row_ub["total"] = utilidad_bruta
        else:
            row_ub["balance"] = utilidad_bruta
        data.append(row_ub)
        inserted_ub = True
        
    if not inserted_uo:
        utilidad_operativa = val_ingresos - val_costos - val_gastos
        row_uo = {
            "account": _("Utilidad Operativa (EBIT)"),
            "account_name": _("Utilidad Operativa (EBIT)"),
            "account_number": "",
            "parent_account": None,
            "is_group": 0,
            "is_header": 1,
            "is_total": 0,
            "root_type": "Income",
            "depth": 0,
            "lft": 999992,
            "rgt": 999993,
            "balance": utilidad_operativa
        }
        if presentation == "3 Columnas (por niveles)":
            row_uo["total"] = utilidad_operativa
        else:
            row_uo["balance"] = utilidad_operativa
        data.append(row_uo)
        inserted_uo = True
        
    # Append Net Profit / Loss Row at the end
    net_profit = total_revenues - total_expenses
    row_profit = {
        "account": _("Utilidad o Pérdida Neta del Ejercicio"),
        "account_name": _("Utilidad o Pérdida Neta del Ejercicio"),
        "account_number": "",
        "parent_account": None,
        "is_group": 0,
        "is_header": 1,
        "is_total": 0,
        "root_type": "Income",
        "depth": 0,
        "lft": 999999,
        "rgt": 1000000,
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
        
    return columns, data, message, None, None
