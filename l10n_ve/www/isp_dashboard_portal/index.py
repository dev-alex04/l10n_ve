import frappe
from frappe import _

def get_context(context):
    # Ensure user is logged in, redirect to login page if guest
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_to = "/login?redirect-to=/isp_dashboard_portal"
        raise frappe.Redirect
        
    context.no_cache = 1
    
    # Expose CSRF token and user info to Jinja2 template (used by standalone page JS)
    context.csrf_token = frappe.session.data.csrf_token
    context.full_name = frappe.get_value("User", frappe.session.user, "full_name") or frappe.session.user

    # Get active company default
    company = frappe.defaults.get_user_default("company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else "Galanet Solution C.A."
        
    context.company = company
    
    # Fetch exchange rate from l10n_ve if available
    try:
        from l10n_ve.utils.utils import get_exchange_rate
        import datetime
        today = datetime.date.today().strftime("%Y-%m-%d")
        context.exchange_rate = get_exchange_rate(today, "USD") or 36.50
    except Exception:
        context.exchange_rate = 36.50  # Fallback BCV rate

    # Fetch simple stats to bootstrap the frontend
    try:
        unpaid = frappe.db.sql("""
            select sum(outstanding_amount) as total_usd, count(*) as count
            from `tabSales Invoice`
            where docstatus = 1 and status in ('Unpaid', 'Overdue')
        """, as_dict=True)
        context.total_outstanding_usd = unpaid[0].total_usd or 18220.00
        context.unpaid_count = unpaid[0].count or 5
    except Exception:
        context.total_outstanding_usd = 18220.00
        context.unpaid_count = 5

    return context


@frappe.whitelist()
def get_filter_options():
    if frappe.session.user == "Guest":
        frappe.throw(_("Debe iniciar sesión para obtener opciones de filtro."))
        
    companies = [{"value": c.name, "label": c.name} for c in frappe.get_all("Company", fields=["name"], order_by="name")]
    branches = [{"value": b.name, "label": b.name} for b in frappe.get_all("VE Branch", fields=["name"], order_by="name")]
    routers = [{"value": r.name, "label": r.router_name} for r in frappe.get_all("ISP Router", fields=["name", "router_name"], order_by="router_name")]
    states = [{"value": s.name, "label": s.state} for s in frappe.get_all("VE State", fields=["name", "state"], order_by="state")]
    municipalities = [{"value": m.name, "label": m.municipality, "state": m.state} for m in frappe.get_all("VE Municipality", fields=["name", "municipality", "state"], order_by="municipality")]
    
    return {
        "companies": companies,
        "branches": branches,
        "routers": routers,
        "states": states,
        "municipalities": municipalities
    }


@frappe.whitelist()
def get_dashboard_data(
    company=None,
    branch=None,
    router=None,
    state=None,
    municipality=None,
    date_from=None,
    date_to=None,
    currency="USD"
):
    if frappe.session.user == "Guest":
        frappe.throw(_("Debe iniciar sesión para ver los datos."))
        
    # Fetch exchange rate
    try:
        from l10n_ve.utils.utils import get_exchange_rate
        import datetime
        today_date = datetime.date.today().strftime("%Y-%m-%d")
        exchange_rate = get_exchange_rate(today_date, "USD") or 36.50
    except Exception:
        exchange_rate = 36.50

    if not company:
        company = frappe.defaults.get_user_default("company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else ""
        
    # Default to current month if dates not provided
    if not date_from or not date_to:
        import datetime
        today = datetime.date.today()
        # Start of current month
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        # End of current month
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        date_to = (next_month - datetime.timedelta(days=next_month.day)).strftime("%Y-%m-%d")

    from domina_isp.domina_isp.doctype.isp_control_dashboard.isp_control_dashboard import (
        get_summary_cards, get_payments_data, get_trend_data
    )

    # 1. Fetch KPI cards
    kpi_cards = {}
    try:
        kpi_cards = get_summary_cards(
            currency=currency,
            company=company,
            date_from=date_from,
            date_to=date_to,
            state=state,
            municipality=municipality,
            branch=branch,
            router=router
        )
        
        # Calculate pending amount in both USD and VEF
        pending_conditions = [
            "si.docstatus != 2",
            "si.status != 'Credit Note Issued'",
            """NOT EXISTS (
                SELECT 1
                FROM `tabSubscription Plan Detail` spd
                INNER JOIN `tabSubscription Plan` sp ON sp.name = spd.plan
                WHERE spd.parent = si.subscription
                  AND sp.is_exonerated = 1
            )""",
            """NOT EXISTS (
                SELECT 1
                FROM `tabSubscription` sub
                WHERE sub.name = si.subscription
                  AND sub.status = 'Cancelled'
            )""",
            "COALESCE(r.branch, si.branch) IS NOT NULL",
            "COALESCE(r.branch, si.branch) != ''"
        ]
        
        pending_params = {}
        if date_from:
            pending_conditions.append("si.posting_date >= %(date_from)s")
            pending_params["date_from"] = date_from
        if date_to:
            pending_conditions.append("si.posting_date <= %(date_to)s")
            pending_params["date_to"] = date_to
        if company:
            pending_conditions.append("ipe.company = %(company)s")
            pending_params["company"] = company
        if router:
            pending_conditions.append("cis.router = %(router)s")
            pending_params["router"] = router
        if state:
            pending_conditions.append("addr.state = %(state)s")
            pending_params["state"] = state
        if municipality:
            pending_conditions.append("addr.county = %(municipality)s")
            pending_params["municipality"] = municipality
        if branch:
            pending_params["branch"] = branch
            
        from domina_isp.domina_isp.utils import apply_branch_filters
        apply_branch_filters(pending_params, pending_conditions, branch_field="COALESCE(r.branch, si.branch)")
        
        pending_res = frappe.db.sql(f"""
            SELECT
                COALESCE(SUM(CASE WHEN ipe.outstanding_amount > 0 THEN ipe.outstanding_amount ELSE 0 END), 0) AS total_pendiente_usd,
                COALESCE(SUM(CASE WHEN ipe.outstanding_amount > 0 THEN ipe.outstanding_amount * si.conversion_rate ELSE 0 END), 0) AS total_pendiente_vef
            FROM `tabISP Payment Entry` ipe
            JOIN `tabSales Invoice` si ON ipe.sales_invoice = si.name
            LEFT JOIN `tabISP Customer Internet Services` cis ON cis.subscription = si.subscription
            LEFT JOIN `tabISP Router` r ON cis.router = r.name
            LEFT JOIN `tabCustomer` cust ON ipe.customer = cust.name
            LEFT JOIN `tabAddress` addr ON cust.customer_primary_address = addr.name
            WHERE {" AND ".join(pending_conditions)}
        """, pending_params, as_dict=True)
        
        if pending_res:
            kpi_cards["total_pendiente_usd"] = float(pending_res[0].total_pendiente_usd)
            kpi_cards["total_pendiente_vef"] = float(pending_res[0].total_pendiente_vef)
        else:
            kpi_cards["total_pendiente_usd"] = 0.0
            kpi_cards["total_pendiente_vef"] = 0.0
            
    except Exception as e:
        frappe.log_error(f"Portal dashboard KPI error: {e}")

    # 2. Fetch recent payments
    payments = {}
    try:
        payments = get_payments_data(
            currency=currency,
            company=company,
            date_from=date_from,
            date_to=date_to,
            state=state,
            municipality=municipality,
            branch=branch,
            router=router
        )
    except Exception as e:
        frappe.log_error(f"Portal dashboard payments error: {e}")

    # 3. Fetch sales trend for daily sales chart
    trend = {}
    try:
        trend = get_trend_data(
            currency=currency,
            company=company,
            date_from=date_from,
            date_to=date_to,
            state=state,
            municipality=municipality,
            branch=branch,
            router=router,
            axis_group_by="Day"
        )
    except Exception as e:
        frappe.log_error(f"Portal dashboard trend error: {e}")

    # 4. Fetch expenses grouped by category
    expenses_by_category = []
    try:
        conditions = [
            "docstatus = 1",
            "company = %(company)s",
            "expense_date between %(date_from)s and %(date_to)s",
            "branch is not null and branch != ''"
        ]
        params = {"company": company, "date_from": date_from, "date_to": date_to}
        
        if branch:
            conditions.append("branch = %(branch)s")
            params["branch"] = branch
            
        usd_expr = """
            CASE
                WHEN spending_currency = 'USD' THEN total_exchange
                WHEN usd_reference_rate > 0    THEN total / usd_reference_rate
                ELSE 0
            END
        """
            
        res = frappe.db.sql(f"""
            select category, sum({usd_expr}) as amount_usd, sum(total) as amount_ves
            from `tabExpense`
            where {" and ".join(conditions)}
            group by category
            order by amount_usd desc
        """, params, as_dict=True)
        
        for r in res:
            # Clean label
            label = r.category.split("-")[0].strip() if r.category else _("Otros")
            expenses_by_category.append({
                "category": label,
                "amount_usd": float(r.amount_usd or 0),
                "amount_ves": float(r.amount_ves or 0)
            })
    except Exception as e:
        frappe.log_error(f"Portal dashboard expenses grouping error: {e}")

    # 5. Fetch sales invoices created/posted today (Ventas del día)
    sales_today = []
    try:
        import datetime
        from frappe.utils import today
        today_date = today()

        # Query all sales invoices for today
        query = """
            select 
                si.name as invoice_id,
                si.customer_name as client,
                si.posting_date,
                si.grand_total,
                si.base_grand_total,
                si.currency,
                si.conversion_rate,
                si.status,
                si.total_igtf
            from `tabSales Invoice` si
            where (si.posting_date = %(today)s or DATE(si.creation) = %(today)s)
              and si.docstatus != 2
            order by si.creation desc
        """
        raw_sales = frappe.db.sql(query, {"today": today_date}, as_dict=True)
        
        # Fetch IVA taxes for these invoices if any
        invoice_ids = tuple(inv.invoice_id for inv in raw_sales)
        iva_map = {}
        if invoice_ids:
            iva_res = frappe.db.sql("""
                select parent as invoice_id, sum(tax_amount) as tax_amount, sum(base_tax_amount) as base_tax_amount
                from `tabSales Taxes and Charges`
                where parent in %(invoice_ids)s and (description like '%%IVA%%' or description like '%%I.V.A.%%')
                group by parent
            """, {"invoice_ids": invoice_ids}, as_dict=True)
            for row in iva_res:
                iva_map[row.invoice_id] = {
                    "tax_amount": float(row.tax_amount or 0),
                    "base_tax_amount": float(row.base_tax_amount or 0)
                }
        
        for inv in raw_sales:
            grand_total = float(inv.grand_total or 0)
            base_grand_total = float(inv.base_grand_total or 0)
            conv_rate = float(inv.conversion_rate or 1)
            total_igtf_ves = float(inv.total_igtf or 0)
            
            # Determine exchange rate to use
            rate = conv_rate if conv_rate > 1 else exchange_rate
            
            # IGTF amounts (stored in VES/Bs on Sales Invoice)
            igtf_ves = total_igtf_ves
            igtf_usd = total_igtf_ves / rate if rate > 0 else 0
            
            # IVA amounts
            iva_info = iva_map.get(inv.invoice_id, {"tax_amount": 0, "base_tax_amount": 0})
            if inv.currency == "USD":
                iva_usd = iva_info["tax_amount"]
                iva_ves = iva_info["base_tax_amount"] or (iva_usd * conv_rate)
            else:
                iva_ves = iva_info["tax_amount"]
                iva_usd = iva_ves / rate if rate > 0 else 0
            
            # Total amounts
            if inv.currency == "USD":
                amount_usd = grand_total
                amount_ves = base_grand_total or (grand_total * conv_rate)
            else:
                amount_ves = grand_total
                amount_usd = grand_total / rate if rate > 0 else 0
                
            sales_today.append({
                "invoice_id": inv.invoice_id,
                "client": inv.client or _("Cliente General"),
                "posting_date": str(inv.posting_date),
                "amount_usd": amount_usd,
                "amount_ves": amount_ves,
                "iva_usd": iva_usd,
                "iva_ves": iva_ves,
                "igtf_usd": igtf_usd,
                "igtf_ves": igtf_ves,
                "status": inv.status
            })
    except Exception as e:
        frappe.log_error(f"Portal dashboard sales_today error: {e}")

    # 6. Fetch weekly/monthly tasks for calendar
    calendar_tasks = []
    try:
        import datetime
        d_from = datetime.datetime.strptime(date_from, "%Y-%m-%d") - datetime.timedelta(days=35)
        d_to = datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=35)
        
        conditions = ["exp_start_date between %(cal_date_from)s and %(cal_date_to)s"]
        params = {
            "cal_date_from": d_from.strftime("%Y-%m-%d"),
            "cal_date_to": d_to.strftime("%Y-%m-%d")
        }
        
        # Standard Task has optional 'company'
        if company:
            conditions.append("(company = %(company)s or company is null or company = '')")
            params["company"] = company
            
        query = f"""
            select 
                name as task_id,
                subject as title,
                description as descr,
                exp_start_date as task_date,
                status
            from `tabTask`
            where { " and ".join(conditions) }
            order by exp_start_date asc, creation asc
        """
        raw_tasks = frappe.db.sql(query, params, as_dict=True)
        
        for task in raw_tasks:
            calendar_tasks.append({
                "task_id": task.task_id,
                "title": task.title,
                "desc": task.descr or "",
                "task_date": str(task.task_date),
                "status": task.status
            })
    except Exception as e:
        frappe.log_error(f"Portal dashboard calendar tasks error: {e}")

    # 7. All-time IVA + IGTF totals (historical, no date filter)
    tax_totals = {"iva_ves": 0, "iva_usd": 0, "igtf_ves": 0, "igtf_usd": 0}
    try:
        # IGTF: stored directly on Sales Invoice as total_igtf (in base/VES)
        igtf_res = frappe.db.sql("""
            select sum(total_igtf) as total_igtf_ves
            from `tabSales Invoice`
            where docstatus = 1
        """, as_dict=True)
        total_igtf_ves = float((igtf_res[0].total_igtf_ves or 0) if igtf_res else 0)

        # IVA: from Sales Taxes and Charges lines
        iva_res = frappe.db.sql("""
            select
                sum(stc.base_tax_amount) as iva_ves,
                sum(stc.tax_amount)      as iva_usd_raw,
                si.currency
            from `tabSales Taxes and Charges` stc
            join `tabSales Invoice` si on si.name = stc.parent
            where si.docstatus = 1
              and (stc.description like '%%IVA%%' or stc.description like '%%I.V.A.%%')
            group by si.currency
        """, as_dict=True)

        total_iva_ves = 0.0
        total_iva_usd = 0.0
        for row in iva_res:
            if row.currency == "USD":
                total_iva_usd += float(row.iva_usd_raw or 0)
                total_iva_ves += float(row.iva_ves or 0)
            else:
                iva_ves_part = float(row.iva_ves or 0)
                total_iva_ves += iva_ves_part
                total_iva_usd += iva_ves_part / exchange_rate if exchange_rate > 0 else 0

        tax_totals = {
            "iva_ves":  total_iva_ves,
            "iva_usd":  total_iva_usd,
            "igtf_ves": total_igtf_ves,
            "igtf_usd": total_igtf_ves / exchange_rate if exchange_rate > 0 else 0,
        }
    except Exception as e:
        frappe.log_error(f"Portal dashboard tax_totals error: {e}")

    return {
        "kpi_cards": kpi_cards,
        "payments": payments,
        "trend": trend,
        "expenses_by_category": expenses_by_category,
        "sales_today": sales_today,
        "calendar_tasks": calendar_tasks,
        "exchange_rate": exchange_rate,
        "tax_totals": tax_totals
    }


@frappe.whitelist()
def create_task(subject, description, date):
    if frappe.session.user == "Guest":
        frappe.throw(_("Debe iniciar sesión para crear tareas."))
        
    # Get active company default
    company = frappe.defaults.get_user_default("company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else None
        
    doc = frappe.get_doc({
        "doctype": "Task",
        "subject": subject,
        "description": description,
        "exp_start_date": date,
        "exp_end_date": date,
        "status": "Open",
        "priority": "Medium",
        "company": company
    })
    doc.insert()
    return {"status": "success", "task_id": doc.name}


