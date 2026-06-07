# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt

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
    
    if getdate(from_date) > getdate(to_date):
        frappe.throw("La Fecha de Inicio no puede ser posterior a la Fecha Fin.")
    rates_cache = {}
    from l10n_ve.utils.utils import get_exchange_rate
    rate_today = flt(get_exchange_rate(to_date, "USD")) or 1.0

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

    # --- Cuentas IGTF (usadas por igtf_by_branch en la tabla) ---
    accounts_igtf = frappe.get_all("Account", filters={
        "company": company,
        "account_name": ["like", "%igtf%"],
        "root_type": "Liability",
        "is_group": 0
    }, pluck="name")
    # =========================================================================
    # 2. TABLA: RESUMEN FINANCIERO POR SUCURSAL
    # =========================================================================
    branch_rows = []

    branches = frappe.get_all("VE Branch", filters={"company": company} if frappe.get_meta("VE Branch").has_field("company") else {}, fields=["name"])
    branch_names = {b["name"] for b in branches}
    if branch:
        branch_names = {branch}

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

    # Retrieve IGTF per branch
    igtf_by_branch = {}
    if accounts_igtf:
        # Group by branch for Sales Invoice IGTF
        si_igtf = frappe.db.sql("""
            SELECT si.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabSales Invoice` si ON gle.voucher_no = si.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s
        """, (tuple(accounts_igtf), from_date, to_date), as_dict=True)
        
        # Group by branch for Payment Entry IGTF
        pe_igtf = frappe.db.sql("""
            SELECT pe.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s
        """, (tuple(accounts_igtf), from_date, to_date), as_dict=True)

        for rows in (si_igtf, pe_igtf):
            for r in rows:
                b = r.branch or "Sin Sucursal"
                if b not in igtf_by_branch:
                    igtf_by_branch[b] = 0.0
                amount = flt(r.credit) - flt(r.debit)
                if r.account_currency == "USD":
                    amount_usd = amount
                else:
                    date_str = str(r.posting_date)
                    rate = _get_cached_rate(date_str, rates_cache)
                    amount_usd = amount / rate
                igtf_by_branch[b] += amount_usd

    # =========================================================================
    # DIFERENCIAL CAMBIARIO POR SUCURSAL (alineado con el panel ISP)
    # =========================================================================
    # Asientos "Exchange Gain Or Loss" del período, ligados a la factura. En la
    # línea por cobrar: débito => ganancia, crédito => pérdida. Dos rutas, igual
    # que el ISP:
    #   1) reference_name -> Sales Invoice (asientos de 2 patas).
    #   2) remark "(Factura: ACC-SINV-...)" para asientos manuales de sobrepago
    #      sin reference (disjunto de la ruta 1). Frágil: depende del texto.
    # Se convierte a USD dividiendo por rate_today para cuadrar con el ISP.
    ganancia_by_branch = {}
    perdida_by_branch = {}
    fx_cond = "AND si_fx.branch = %(branch)s" if branch else ""
    fx_params = {"company": company, "from_date": from_date, "to_date": to_date, "branch": branch}

    fx_ref = frappe.db.sql("""
        SELECT si_fx.branch AS branch,
            SUM(jea.debit_in_account_currency) AS ganancia,
            SUM(jea.credit_in_account_currency) AS perdida
        FROM `tabJournal Entry Account` jea
        JOIN `tabJournal Entry` je ON jea.parent = je.name
            AND je.voucher_type = 'Exchange Gain Or Loss'
            AND je.docstatus = 1 AND je.company = %(company)s
        JOIN `tabSales Invoice` si_fx ON jea.reference_name = si_fx.name
            AND si_fx.posting_date BETWEEN %(from_date)s AND %(to_date)s {cond}
        WHERE jea.reference_type = 'Sales Invoice'
        GROUP BY si_fx.branch
    """.format(cond=fx_cond), fx_params, as_dict=True)

    fx_remark = frappe.db.sql("""
        SELECT si_fx.branch AS branch,
            SUM(jea.debit_in_account_currency) AS ganancia,
            SUM(jea.credit_in_account_currency) AS perdida
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
            AND jea.account_type = 'Receivable'
        JOIN `tabSales Invoice` si_fx ON si_fx.name = SUBSTRING_INDEX(
                SUBSTRING_INDEX(je.remark, '(Factura: ', -1), ')', 1)
            AND si_fx.posting_date BETWEEN %(from_date)s AND %(to_date)s {cond}
        WHERE je.voucher_type = 'Exchange Gain Or Loss'
            AND je.docstatus = 1 AND je.company = %(company)s
            AND LOCATE('(Factura: ', je.remark) > 0
            AND NOT EXISTS (
                SELECT 1 FROM `tabJournal Entry Account` jx
                WHERE jx.parent = je.name AND jx.reference_type = 'Sales Invoice'
                    AND jx.reference_name IS NOT NULL AND jx.reference_name <> '')
        GROUP BY si_fx.branch
    """.format(cond=fx_cond), fx_params, as_dict=True)

    for fx in (fx_ref + fx_remark):
        b = fx.branch if (fx.branch and fx.branch in branch_names) else "Sin Sucursal"
        ganancia_by_branch[b] = ganancia_by_branch.get(b, 0.0) + flt(fx.ganancia) / rate_today
        perdida_by_branch[b] = perdida_by_branch.get(b, 0.0) + flt(fx.perdida) / rate_today

    # 1. Single bulk query of all invoices of the company during the period
    # Incluir borradores (docstatus 0): las facturas de suscripción aún sin número
    # de control deben contar en "Por cobrar" (mismo criterio que el ISP).
    table_filters = dict(si_filters)
    table_filters["docstatus"] = ["!=", 2]
    all_invoices = frappe.get_all(
        "Sales Invoice",
        filters=table_filters,
        fields=["name", "net_total", "grand_total", "total_taxes_and_charges", "bill_control", "currency", "posting_date", "branch", "docstatus"]
    )

    # 2. Single bulk query of all withholdings for these invoices
    invoice_names = [inv.name for inv in all_invoices]
    withholdings_by_invoice = {}
    iva_by_invoice = {}
    if invoice_names:
        taxes_raw = frappe.db.get_all(
            "Sales Taxes and Charges",
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

        # IVA bruto (fila VAT, no retención) para calcular Facturado = base + IVA bruto
        iva_raw = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={
                "parent": ["in", invoice_names],
                "is_tax_withholding_account": 0,
                "charge_type": "VAT"
            },
            fields=["parent", "tax_amount"]
        )
        for t in iva_raw:
            iva_by_invoice[t.parent] = iva_by_invoice.get(t.parent, 0.0) + flt(t.tax_amount)

    # 3. Group invoices by branch in memory
    invoices_by_branch = {}
    for inv in all_invoices:
        b_name = inv.branch if (inv.branch and inv.branch in branch_names) else "Sin Sucursal"
        if b_name not in invoices_by_branch:
            invoices_by_branch[b_name] = []
        invoices_by_branch[b_name].append(inv)

    # Determine branches to display in the table
    all_table_branches = list(branch_names)
    if "Sin Sucursal" in invoices_by_branch or not branch:
        if "Sin Sucursal" not in all_table_branches:
            all_table_branches.append("Sin Sucursal")

    # 4. Process metrics in a unified way
    for b_name in all_table_branches:
        b_invoices = invoices_by_branch.get(b_name, [])

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
            raw_gross_iva = iva_by_invoice.get(inv.name, 0.0)

            # BRUTO (base + IVA), igual que el modelo del ISP/Excel. NO usar
            # grand_total (neto, ya descontadas las retenciones) ni
            # total_taxes_and_charges (IVA neto); usar net_total + IVA bruto.
            base_usd = flt(inv.net_total) if is_usd else flt(inv.net_total) / rate
            tax_usd = flt(raw_gross_iva) if is_usd else flt(raw_gross_iva) / rate
            g_total_usd = base_usd + tax_usd
            ret_iva_usd = flt(raw_vat_withholding) if is_usd else flt(raw_vat_withholding) / rate
            ret_islr_usd = flt(raw_islr_withholding) if is_usd else flt(raw_islr_withholding) / rate

            payment_order += g_total_usd
            payment_order_vat += tax_usd

            # Facturado = aprobada (docstatus 1) CON número de control.
            # Sin número de control (incl. borradores de suscripción) -> Por cobrar.
            has_control = (inv.docstatus == 1 and inv.bill_control is not None and str(inv.bill_control).strip() != "")
            no_control = (inv.bill_control is None or str(inv.bill_control).strip() == "")
            if has_control:
                billed += g_total_usd
                vat_billed += tax_usd
                vat_withholding += ret_iva_usd
                islr_withholding += ret_islr_usd
            elif no_control:
                pending_to_collect += g_total_usd

        vat_after_withholding = vat_billed - vat_withholding
        ganancia_val = flt(ganancia_by_branch.get(b_name, 0.0))
        perdida_val = flt(perdida_by_branch.get(b_name, 0.0))
        # Disponibilidad incluye el diferencial cambiario, igual que el ISP:
        # (Facturado - IVA) - Ret. ISLR - Pérdida + Ganancia.
        availability = (billed - vat_billed) - islr_withholding - perdida_val + ganancia_val
        igtf_val = flt(igtf_by_branch.get(b_name, 0.0))
        spent = flt(expenses_by_branch.get(b_name, 0.0)) if b_name != "Sin Sucursal" else 0.0
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
            "igtf": igtf_val,
            "ganancia": ganancia_val,
            "perdida": perdida_val,
            "availability": availability,
            "spent": spent,
            "profit": profit
        })

    return {
        "sales_count": sales_count,
        "exchange_rate": rate_today,
        "branch_financial_summary": branch_rows
    }
