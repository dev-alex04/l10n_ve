# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint

def execute(filters=None):
    if not filters:
        filters = {}
        
    company = filters.get("company")
    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    cost_center = filters.get("cost_center")
    account = filters.get("account")
    
    # RIF de la Empresa
    company_rif = frappe.db.get_value("Company", company, "tax_id") or ""
    
    columns = [
        {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 90},
        {"fieldname": "voucher_no", "label": _("Número de Comprob."), "fieldtype": "Data", "width": 130},
        {"fieldname": "party_name", "label": _("Auxiliar"), "fieldtype": "Data", "width": 100},
        {"fieldname": "ref_code", "label": _("Ref."), "fieldtype": "Data", "width": 80},
        {"fieldname": "remarks", "label": _("Descripción"), "fieldtype": "Data", "width": 250},
        {"fieldname": "debit", "label": _("Monto Debe"), "fieldtype": "Currency", "width": 110},
        {"fieldname": "credit", "label": _("Monto Haber"), "fieldtype": "Currency", "width": 110},
        {"fieldname": "balance", "label": _("Saldo"), "fieldtype": "Currency", "width": 120},
        {"fieldname": "posting_date_ref", "label": _("Fecha del Asiento"), "fieldtype": "Date", "width": 90}
    ]
    
    # Pre-calculate CC condition
    cc_cond = ""
    cc_args = []
    if cost_center:
        cc_cond = " AND cost_center = %s"
        cc_args = [cost_center]

    # Pre-calculate Account condition
    acc_cond = ""
    acc_args = []
    if account:
        acc_cond = " AND account = %s"
        acc_args = [account]

    # Fetch accounts metadata
    accounts_raw = frappe.db.get_all("Account", fields=["name", "account_number", "account_name"])
    accounts_meta = {
        a.name: {"number": a.account_number or "", "name": a.account_name or ""}
        for a in accounts_raw
    }

    # Un asiento anulado conserva docstatus = 1: GL Entry se emite al crearse y la
    # cancelación solo pone is_cancelled = 1 (erpnext/accounts/general_ledger.py,
    # `UPDATE tabGL Entry SET is_cancelled = 1 ... where voucher_type=%s and voucher_no=%s`).
    # No existen borradores ni docstatus = 2, así que el docstatus va fijo y la casilla
    # controla únicamente is_cancelled.
    include_cancelled = cint(filters.get("include_cancelled"))
    cancelled_cond = "" if include_cancelled else " AND IFNULL(is_cancelled, 0) = 0"

    # 1. Fetch beginning balances (before from_date)
    # El saldo inicial NUNCA incluye anulados, ni con la casilla activa: es un
    # SUM(debit - credit) y los anulados no netean a cero por cuenta (en producción dejan
    # ~2,8 MM de residuo en Cuentas por Cobrar), así que incluirlos descuadraría el saldo
    # de arranque contra el de cierre. La casilla sirve para AUDITAR los movimientos
    # anulados del período, no para reescribir el saldo previo.
    init_query = f"""
        SELECT account, SUM(debit - credit) as balance
        FROM `tabGL Entry`
        WHERE company = %s AND docstatus = 1 AND IFNULL(is_cancelled, 0) = 0
              AND posting_date < %s {cc_cond} {acc_cond}
        GROUP BY account
    """
    init_balances_raw = frappe.db.sql(init_query, tuple([company, from_date] + cc_args + acc_args), as_dict=True)
    init_balances = {b.account: float(b.balance) for b in init_balances_raw}

    # 2. Fetch all GL entries in date range
    entries_query = f"""
        SELECT name as gle_id, posting_date, voucher_no, account, remarks, debit, credit, party, party_type, is_cancelled
        FROM `tabGL Entry`
        WHERE company = %s AND docstatus = 1 {cancelled_cond} AND posting_date >= %s AND posting_date <= %s {cc_cond} {acc_cond}
        ORDER BY account, posting_date, creation
    """
    entries = frappe.db.sql(entries_query, tuple([company, from_date, to_date] + cc_args + acc_args), as_dict=True)

    # Cargar solo los terceros presentes en las entradas (evita traer Supplier/Customer completos)
    supplier_ids = {e.party for e in entries if e.party_type == "Supplier" and e.party}
    customer_ids = {e.party for e in entries if e.party_type == "Customer" and e.party}
    suppliers = (
        {s.name: s.supplier_name for s in frappe.db.get_all(
            "Supplier", filters={"name": ["in", list(supplier_ids)]}, fields=["name", "supplier_name"])}
        if supplier_ids else {}
    )
    customers = (
        {c.name: c.customer_name for c in frappe.db.get_all(
            "Customer", filters={"name": ["in", list(customer_ids)]}, fields=["name", "customer_name"])}
        if customer_ids else {}
    )
    
    # Group entries by account
    account_entries = {}
    for entry in entries:
        if entry.account not in account_entries:
            account_entries[entry.account] = []
        account_entries[entry.account].append(entry)
        
    # Get all active accounts in the period or with opening balance
    all_accounts = set(init_balances.keys()) | set(account_entries.keys())
    
    # We want to sort accounts by their account number/code
    def get_account_sort_key(acc_name):
        meta = accounts_meta.get(acc_name, {})
        return meta.get("number") or acc_name

    sorted_accounts = sorted(all_accounts, key=get_account_sort_key)
    
    data = []
    
    for acc in sorted_accounts:
        acc_entries = account_entries.get(acc, [])
        opening_bal = init_balances.get(acc, 0.0)
        
        acc_number = accounts_meta.get(acc, {}).get("number") or ""
        acc_name = accounts_meta.get(acc, {}).get("name") or acc
        
        # Header row for the account
        data.append({
            "posting_date": "",
            "voucher_no": "",
            "party": "",
            "party_name": "",
            "ref_code": "",
            "remarks": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": 0.0,
            "posting_date_ref": "",
            "is_header": 1,
            "account_number": acc_number,
            "account_name": acc_name,
            "company_rif": company_rif
        })
        
        # Opening balance row
        data.append({
            "posting_date": from_date,
            "voucher_no": _("SALDO INICIAL"),
            "party": "",
            "party_name": "",
            "ref_code": "",
            "remarks": "",
            "debit": 0.0,
            "credit": 0.0,
            "balance": opening_bal,
            "posting_date_ref": from_date,
            "is_opening": 1,
            "account_number": acc_number,
            "account_name": acc_name,
            "company_rif": company_rif
        })
        
        running_balance = opening_bal
        total_debit = 0.0
        total_credit = 0.0
        
        # Entry rows
        for entry in acc_entries:
            deb = float(entry.debit)
            cred = float(entry.credit)
            entry_cancelled = cint(entry.get("is_cancelled"))

            # Un asiento anulado se lista para auditoría pero NO mueve el saldo ni los
            # totales de la cuenta: contablemente no existe. Si acumulara, el "Saldo" y el
            # "Total Cuenta" se irían del saldo real por el monto de lo anulado, y la
            # casilla dejaría de ser una vista de auditoría para volverse un reporte mal
            # cuadrado.
            if not entry_cancelled:
                running_balance += (deb - cred)
                total_debit += deb
                total_credit += cred

            # La marca va en el propio voucher_no porque el print format
            # (ve_analytical_ledger.html) imprime ese campo tal cual y arma los <td> a mano:
            # así el anulado se distingue igual en pantalla y en el PDF, sin tener que
            # mantener una columna extra en dos lugares.
            voucher_label = entry.voucher_no
            if entry_cancelled:
                voucher_label = _("CANCELADO · {0}").format(entry.voucher_no or "")

            # Formatear Ref. (quitar prefijo GLE-)
            ref_val = entry.gle_id.replace("GLE-", "") if entry.gle_id else ""
            
            # Nombre de tercero
            p_name = ""
            if entry.party_type == "Supplier":
                p_name = suppliers.get(entry.party, "")
            elif entry.party_type == "Customer":
                p_name = customers.get(entry.party, "")
            
            data.append({
                "posting_date": entry.posting_date,
                "voucher_no": voucher_label,
                "party": entry.party or "",
                "party_name": p_name,
                "ref_code": ref_val,
                "remarks": entry.remarks,
                "debit": deb,
                "credit": cred,
                "balance": running_balance,
                "posting_date_ref": entry.posting_date,
                "account_number": acc_number,
                "account_name": acc_name,
                "company_rif": company_rif,
                "is_cancelled": entry_cancelled
            })
            
        # Total row for the account
        data.append({
            "posting_date": "",
            "voucher_no": _("Total Cuenta"),
            "party": "",
            "party_name": "",
            "ref_code": "",
            "remarks": "",
            "debit": total_debit,
            "credit": total_credit,
            "balance": running_balance,
            "posting_date_ref": "",
            "is_total": 1,
            "account_number": acc_number,
            "account_name": acc_name,
            "company_rif": company_rif
        })
        
        # Spacer row
        data.append({
            "posting_date": "", "voucher_no": "", "party": "", "party_name": "", "ref_code": "", "remarks": "",
            "debit": 0, "credit": 0, "balance": 0, "posting_date_ref": "", "is_spacer": 1,
            "company_rif": company_rif
        })
        
    return columns, data, None, None, None

