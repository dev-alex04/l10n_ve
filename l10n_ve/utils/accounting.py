# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _

def get_hierarchical_balances(company, to_date, from_date=None, cost_center=None, root_types=None):
    """
    Obtiene las cuentas y sus saldos consolidados/jerárquicos (roll-up) usando los conjuntos anidados (lft, rgt) de tabAccount.
    Retorna una lista de diccionarios ordenada por lft.
    """
    gl_cond = ""
    args = []
    
    if from_date:
        gl_cond += " AND gl.posting_date >= %s"
        args.append(from_date)
        
    gl_cond += " AND gl.posting_date <= %s"
    args.append(to_date)
    
    if cost_center:
        gl_cond += " AND gl.cost_center = %s"
        args.append(cost_center)
        
    root_type_cond = ""
    if root_types:
        if isinstance(root_types, str):
            root_types = [root_types]
        root_type_cond = " AND parent.root_type IN ({})".format(", ".join(["%s"] * len(root_types)))
        # Correct order: args (for gl_cond) + [company] + list(root_types)
        query_args = args + [company] + list(root_types)
    else:
        query_args = args + [company]
        
    query = f"""
        SELECT 
            parent.name as account,
            parent.account_number,
            parent.account_name,
            parent.parent_account,
            parent.is_group,
            parent.root_type,
            parent.report_type,
            parent.lft,
            parent.rgt,
            COALESCE(SUM(gl.debit - gl.credit), 0) as balance,
            COALESCE(SUM(gl.debit), 0) as debit,
            COALESCE(SUM(gl.credit), 0) as credit
        FROM 
            `tabAccount` parent
        LEFT JOIN 
            `tabAccount` child ON child.lft >= parent.lft AND child.rgt <= parent.rgt AND child.company = parent.company
        LEFT JOIN 
            `tabGL Entry` gl ON gl.account = child.name AND gl.docstatus = 1 AND gl.company = parent.company {gl_cond}
        WHERE 
            parent.company = %s {root_type_cond}
        GROUP BY 
            parent.name
        ORDER BY 
            parent.lft
    """
    
    return frappe.db.sql(query, tuple(query_args), as_dict=True)

def get_disclosure_note(company, to_date, section):
    """
    Obtiene la nota revelatoria cualitativa para una sección y año fiscal.
    """
    # Encontrar el año fiscal correspondiente a la fecha to_date
    fiscal_year = frappe.db.get_value("Fiscal Year", {
        "year_start_date": ["<=", to_date],
        "year_end_date": [">=", to_date]
    }, "name")
    
    if not fiscal_year:
        # Fallback al año actual si no se encuentra
        fiscal_year = to_date[:4]
        
    note = frappe.db.get_value("VE Disclosure Note", {
        "company": company,
        "fiscal_year": fiscal_year,
        "section": section
    }, "note")
    
    return note or ""
