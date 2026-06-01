# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt, get_first_day, get_last_day, nowdate
from urllib.parse import urlparse

class DashboardGerencial(Document):
    pass


def _get_cached_rate(date_str, cache):
    """Helper to cache exchange rates to prevent N+1 query loops."""
    if date_str not in cache:
        from l10n_ve.utils.utils import get_exchange_rate
        cache[date_str] = flt(get_exchange_rate(date_str, "USD")) or 1.0
    return cache[date_str]


@frappe.whitelist()
def get_dashboard_data(company, from_date, to_date, branch=None, cost_center=None):
    """Calculates all metrics and table rows for the Dashboard Gerencial."""
    if not company or not from_date or not to_date:
        frappe.throw("Los campos Empresa, Fecha Inicio y Fecha Fin son obligatorios.")

    from_date = str(from_date)
    to_date = str(to_date)
    rates_cache = {}

    # ═════════════════════════════════════════════════════════════════════════
    # 1. METRICS: CARDS
    # ═════════════════════════════════════════════════════════════════════════

    # --- Sales count ---
    si_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [from_date, to_date]]
    }
    if branch:
        si_filters["branch"] = branch
    if cost_center:
        si_filters["name"] = ["in", frappe.get_all("Sales Invoice Item", filters={"cost_center": cost_center}, pluck="parent")]

    sales_count = frappe.db.count("Sales Invoice", si_filters)

    # --- Collected amount (VEF) ---
    pe_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [from_date, to_date]]
    }
    if branch:
        pe_filters["branch"] = branch
    if cost_center:
        pe_filters["name"] = ["in", frappe.get_all("GL Entry", filters={"voucher_type": "Payment Entry", "cost_center": cost_center}, pluck="voucher_no")]

    collected_raw = frappe.get_all("Payment Entry", filters=pe_filters, fields=["SUM(base_received_amount) as total"])
    collected_amount = flt(collected_raw[0].total) if collected_raw and collected_raw[0].total else 0.0

    # --- Total Billed USD & Billed BS ---
    invoices = frappe.get_all("Sales Invoice", filters=si_filters, fields=["grand_total", "base_grand_total", "currency", "posting_date", "total_taxes_and_charges"])
    
    total_billed_usd = 0.0
    total_billed_bs = 0.0
    taxes_usd = 0.0

    for inv in invoices:
        total_billed_bs += flt(inv.base_grand_total)
        
        # Converted or native USD billed
        if inv.currency == "USD":
            total_billed_usd += flt(inv.grand_total)
            if inv.total_taxes_and_charges:
                taxes_usd += flt(inv.total_taxes_and_charges)
        else:
            date_str = str(inv.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            total_billed_usd += flt(inv.grand_total) / rate
            if inv.total_taxes_and_charges:
                taxes_usd += flt(inv.total_taxes_and_charges) / rate

    # --- USD Sales Invoices Count ---
    usd_si_filters = si_filters.copy()
    usd_si_filters["currency"] = "USD"
    usd_sales_invoices_count = frappe.db.count("Sales Invoice", usd_si_filters)

    # --- Pending to Collect USD (Accounts Receivable) ---
    accounts_rec = frappe.get_all("Account", filters={"company": company, "account_type": "Receivable", "is_group": 0}, pluck="name")
    pending_to_collect_usd = 0.0
    if accounts_rec:
        gle_filters = {
            "account": ["in", accounts_rec],
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]]
        }
        if cost_center:
            gle_filters["cost_center"] = cost_center
        if branch:
            invoices_b = frappe.get_all("Sales Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
            gle_filters["voucher_no"] = ["in", invoices_b] if invoices_b else ["in", [""]]
        
        gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
        for entry in gl_entries:
            amount = flt(entry.debit) - flt(entry.credit)
            if entry.account_currency == "USD":
                amount_usd = flt(entry.debit_in_account_currency) - flt(entry.credit_in_account_currency)
            else:
                date_str = str(entry.posting_date)
                rate = _get_cached_rate(date_str, rates_cache)
                amount_usd = amount / rate
            pending_to_collect_usd += amount_usd

    # --- Client VAT Withholding USD ---
    accounts_iva = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%iva%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    client_vat_withholding_usd = 0.0
    if accounts_iva:
        gle_filters = {
            "account": ["in", accounts_iva],
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]]
        }
        if cost_center:
            gle_filters["cost_center"] = cost_center
        if branch:
            invoices_b = frappe.get_all("Sales Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
            payments_b = frappe.get_all("Payment Entry", filters={"branch": branch, "docstatus": 1}, pluck="name")
            gle_filters["voucher_no"] = ["in", invoices_b + payments_b] if (invoices_b or payments_b) else ["in", [""]]

        gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
        for entry in gl_entries:
            amount = flt(entry.debit) - flt(entry.credit)
            if entry.account_currency == "USD":
                amount_usd = flt(entry.debit_in_account_currency) - flt(entry.credit_in_account_currency)
            else:
                date_str = str(entry.posting_date)
                rate = _get_cached_rate(date_str, rates_cache)
                amount_usd = amount / rate
            client_vat_withholding_usd += amount_usd

    # --- Client ISLR Withholding USD ---
    accounts_islr = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%islr%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    client_islr_withholding_usd = 0.0
    if accounts_islr:
        gle_filters = {
            "account": ["in", accounts_islr],
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]]
        }
        if cost_center:
            gle_filters["cost_center"] = cost_center
        if branch:
            invoices_b = frappe.get_all("Sales Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
            payments_b = frappe.get_all("Payment Entry", filters={"branch": branch, "docstatus": 1}, pluck="name")
            gle_filters["voucher_no"] = ["in", invoices_b + payments_b] if (invoices_b or payments_b) else ["in", [""]]

        gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
        for entry in gl_entries:
            amount = flt(entry.debit) - flt(entry.credit)
            if entry.account_currency == "USD":
                amount_usd = flt(entry.debit_in_account_currency) - flt(entry.credit_in_account_currency)
            else:
                date_str = str(entry.posting_date)
                rate = _get_cached_rate(date_str, rates_cache)
                amount_usd = amount / rate
            client_islr_withholding_usd += amount_usd

    # --- IGTF Payable USD ---
    accounts_igtf = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%igtf%"],
        "root_type": "Liability",
        "is_group": 0
    }, pluck="name")
    igtf_payable_usd = 0.0
    if accounts_igtf:
        gle_filters = {
            "account": ["in", accounts_igtf],
            "docstatus": 1,
            "posting_date": ["between", [from_date, to_date]]
        }
        if cost_center:
            gle_filters["cost_center"] = cost_center
        if branch:
            invoices_b = frappe.get_all("Sales Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
            payments_b = frappe.get_all("Payment Entry", filters={"branch": branch, "docstatus": 1}, pluck="name")
            gle_filters["voucher_no"] = ["in", invoices_b + payments_b] if (invoices_b or payments_b) else ["in", [""]]

        gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
        for entry in gl_entries:
            amount = flt(entry.credit) - flt(entry.debit)
            if entry.account_currency == "USD":
                amount_usd = flt(entry.credit_in_account_currency) - flt(entry.debit_in_account_currency)
            else:
                date_str = str(entry.posting_date)
                rate = _get_cached_rate(date_str, rates_cache)
                amount_usd = amount / rate
            igtf_payable_usd += amount_usd

    # --- Expenses USD (Month) ---
    expenses_usd_month = 0.0
    if frappe.db.exists("DocType", "Expense"):
        exp_filters = {
            "docstatus": 1,
            "company": company,
            "expense_date": ["between", [from_date, to_date]]
        }
        if branch:
            exp_filters["branch"] = branch
        
        expenses_raw = frappe.db.sql("""
            SELECT SUM(
                CASE WHEN spending_currency = 'USD' THEN total_exchange
                WHEN usd_reference_rate > 0 THEN total / usd_reference_rate
                ELSE total
                END
            ) as total_spent
            FROM `tabExpense`
            WHERE docstatus = 1 AND company = %s AND expense_date BETWEEN %s AND %s
            """ + (" AND branch = %s" if branch else ""), 
            (company, from_date, to_date, branch) if branch else (company, from_date, to_date), as_dict=True)
        
        expenses_usd_month = flt(expenses_raw[0].total_spent) if expenses_raw and expenses_raw[0].total_spent is not None else 0.0
    else:
        accounts_exp = frappe.get_all("Account", filters={"company": company, "root_type": "Expense", "is_group": 0}, pluck="name")
        if accounts_exp:
            gle_filters = {
                "account": ["in", accounts_exp],
                "docstatus": 1,
                "posting_date": ["between", [from_date, to_date]]
            }
            if cost_center:
                gle_filters["cost_center"] = cost_center
            if branch:
                purchases_b = frappe.get_all("Purchase Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
                gle_filters["voucher_no"] = ["in", purchases_b] if purchases_b else ["in", [""]]

            gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
            for entry in gl_entries:
                amount = flt(entry.debit) - flt(entry.credit)
                if entry.account_currency == "USD":
                    amount_usd = flt(entry.debit_in_account_currency) - flt(entry.credit_in_account_currency)
                else:
                    date_str = str(entry.posting_date)
                    rate = _get_cached_rate(date_str, rates_cache)
                    amount_usd = amount / rate
                expenses_usd_month += amount_usd

    # --- Expenses USD (Year) ---
    year_start = f"{from_date[:4]}-01-01"
    year_end = f"{to_date[:4]}-12-31"
    expenses_usd_year = 0.0
    if frappe.db.exists("DocType", "Expense"):
        expenses_raw = frappe.db.sql("""
            SELECT SUM(
                CASE WHEN spending_currency = 'USD' THEN total_exchange
                WHEN usd_reference_rate > 0 THEN total / usd_reference_rate
                ELSE total
                END
            ) as total_spent
            FROM `tabExpense`
            WHERE docstatus = 1 AND company = %s AND expense_date BETWEEN %s AND %s
            """ + (" AND branch = %s" if branch else ""), 
            (company, year_start, year_end, branch) if branch else (company, year_start, year_end), as_dict=True)
        
        expenses_usd_year = flt(expenses_raw[0].total_spent) if expenses_raw and expenses_raw[0].total_spent is not None else 0.0
    else:
        accounts_exp = frappe.get_all("Account", filters={"company": company, "root_type": "Expense", "is_group": 0}, pluck="name")
        if accounts_exp:
            gle_filters = {
                "account": ["in", accounts_exp],
                "docstatus": 1,
                "posting_date": ["between", [year_start, year_end]]
            }
            if cost_center:
                gle_filters["cost_center"] = cost_center
            if branch:
                purchases_b = frappe.get_all("Purchase Invoice", filters={"branch": branch, "docstatus": 1}, pluck="name")
                gle_filters["voucher_no"] = ["in", purchases_b] if purchases_b else ["in", [""]]

            gl_entries = frappe.get_all("GL Entry", filters=gle_filters, fields=["debit", "credit", "account_currency", "debit_in_account_currency", "credit_in_account_currency", "posting_date"])
            for entry in gl_entries:
                amount = flt(entry.debit) - flt(entry.credit)
                if entry.account_currency == "USD":
                    amount_usd = flt(entry.debit_in_account_currency) - flt(entry.credit_in_account_currency)
                else:
                    date_str = str(entry.posting_date)
                    rate = _get_cached_rate(date_str, rates_cache)
                    amount_usd = amount / rate
                expenses_usd_year += amount_usd

    # --- Available USD (Cash & Bank) ---
    accounts_disp = frappe.get_all("Account", filters={
        "company": company,
        "account_type": ["in", ["Bank", "Cash"]],
        "is_group": 0
    }, fields=["name", "account_currency", "account_name"])
    
    available_usd = 0.0
    if accounts_disp:
        from l10n_ve.utils.utils import get_exchange_rate
        rate_today = flt(get_exchange_rate(to_date, "USD")) or 1.0
        
        for acc in accounts_disp:
            result = frappe.db.sql("""
                SELECT 
                    SUM(debit - credit) as balance_vef,
                    SUM(debit_in_account_currency - credit_in_account_currency) as balance_foreign
                FROM `tabGL Entry`
                WHERE account = %s AND docstatus = 1 AND posting_date <= %s
            """, (acc.name, to_date), as_dict=True)
            
            if result and result[0]:
                b_vef = flt(result[0].balance_vef)
                b_foreign = flt(result[0].balance_foreign)
                
                if acc.account_currency == "USD" or "usd" in str(acc.account_name).lower():
                    available_usd += b_foreign if b_foreign != 0 else (b_vef / rate_today)
                else:
                    available_usd += b_vef / rate_today

    # ═════════════════════════════════════════════════════════════════════════
    # 2. TABLE: FINANCIAL SUMMARY BY BRANCH
    # ═════════════════════════════════════════════════════════════════════════
    branch_rows = []
    
    # Get all branches
    branches = frappe.get_all("VE Branch", filters={"company": company} if frappe.get_meta("VE Branch").has_field("company") else {}, fields=["name"])
    if branch:
        branches = [{"name": branch}]

    # Retrieve expenses via tabExpense
    expenses_by_branch = {}
    if frappe.db.exists("DocType", "Expense"):
        expenses_raw = frappe.db.sql("""
            SELECT branch, SUM(
                CASE WHEN spending_currency = 'USD' THEN total_exchange
                WHEN usd_reference_rate > 0 THEN total / usd_reference_rate
                ELSE total
                END
            ) as total_spent
            FROM `tabExpense`
            WHERE docstatus = 1 AND company = %s AND expense_date BETWEEN %s AND %s
            GROUP BY branch
        """, (company, from_date, to_date), as_dict=True)
        expenses_by_branch = {r.branch: flt(r.total_spent) for r in expenses_raw if r.branch}

    for b in branches:
        b_name = b["name"]
        b_si_filters = si_filters.copy()
        b_si_filters["branch"] = b_name

        b_invoices = frappe.get_all("Sales Invoice", filters=b_si_filters, fields=["name", "grand_total", "total_taxes_and_charges", "bill_control", "currency", "posting_date"])
        
        invoice_names = [inv.name for inv in b_invoices]
        withholdings_by_invoice = {}
        if invoice_names:
            taxes_raw = frappe.db.get_all("Sales Taxes and Charges",
                filters={
                    "parent": ["in", invoice_names],
                    "is_tax_withholding_account": 1
                },
                fields=["parent", "account_head", "tax_amount"]
            )
            for t in taxes_raw:
                inv_name = t.parent
                if inv_name not in withholdings_by_invoice:
                    withholdings_by_invoice[inv_name] = {"vat": 0.0, "islr": 0.0}
                
                ac_lower = str(t.account_head).lower()
                if "iva" in ac_lower:
                    withholdings_by_invoice[inv_name]["vat"] += flt(t.tax_amount)
                elif "islr" in ac_lower:
                    withholdings_by_invoice[inv_name]["islr"] += flt(t.tax_amount)

        payment_order = 0.0
        payment_order_vat = 0.0
        billed = 0.0
        vat_billed = 0.0
        vat_withholding = 0.0
        islr_withholding = 0.0
        pending_to_collect = 0.0

        for inv in b_invoices:
            is_usd = (inv.currency == "USD")
            rate = 1.0 if is_usd else _get_cached_rate(str(inv.posting_date), rates_cache)

            inv_withholdings = withholdings_by_invoice.get(inv.name, {"vat": 0.0, "islr": 0.0})
            raw_vat_withholding = inv_withholdings["vat"]
            raw_islr_withholding = inv_withholdings["islr"]

            g_total_usd = flt(inv.grand_total) if is_usd else flt(inv.grand_total) / rate
            tax_usd = flt(inv.total_taxes_and_charges) if is_usd else flt(inv.total_taxes_and_charges) / rate
            ret_iva_usd = flt(raw_vat_withholding) if is_usd else flt(raw_vat_withholding) / rate
            ret_islr_usd = flt(raw_islr_withholding) if is_usd else flt(raw_islr_withholding) / rate

            payment_order += g_total_usd
            payment_order_vat += tax_usd

            has_control = (inv.bill_control is not None and str(inv.bill_control).strip() != "")
            if has_control:
                billed += g_total_usd
                vat_billed += tax_usd
                vat_withholding += ret_iva_usd
                islr_withholding += ret_islr_usd
            else:
                pending_to_collect += g_total_usd

        vat_after_withholding = vat_billed - vat_withholding
        availability = (billed - vat_billed) - islr_withholding
        spent = flt(expenses_by_branch.get(b_name, 0.0))
        profit = availability - spent

        branch_rows.append({
            "branch": b_name,
            "pending_to_collect": pending_to_collect,
            "payment_order": payment_order,
            "payment_order_vat": payment_order_vat,
            "billed": billed,
            "vat": vat_billed,
            "vat_after_withholding": vat_after_withholding,
            "vat_withholding": vat_withholding,
            "islr_withholding": islr_withholding,
            "availability": availability,
            "spent": spent,
            "profit": profit
        })

    return {
        "sales_count": sales_count,
        "collected_amount": collected_amount,
        "total_billed_usd": total_billed_usd,
        "usd_sales_invoices_count": usd_sales_invoices_count,
        "taxes_usd": taxes_usd,
        "total_billed_bs": total_billed_bs,
        "pending_to_collect_usd": pending_to_collect_usd,
        "client_vat_withholding_usd": client_vat_withholding_usd,
        "client_islr_withholding_usd": client_islr_withholding_usd,
        "igtf_payable_usd": igtf_payable_usd,
        "expenses_usd_month": expenses_usd_month,
        "expenses_usd_year": expenses_usd_year,
        "available_usd": available_usd,
        "branch_financial_summary": branch_rows
    }
