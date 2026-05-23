import frappe
from frappe.utils import flt

def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {"label": "Cuenta Contable", "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 250},
        {"label": "Saldo Inicial", "fieldname": "opening_balance", "fieldtype": "Currency", "width": 120},
        {"label": "Debe", "fieldname": "debit", "fieldtype": "Currency", "width": 120},
        {"label": "Haber", "fieldname": "credit", "fieldtype": "Currency", "width": 120},
        {"label": "Saldo a la Fecha", "fieldname": "closing_balance", "fieldtype": "Currency", "width": 140},
    ]

def get_data(filters):
    if not filters:
        filters = {}

    company = filters.get("company")
    if not company:
        return []

    # 1. Obtener todas las cuentas ordenadas por su código (lft) para mantener la jerarquía
    accounts = frappe.get_all("Account", 
        filters={"company": company},
        fields=["name", "account_name", "is_group", "lft", "rgt"],
        order_by="lft"
    )

    # Mapa para búsqueda rápida de cuentas y sus atributos de jerarquía (lft/rgt)
    account_map = {acc.name: acc for acc in accounts}

    # 2. Obtener los saldos consolidados de GL Entry en una sola consulta
    gl_entries = frappe.db.sql("""
        SELECT 
            account,
            SUM(CASE WHEN posting_date < %(from_date)s THEN debit - credit ELSE 0 END) as opening,
            SUM(CASE WHEN posting_date BETWEEN %(from_date)s AND %(to_date)s THEN debit ELSE 0 END) as debit,
            SUM(CASE WHEN posting_date BETWEEN %(from_date)s AND %(to_date)s THEN credit ELSE 0 END) as credit
        FROM `tabGL Entry`
        WHERE company = %(company)s AND is_cancelled = 0
        GROUP BY account
    """, filters, as_dict=1)

    # Mapa para búsqueda rápida de saldos en cuentas hojas
    gl_map = {d.account: d for d in gl_entries}

    data = []
    
    # 3. Consolidar balances recursivamente en memoria (Python)
    for acc in accounts:
        opening = 0.0
        debit = 0.0
        credit = 0.0

        # Sumamos los saldos de todas las cuentas hojas descendientes de la cuenta actual
        for leaf_name, leaf_bal in gl_map.items():
            leaf_acc = account_map.get(leaf_name)
            if leaf_acc and leaf_acc.lft >= acc.lft and leaf_acc.rgt <= acc.rgt:
                opening += flt(leaf_bal.get("opening", 0.0))
                debit += flt(leaf_bal.get("debit", 0.0))
                credit += flt(leaf_bal.get("credit", 0.0))

        closing = opening + debit - credit

        # Solo agregamos si hay movimiento/saldo o si el filtro indica mostrar cuentas en cero
        if filters.get("show_zero_values") or opening or debit or credit or closing:
            data.append({
                "account": acc.name,
                "opening_balance": opening,
                "debit": debit,
                "credit": credit,
                "closing_balance": closing,
                "is_group": acc.is_group
            })

    return data