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

    # Ensure from_date and to_date are present to prevent KeyError in SQL query
    if not filters.get("from_date"):
        from frappe.utils import get_first_day, today
        filters["from_date"] = get_first_day(today())
    if not filters.get("to_date"):
        from frappe.utils import get_last_day, today
        filters["to_date"] = get_last_day(today())

    # 1. Obtener todas las cuentas ordenadas por su código (lft) para mantener la jerarquía
    accounts = frappe.get_all("Account",
        filters={"company": company},
        fields=["name", "account_name", "account_number", "is_group", "parent_account", "lft", "rgt", "root_type"],
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

    # Construir un mapa de parent -> children para poder recorrer de manera eficiente
    children_map = {}
    for acc in accounts:
        parent = acc.parent_account
        if parent:
            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append(acc)

    # Identificar las cuentas raíz (aquellas que no tienen padre en el mapa de cuentas del reporte)
    roots = [acc for acc in accounts if not acc.parent_account or acc.parent_account not in account_map]

    data = []

    def traverse_account(acc, depth=0):
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

        # Solo procesamos si hay movimiento/saldo o si se muestra en cero
        has_movement = (abs(opening) > 0.005 or abs(debit) > 0.005 or abs(credit) > 0.005 or abs(closing) > 0.005)

        if not (filters.get("show_zero_values") or has_movement):
            return 0.0, 0.0, 0.0, 0.0

        if acc.is_group:
            # Fila de Cabecera: Cuenta Contable en negrita, sin valores numéricos
            header_row = {
                "account": acc.name,
                "account_number": acc.account_number or "",
                "account_name": acc.account_name,
                "opening_balance": None,
                "debit": None,
                "credit": None,
                "closing_balance": None,
                "is_group": 1,
                "is_header": 1,
                "root_type": acc.root_type,
                "indent": depth
            }
            data.append(header_row)

            # Recorrer hijos
            children = children_map.get(acc.name, [])
            for child in children:
                traverse_account(child, depth + 1)

            # Fila de Total: consolidada de los hijos
            total_row = {
                "account": f"Total de {acc.account_number or ''} {acc.account_name}",
                "account_number": "",
                "account_name": f"Total de {acc.account_number or ''} {acc.account_name}",
                "opening_balance": opening,
                "debit": debit,
                "credit": credit,
                "closing_balance": closing,
                "is_group": 1,
                "is_total": 1,
                "root_type": acc.root_type,
                "indent": depth
            }
            data.append(total_row)
        else:
            # Fila de Hoja con sus valores
            leaf_row = {
                "account": acc.name,
                "account_number": acc.account_number or "",
                "account_name": acc.account_name,
                "opening_balance": opening,
                "debit": debit,
                "credit": credit,
                "closing_balance": closing,
                "is_group": 0,
                "root_type": acc.root_type,
                "indent": depth
            }
            data.append(leaf_row)

        return opening, debit, credit, closing

    for root in roots:
        traverse_account(root, 0)

    return data