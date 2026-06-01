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
    # 1. METRICAS: CARDS
    # ═════════════════════════════════════════════════════════════════════════

    # --- Cantidad de ventas ---
    si_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [from_date, to_date]]
    }
    if branch:
        si_filters["branch"] = branch
    if cost_center:
        si_filters["name"] = ["in", frappe.get_all("Sales Invoice Item", filters={"cost_center": cost_center}, pluck="parent")]

    cantidad_de_ventas = frappe.db.count("Sales Invoice", si_filters)

    # --- Cobrado VEF ---
    pe_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [from_date, to_date]]
    }
    if branch:
        pe_filters["branch"] = branch
    if cost_center:
        pe_filters["name"] = ["in", frappe.get_all("GL Entry", filters={"voucher_type": "Payment Entry", "cost_center": cost_center}, pluck="voucher_no")]

    cobrado_raw = frappe.get_all("Payment Entry", filters=pe_filters, fields=["SUM(base_received_amount) as total"])
    cobrado = flt(cobrado_raw[0].total) if cobrado_raw and cobrado_raw[0].total else 0.0

    # --- Total Facturado USD & VEF/BS ---
    invoices = frappe.get_all("Sales Invoice", filters=si_filters, fields=["grand_total", "base_grand_total", "currency", "posting_date", "total_taxes_and_charges"])
    
    total_facturado_usd = 0.0
    total_facturado_bs = 0.0
    impuestos_usd = 0.0

    for inv in invoices:
        total_facturado_bs += flt(inv.base_grand_total)
        
        # Facturado USD conversion
        if inv.currency == "USD":
            total_facturado_usd += flt(inv.grand_total)
            if inv.total_taxes_and_charges:
                impuestos_usd += flt(inv.total_taxes_and_charges)
        else:
            date_str = str(inv.posting_date)
            rate = _get_cached_rate(date_str, rates_cache)
            total_facturado_usd += flt(inv.grand_total) / rate
            if inv.total_taxes_and_charges:
                impuestos_usd += flt(inv.total_taxes_and_charges) / rate

    # --- USD Factura de venta (Count) ---
    usd_si_filters = si_filters.copy()
    usd_si_filters["currency"] = "USD"
    usd_factura_de_venta = frappe.db.count("Sales Invoice", usd_si_filters)

    # --- Pendiente por Cobrar USD ---
    accounts_rec = frappe.get_all("Account", filters={"company": company, "account_type": "Receivable", "is_group": 0}, pluck="name")
    pendiente_por_cobrar_usd = 0.0
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
            pendiente_por_cobrar_usd += amount_usd

    # --- Retenciones IVA Clientes USD ---
    accounts_iva = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%iva%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    retencion_iva_clientes_usd = 0.0
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
            retencion_iva_clientes_usd += amount_usd

    # --- Retenciones ISLR Clientes USD ---
    accounts_islr = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%islr%"],
        "root_type": "Asset",
        "is_group": 0
    }, pluck="name")
    retencion_islr_clientes_usd = 0.0
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
            retencion_islr_clientes_usd += amount_usd

    # --- IGTF por Pagar USD ---
    accounts_igtf = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%igtf%"],
        "root_type": "Liability",
        "is_group": 0
    }, pluck="name")
    igtf_por_pagar_usd = 0.0
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
            igtf_por_pagar_usd += amount_usd

    # --- Gastos USD (Mes) ---
    gastos_usd_mes = 0.0
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
            (company, from_date, to_date, branch) if branch else (company, from_date, to_date))
        
        gastos_usd_mes = flt(expenses_raw[0][0]) if expenses_raw and expenses_raw[0][0] is not None else 0.0
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
                gastos_usd_mes += amount_usd

    # --- Gastos USD (Año) ---
    year_start = f"{from_date[:4]}-01-01"
    year_end = f"{to_date[:4]}-12-31"
    gastos_usd_ano = 0.0
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
            (company, year_start, year_end, branch) if branch else (company, year_start, year_end))
        
        gastos_usd_ano = flt(expenses_raw[0][0]) if expenses_raw and expenses_raw[0][0] is not None else 0.0
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
                gastos_usd_ano += amount_usd

    # --- Disponible USD ---
    # Retrieve all Bank/Cash accounts for the company
    accounts_disp = frappe.get_all("Account", filters={
        "company": company,
        "account_type": ["in", ["Bank", "Cash"]],
        "is_group": 0
    }, fields=["name", "account_currency", "account_name"])
    
    disponible_usd = 0.0
    if accounts_disp:
        from l10n_ve.utils.utils import get_exchange_rate
        rate_today = flt(get_exchange_rate(to_date, "USD")) or 1.0
        
        for acc in accounts_disp:
            # Query GL balance in VEF and in account currency
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
                    # Direct USD balance
                    disponible_usd += b_foreign if b_foreign != 0 else (b_vef / rate_today)
                else:
                    # Convert VEF balance to USD equivalent using the date's rate
                    disponible_usd += b_vef / rate_today

    # ═════════════════════════════════════════════════════════════════════════
    # 2. TABLA: RESUMEN FINANCIERO POR SUCURSAL
    # ═════════════════════════════════════════════════════════════════════════
    branch_rows = []
    
    # Obtener todas las sucursales (VE Branch)
    branches = frappe.get_all("VE Branch", filters={"company": company} if frappe.get_meta("VE Branch").has_field("company") else {}, fields=["name"])
    
    # Si se filtró por una sucursal, solo mostramos esa
    if branch:
        branches = [{"name": branch}]

    # Si hay un DocType Expense, obtenemos sus gastos por sucursal
    expenses_by_branch = {}
    if frappe.db.exists("DocType", "Expense"):
        exp_filters = {
            "docstatus": 1,
            "company": company,
            "expense_date": ["between", [from_date, to_date]]
        }
        if branch:
            exp_filters["branch"] = branch
        
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
        
        # Filtros de facturas para la sucursal
        b_si_filters = si_filters.copy()
        b_si_filters["branch"] = b_name

        b_invoices = frappe.get_all("Sales Invoice", filters=b_si_filters, fields=["name", "grand_total", "total_taxes_and_charges", "bill_control", "currency", "posting_date"])
        
        # Pre-fetch withholdings for all invoices of this branch to optimize DB queries
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

        orden_de_pago = 0.0
        iva_orden = 0.0
        facturado = 0.0
        iva_facturado = 0.0
        ret_iva = 0.0
        ret_islr = 0.0
        por_cobrar = 0.0

        for inv in b_invoices:
            # Conversion a USD o usar nativo
            is_usd = (inv.currency == "USD")
            rate = 1.0 if is_usd else _get_cached_rate(str(inv.posting_date), rates_cache)

            # Get pre-fetched withholdings for this invoice
            inv_withholdings = withholdings_by_invoice.get(inv.name, {"vat": 0.0, "islr": 0.0})
            raw_vat_withholding = inv_withholdings["vat"]
            raw_islr_withholding = inv_withholdings["islr"]

            g_total_usd = flt(inv.grand_total) if is_usd else flt(inv.grand_total) / rate
            tax_usd = flt(inv.total_taxes_and_charges) if is_usd else flt(inv.total_taxes_and_charges) / rate
            ret_iva_usd = flt(raw_vat_withholding) if is_usd else flt(raw_vat_withholding) / rate
            ret_islr_usd = flt(raw_islr_withholding) if is_usd else flt(raw_islr_withholding) / rate

            # OP total
            orden_de_pago += g_total_usd
            iva_orden += tax_usd

            has_control = (inv.bill_control is not None and str(inv.bill_control).strip() != "")
            
            if has_control:
                facturado += g_total_usd
                iva_facturado += tax_usd
                ret_iva += ret_iva_usd
                ret_islr += ret_islr_usd
            else:
                por_cobrar += g_total_usd

        iva_desp_reten = iva_facturado - ret_iva
        disponibilidad = (facturado - iva_facturado) - ret_islr
        spent = flt(expenses_by_branch.get(b_name, 0.0))
        utilidad = disponibilidad - spent

        branch_rows.append({
            "branch": b_name,
            "por_cobrar": por_cobrar,
            "orden_de_pago": orden_de_pago,
            "iva_orden": iva_orden,
            "facturado": facturado,
            "iva": iva_facturado,
            "iva_desp_retencion": iva_desp_reten,
            "ret_iva": ret_iva,
            "ret_islr": ret_islr,
            "disponibilidad": disponibilidad,
            "spent": spent,
            "utilidad": utilidad
        })

    # Ordenar y retornar
    return {
        "cantidad_de_ventas": cantidad_de_ventas,
        "cobrado": cobrado,
        "total_facturado_usd": total_facturado_usd,
        "usd_factura_de_venta": usd_factura_de_venta,
        "impuestos_usd": impuestos_usd,
        "total_facturado_bs": total_facturado_bs,
        "pendiente_por_cobrar_usd": pendiente_por_cobrar_usd,
        "retencion_iva_clientes_usd": retencion_iva_clientes_usd,
        "retencion_islr_clientes_usd": retencion_islr_clientes_usd,
        "igtf_por_pagar_usd": igtf_por_pagar_usd,
        "gastos_usd_mes": gastos_usd_mes,
        "gastos_usd_ano": gastos_usd_ano,
        "disponible_usd": disponible_usd,
        "branch_financial_summary": branch_rows
    }
