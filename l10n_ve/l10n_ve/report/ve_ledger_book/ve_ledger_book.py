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
    presentation = filters.get("presentation") or "Detallado"
    
    company_rif = frappe.db.get_value("Company", company, "tax_id") or ""
    company_logo = frappe.db.get_value("Company", company, "company_logo") or ""

    # Resolve company address
    company_address = ""
    try:
        comp_doc = frappe.get_cached_doc("Company", company)
        if comp_doc.get("custom_company_primary_address"):
            addr = frappe.get_cached_doc("Address", comp_doc.custom_company_primary_address)
            addr_parts = [addr.address_line1]
            if addr.address_line2:
                addr_parts.append(addr.address_line2)
            if addr.city:
                addr_parts.append(addr.city)
            if addr.state:
                addr_parts.append(addr.state)
            if addr.country:
                addr_parts.append(addr.country)
            company_address = ", ".join([p for p in addr_parts if p])
    except Exception:
        pass
        
    if presentation in ["1° Nivel", "2° Nivel", "3° Nivel", "4° Nivel"]:
        from l10n_ve.utils.accounting import get_hierarchical_balances
        from datetime import datetime, timedelta
        
        meses = {
            1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
            7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
        }
        
        try:
            from_date_dt = datetime.strptime(from_date, "%Y-%m-%d")
            prev_date_dt = from_date_dt - timedelta(days=1)
            prev_date_str = prev_date_dt.strftime("%Y-%m-%d")
            
            month_name = meses.get(from_date_dt.month, "")
            year_val = from_date_dt.year
            balance_label = f"Saldo a la fecha {month_name} {year_val}"
        except Exception:
            prev_date_str = from_date
            balance_label = _("Saldo a la fecha")
            
        columns = [
            {"fieldname": "account_number", "label": _("Código"), "fieldtype": "Data", "width": 120},
            {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Data", "width": 300},
            {"fieldname": "init_balance", "label": _("Saldo Inicial"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "debit", "label": _("Debe"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "credit", "label": _("Haber"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "end_balance", "label": balance_label, "fieldtype": "Currency", "width": 140}
        ]
        
        # 1. Fetch beginning balances (before from_date)
        init_balances = get_hierarchical_balances(company, to_date=prev_date_str, cost_center=cost_center)
        init_map = {b.account: float(b.balance or 0.0) for b in init_balances}
        
        # 2. Fetch period balances (debits and credits in range)
        period_balances = get_hierarchical_balances(company, to_date=to_date, from_date=from_date, cost_center=cost_center)
        
        # Build unified accounts data list
        accounts_data = []
        for acc in period_balances:
            acc_name = acc.account
            init_bal = init_map.get(acc_name, 0.0)
            deb = float(acc.debit or 0.0)
            cred = float(acc.credit or 0.0)
            end_bal = init_bal + deb - cred
            
            acc_obj = frappe._dict({
                "account": acc_name,
                "account_number": acc.account_number,
                "account_name": acc.account_name,
                "parent_account": acc.parent_account,
                "is_group": acc.is_group,
                "lft": acc.lft,
                "rgt": acc.rgt,
                "init_balance": init_bal,
                "debit": deb,
                "credit": cred,
                "end_balance": end_bal
            })
            accounts_data.append(acc_obj)
            
        # Determine L based on presentation
        if presentation == "1° Nivel":
            L = 1
        elif presentation == "2° Nivel":
            L = 2
        elif presentation == "3° Nivel":
            L = 3
        else:
            L = 4
            
        parent_map = {acc.account: acc.parent_account for acc in accounts_data}
        depth_cache = {}
        
        def get_depth(acc_id):
            if acc_id not in parent_map or not parent_map[acc_id]:
                return 0
            if acc_id in depth_cache:
                return depth_cache[acc_id]
            d = 1 + get_depth(parent_map[acc_id])
            depth_cache[acc_id] = d
            return d
            
        def is_descendant(child, parent):
            return child.lft > parent.lft and child.rgt < parent.rgt
            
        data = []
        stack = []
        
        # Filter accounts that have depth < L
        filtered_accounts = []
        for acc in accounts_data:
            acc.depth = get_depth(acc.account)
            if acc.depth < L:
                filtered_accounts.append(acc)
                
        for idx, acc in enumerate(filtered_accounts):
            # Close groups that this row does not belong to
            while stack and not is_descendant(acc, stack[-1]):
                closed = stack.pop()
                data.append({
                    "account_number": "",
                    "account": f"Total de {closed.account_number or ''} {closed.account_name}",
                    "init_balance": closed.init_balance,
                    "debit": closed.debit,
                    "credit": closed.credit,
                    "end_balance": closed.end_balance,
                    "is_total": 1,
                    "is_group_total": 1,
                    "indent": closed.depth,
                    "company_rif": company_rif
                })
                
            # If it's a group header (depth < L - 1 and is_group == 1)
            if acc.depth < L - 1 and acc.is_group == 1:
                data.append({
                    "account_number": acc.account_number or "",
                    "account": acc.account_name,
                    "init_balance": None,
                    "debit": None,
                    "credit": None,
                    "end_balance": None,
                    "is_group_header": 1,
                    "indent": acc.depth,
                    "company_rif": company_rif
                })
                stack.append(acc)
            else:
                # Leaf at this level
                data.append({
                    "account_number": acc.account_number or "",
                    "account": acc.account_name,
                    "init_balance": acc.init_balance,
                    "debit": acc.debit,
                    "credit": acc.credit,
                    "end_balance": acc.end_balance,
                    "is_leaf": 1,
                    "indent": acc.depth,
                    "company_rif": company_rif
                })
                
        # Close any remaining groups on stack
        while stack:
            closed = stack.pop()
            data.append({
                "account_number": "",
                "account": f"Total de {closed.account_number or ''} {closed.account_name}",
                "init_balance": closed.init_balance,
                "debit": closed.debit,
                "credit": closed.credit,
                "end_balance": closed.end_balance,
                "is_total": 1,
                "is_group_total": 1,
                "indent": closed.depth,
                "company_rif": company_rif
            })
            
        # Add grand total row
        grand_init = sum(acc.init_balance for acc in accounts_data if get_depth(acc.account) == 0)
        grand_debit = sum(acc.debit for acc in accounts_data if get_depth(acc.account) == 0)
        grand_credit = sum(acc.credit for acc in accounts_data if get_depth(acc.account) == 0)
        grand_end = sum(acc.end_balance for acc in accounts_data if get_depth(acc.account) == 0)
        
        data.append({"account_number": "", "account": "", "init_balance": 0.0, "debit": 0.0, "credit": 0.0, "end_balance": 0.0, "company_rif": company_rif}) # Spacer
        data.append({
            "account_number": "",
            "account": _("Total Libro Mayor"),
            "init_balance": grand_init,
            "debit": grand_debit,
            "credit": grand_credit,
            "end_balance": grand_end,
            "is_total": 1,
            "is_grand_total": 1,
            "company_rif": company_rif
        })
        
        for r in data:
            r["company_address"] = company_address
            r["company_logo"] = company_logo

        return columns, data, None, None, None
        
    else:
        # DETAILED/TRANSACTIONAL presentation
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
            SELECT 
                gle.posting_date, 
                gle.voucher_no, 
                gle.account, 
                gle.remarks, 
                gle.debit, 
                gle.credit,
                COALESCE(
                    CASE 
                        WHEN gle.voucher_type = 'Sales Invoice' THEN NULLIF(si.bill_no, '')
                        WHEN gle.voucher_type = 'Purchase Invoice' THEN NULLIF(pi.bill_no, '')
                        WHEN gle.voucher_type = 'Payment Entry' THEN NULLIF(pe.reference_no, '')
                        WHEN gle.voucher_type = 'Journal Entry' THEN NULLIF(je.cheque_no, '')
                        WHEN gle.voucher_type = 'VE Sales Debit Note' THEN NULLIF(vsdn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Sales Credit Note' THEN NULLIF(vscn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Purchase Debit Note' THEN NULLIF(vpdn.bill_no, '')
                        WHEN gle.voucher_type = 'VE Purchase Credit Note' THEN NULLIF(vpcn.bill_no, '')
                        ELSE NULL
                    END,
                    gle.voucher_no
                ) as display_ref
            FROM `tabGL Entry` gle
            LEFT JOIN `tabSales Invoice` si ON gle.voucher_no = si.name AND gle.voucher_type = 'Sales Invoice'
            LEFT JOIN `tabPurchase Invoice` pi ON gle.voucher_no = pi.name AND gle.voucher_type = 'Purchase Invoice'
            LEFT JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name AND gle.voucher_type = 'Payment Entry'
            LEFT JOIN `tabJournal Entry` je ON gle.voucher_no = je.name AND gle.voucher_type = 'Journal Entry'
            LEFT JOIN `tabVE Sales Debit Note` vsdn ON gle.voucher_no = vsdn.name AND gle.voucher_type = 'VE Sales Debit Note'
            LEFT JOIN `tabVE Sales Credit Note` vscn ON gle.voucher_no = vscn.name AND gle.voucher_type = 'VE Sales Credit Note'
            LEFT JOIN `tabVE Purchase Debit Note` vpdn ON gle.voucher_no = vpdn.name AND gle.voucher_type = 'VE Purchase Debit Note'
            LEFT JOIN `tabVE Purchase Credit Note` vpcn ON gle.voucher_no = vpcn.name AND gle.voucher_type = 'VE Purchase Credit Note'
            WHERE gle.company = %s AND gle.docstatus = 1 AND gle.posting_date >= %s AND gle.posting_date <= %s {cc_cond}
            ORDER BY gle.account, gle.posting_date, gle.creation
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
                "is_header": 1,
                "company_rif": company_rif
            })
            
            # Opening balance row
            data.append({
                "posting_date": from_date,
                "reference": _("SALDO INICIAL"),
                "remarks": "",
                "debit": 0.0,
                "credit": 0.0,
                "balance": opening_bal,
                "is_opening": 1,
                "company_rif": company_rif
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
                    "reference": entry.display_ref,
                    "remarks": entry.remarks,
                    "debit": deb,
                    "credit": cred,
                    "balance": running_balance,
                    "company_rif": company_rif
                })
                
            # Total row for the account
            data.append({
                "posting_date": "",
                "reference": _("  Total Cuenta"),
                "remarks": "",
                "debit": total_debit,
                "credit": total_credit,
                "balance": running_balance,
                "is_total": 1,
                "company_rif": company_rif
            })
            
            # Spacer row
            data.append({
                "posting_date": "",
                "reference": "",
                "remarks": "",
                "debit": 0,
                "credit": 0,
                "balance": 0,
                "company_rif": company_rif
            })
            
        for r in data:
            r["company_address"] = company_address
            r["company_logo"] = company_logo

        return columns, data, None, None, None

