import frappe
from frappe import _
from frappe.utils import getdate, flt
import datetime

def get_context(context):
    # Ensure user is logged in, redirect to login page if guest
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_to = "/login?redirect-to=/isp_dashboard_portal"
        raise frappe.Redirect
        
    context.no_cache = 1
    
    # Expose CSRF token and user info to Jinja2 template (used by standalone page JS)
    context.csrf_token = getattr(frappe.session.data, "csrf_token", "")
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
        today = datetime.date.today().strftime("%Y-%m-%d")
        rate = get_exchange_rate(today, "USD")
        if not rate:
            frappe.throw(_("No se pudo obtener la tasa de cambio BCV para el día de hoy ({0})").format(today))
        context.exchange_rate = rate
    except Exception as e:
        if "No se pudo obtener" in str(e):
            raise e
        frappe.throw(_("Error al recuperar la tasa de cambio BCV para el día de hoy ({0}): {1}").format(today, e))

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
        
    frappe.get_doc("Dashboard Gerencial").check_permission("read")
        
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


def _get_kpi_cards(company, date_from, date_to, branch, exchange_rate):
    from l10n_ve.l10n_ve.doctype.dashboard_gerencial.dashboard_gerencial import get_dashboard_data as get_dg_data
    
    dg_res = get_dg_data(company, date_from, date_to, branch=branch)
    tree = dg_res.get("branch_financial_summary", [])
    
    total_pendiente_usd = 0.0
    total_pendiente_vef = 0.0
    
    billed_usd = 0.0
    billed_vef = 0.0
    vat_usd = 0.0
    vat_vef = 0.0
    igtf_usd = 0.0
    igtf_vef = 0.0
    
    availability_usd = 0.0
    availability_vef = 0.0
    
    spent_usd = 0.0
    spent_vef = 0.0
    
    for node in tree:
        if node.get("indent") == 0:
            total_pendiente_usd += flt(node.get("pending_to_collect") or 0)
            total_pendiente_vef += flt(node.get("pending_to_collect_vef") or 0)
            
            billed_usd += flt(node.get("billed") or 0)
            billed_vef += flt(node.get("billed_vef") or 0)
            
            vat_usd += flt(node.get("vat") or 0)
            vat_vef += flt(node.get("vat_vef") or 0)
            
            igtf_usd += flt(node.get("igtf") or 0)
            igtf_vef += flt(node.get("igtf_vef") or 0)
            
            availability_usd += flt(node.get("availability") or 0)
            availability_vef += flt(node.get("availability_vef") or 0)
            
            spent_usd += flt(node.get("spent") or 0)
            spent_vef += flt(node.get("spent_vef") or 0)

    # Count invoices without control number (or draft/unsubmitted in range)
    si_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [date_from, date_to]]
    }
    if branch:
        si_filters["branch"] = branch
        
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=["name", "bill_control"]
    )
    unpaid_count = sum(1 for inv in invoices if not inv.bill_control)

    igtf_usd_divided = flt(flt(igtf_vef) / flt(exchange_rate)) if exchange_rate else 0.0

    return {
        "unpaid_orders_count": unpaid_count,
        "grand_total": flt(total_pendiente_usd),
        "total_pendiente_usd": flt(total_pendiente_usd),
        "total_pendiente_vef": flt(total_pendiente_vef),
        "pending_base_amount": 0.0,
        "pending_tax_amount": 0.0,
        
        "actual_collected_total": flt(billed_usd),
        "collected_base_amount": flt(flt(billed_usd) - flt(vat_usd) - flt(igtf_usd_divided)),
        "collected_tax_amount": flt(vat_usd),
        
        "collected_usd_total": flt(billed_usd),
        "collected_usd_base": flt(flt(billed_usd) - flt(vat_usd) - flt(igtf_usd_divided)),
        "collected_usd_tax": flt(vat_usd),
        "collected_usd_igtf": flt(igtf_usd_divided),
        
        "collected_ves_total": flt(billed_vef),
        "collected_ves_base": flt(flt(billed_vef) - flt(vat_vef) - flt(igtf_vef)),
        "collected_ves_tax": flt(vat_vef),
        "collected_ves_igtf": flt(igtf_vef),
        "collected_ves_equivalent_usd": flt(billed_usd),
        
        "total_expenses_usd": flt(spent_usd),
        "total_expenses_vef": flt(spent_vef),
        
        "collected_total_usd": flt(billed_usd),
        "collected_total_vef": flt(billed_vef),
        "collected_total_usd_base": flt(flt(billed_usd) - flt(vat_usd) - flt(igtf_usd_divided)),
        "collected_total_vef_base": flt(flt(billed_vef) - flt(vat_vef) - flt(igtf_vef)),
        
        "available_usd": flt(availability_usd),
        "available_vef": flt(availability_vef),
    }


def _get_trend_data(company, date_from, date_to, branch):
    si_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [date_from, date_to]],
        "bill_control": ["is", "set"]
    }
    if branch:
        si_filters["branch"] = branch
        
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=si_filters,
        fields=["name", "net_total", "grand_total", "currency", "conversion_rate", "posting_date"]
    )
    
    invoice_names = [inv.name for inv in invoices]
    iva_by_invoice = {}
    if invoice_names:
        taxes = frappe.get_all(
            "Sales Taxes and Charges",
            filters={
                "parent": ["in", invoice_names],
                "is_tax_withholding_account": 0,
                "charge_type": "VAT"
            },
            fields=["parent", "tax_amount"]
        )
        for t in taxes:
            iva_by_invoice[t.parent] = flt(iva_by_invoice.get(t.parent, 0.0)) + flt(t.tax_amount or 0)
            
    rates_cache = {}
    from l10n_ve.utils.utils import get_exchange_rate
    
    daily_map = {}
    d_start = datetime.datetime.strptime(date_from, "%Y-%m-%d")
    d_end = datetime.datetime.strptime(date_to, "%Y-%m-%d")
    curr = d_start
    while curr <= d_end:
        daily_map[curr.strftime("%Y-%m-%d")] = 0.0
        curr += datetime.timedelta(days=1)
        
    for inv in invoices:
        is_usd = (inv.currency == "USD")
        rate = 1.0
        if not is_usd:
            date_str = str(inv.posting_date)
            if date_str not in rates_cache:
                rates_cache[date_str] = flt(get_exchange_rate(date_str, "USD") or 1.0)
            rate = rates_cache[date_str]
            
        gross_iva = flt(iva_by_invoice.get(inv.name, 0.0))
        gross_total_usd = flt((flt(inv.net_total or 0) + gross_iva) / rate) if rate else 0.0
        
        date_str = str(inv.posting_date)
        if date_str in daily_map:
            daily_map[date_str] += gross_total_usd
            
    labels = sorted(daily_map.keys())
    values = [daily_map[k] for k in labels]
    
    return {
        "labels": labels,
        "datasets": [
            {
                "name": "Cobrado",
                "values": values
            }
        ]
    }


def _get_customer_analytics(company, date_from, date_to, branch, state, municipality):
    # Customer queries
    invoice_subquery = "SELECT DISTINCT customer FROM `tabSales Invoice` WHERE company = %(company)s AND docstatus = 1"
    cust_params = {"company": company}
    
    if date_from:
        invoice_subquery += " AND posting_date >= %(date_from)s"
        cust_params["date_from"] = date_from
    if date_to:
        invoice_subquery += " AND posting_date <= %(date_to)s"
        cust_params["date_to"] = date_to
    if branch:
        invoice_subquery += " AND branch = %(branch)s"
        cust_params["branch"] = branch
        
    query = f"""
        SELECT DISTINCT
            cust.name, cust.disabled, cust.creation, addr.state, addr.county,
            s.state as state_name, m.municipality as mun_name
        FROM `tabCustomer` cust
        LEFT JOIN `tabDynamic Link` dl ON dl.link_doctype = 'Customer' AND dl.link_name = cust.name
        LEFT JOIN `tabAddress` addr ON dl.parent = addr.name
        LEFT JOIN `tabVE State` s ON addr.state = s.name
        LEFT JOIN `tabVE Municipality` m ON addr.county = m.name
        WHERE cust.name IN ({invoice_subquery})
    """
    
    if state:
        query += " AND addr.state = %(state)s"
        cust_params["state"] = state
    if municipality:
        query += " AND addr.county = %(municipality)s"
        cust_params["municipality"] = municipality

    customers = frappe.db.sql(query, cust_params, as_dict=True)

    active_count = 0
    suspended_count = 0
    new_this_month = 0
    
    # Growth monthly data grouping
    growth_months = {}
    from dateutil.relativedelta import relativedelta
    
    # Parse dates outside the customer loop for performance optimization
    d_from_dt = datetime.datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
    d_to_dt = datetime.datetime.strptime(date_to, "%Y-%m-%d") if date_to else None
    
    # Initialize last 6 months
    if d_to_dt:
        d_to = d_to_dt
    else:
        d_to = datetime.datetime.strptime(date_to, "%Y-%m-%d") if date_to else datetime.datetime.today()
    for i in range(5, -1, -1):
        m_date = d_to - relativedelta(months=i)
        m_label = m_date.strftime("%b")
        growth_months[m_date.strftime("%Y-%m")] = {"label": m_label, "count": 0}

    # Location distribution
    location_map = {}

    for c in customers:
        if c.disabled:
            suspended_count += 1
        else:
            active_count += 1
            
        creation_date = c.creation
        if creation_date:
            c_month = creation_date.strftime("%Y-%m")
            if c_month in growth_months:
                growth_months[c_month]["count"] += 1
                
            # New this month
            if d_from_dt and d_to_dt:
                if d_from_dt <= creation_date <= d_to_dt:
                    new_this_month += 1
                    
        loc = c.state_name or "Sin Ubicación"
        location_map[loc] = location_map.get(loc, 0) + 1

    # Growth chart formatting
    sorted_growth_keys = sorted(growth_months.keys())
    growth_labels = [growth_months[k]["label"] for k in sorted_growth_keys]
    growth_values = [growth_months[k]["count"] for k in sorted_growth_keys]

    # Plan distribution (use top items sold by quantity in this period)
    plan_labels = []
    plan_values = []
    
    sii_conds = ["si.company = %(company)s", "si.docstatus = 1"]
    sii_params = {"company": company}
    if date_from:
        sii_conds.append("si.posting_date >= %(date_from)s")
        sii_params["date_from"] = date_from
    if date_to:
        sii_conds.append("si.posting_date <= %(date_to)s")
        sii_params["date_to"] = date_to
    if branch:
        sii_conds.append("si.branch = %(branch)s")
        sii_params["branch"] = branch
        
    top_items_query = f"""
        SELECT sii.item_name, SUM(sii.qty) as total_qty
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE { " AND ".join(sii_conds) }
        GROUP BY sii.item_code, sii.item_name
        ORDER BY total_qty DESC
        LIMIT 5
    """
    top_items = frappe.db.sql(top_items_query, sii_params, as_dict=True)
    for ti in top_items:
        plan_labels.append(ti.item_name or "Artículo Sin Nombre")
        plan_values.append(int(ti.total_qty or 0))

    if not plan_labels:
        plan_labels = ["Sin Ventas"]
        plan_values = [0]

    # Location chart formatting
    sorted_locs = sorted(location_map.items(), key=lambda x: x[1], reverse=True)[:15]
    loc_labels = [l[0] for l in sorted_locs]
    loc_values = [l[1] for l in sorted_locs]

    if not loc_labels:
        loc_labels = ["Sin Ubicación"]
        loc_values = [0]

    return {
        "status_chart": {
            "labels": ["Activos", "Suspendidos/Inactivos"],
            "values": [active_count, suspended_count]
        },
        "growth_chart": {
            "labels": growth_labels,
            "datasets": [
                {
                    "name": "Servicios Nuevos",
                    "values": growth_values
                }
            ]
        },
        "plan_distribution": {
            "labels": plan_labels,
            "values": plan_values
        },
        "location_chart": {
            "labels": loc_labels,
            "values": loc_values
        },
        "new_customers_data": {
            "new_this_month": new_this_month,
            "average": int(sum(growth_values) / len(growth_values)) if growth_values else 0,
            "trend": "up"
        },
        "churn_data": {
            "current_rate": 0,
            "average_rate": 0,
            "churned_this_month": 0,
            "trend": "flat"
        }
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
        
    frappe.get_doc("Dashboard Gerencial").check_permission("read")
        
    currency = "USD"
        
    if not company:
        company = frappe.defaults.get_user_default("company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else ""
        
    # Default to current month if dates not provided
    if not date_from or not date_to:
        today = datetime.date.today()
        # Start of current month
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        # End of current month
        next_month = today.replace(day=28) + datetime.timedelta(days=4)
        date_to = (next_month - datetime.timedelta(days=next_month.day)).strftime("%Y-%m-%d")

    # Fetch exchange rate for the end of the report period (date_to)
    try:
        from l10n_ve.utils.utils import get_exchange_rate
        rate = get_exchange_rate(date_to, "USD")
        if not rate:
            frappe.throw(_("No se pudo obtener la tasa de cambio BCV para la fecha {0}").format(date_to))
        exchange_rate = rate
    except Exception as e:
        if "No se pudo obtener" in str(e):
            raise e
        frappe.throw(_("Error al recuperar la tasa de cambio BCV para la fecha {0}: {1}").format(date_to, e))

    # 1. Fetch KPI cards
    kpi_cards = {}
    try:
        kpi_cards = _get_kpi_cards(
            company=company,
            date_from=date_from,
            date_to=date_to,
            branch=branch,
            exchange_rate=exchange_rate
        )
    except Exception as e:
        frappe.log_error(f"Portal dashboard KPI error: {e}")

    # 2. Fetch recent payments (mocked/empty since not rendered in UI)
    payments = {"recent_payments": [], "payments_by_mode": []}

    # 3. Fetch sales trend for daily sales chart
    trend = {}
    try:
        trend = _get_trend_data(
            company=company,
            date_from=date_from,
            date_to=date_to,
            branch=branch
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
                "amount_usd": flt(r.amount_usd or 0),
                "amount_ves": flt(r.amount_ves or 0)
            })
    except Exception as e:
        frappe.log_error(f"Portal dashboard expenses grouping error: {e}")

    # 5. Fetch sales invoices created/posted today (Ventas del día)
    sales_today = []
    try:
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
            grand_total = flt(inv.grand_total or 0)
            base_grand_total = flt(inv.base_grand_total or 0)
            conv_rate = flt(inv.conversion_rate or 1)
            total_igtf_ves = flt(inv.total_igtf or 0)
            
            # Determine exchange rate to use
            rate = flt(conv_rate if conv_rate > 1 else exchange_rate)
            
            # IGTF amounts (stored in VES/Bs on Sales Invoice)
            igtf_ves = flt(total_igtf_ves)
            igtf_usd = flt(total_igtf_ves / rate) if rate > 0 else 0.0
            
            # IVA amounts
            iva_info = iva_map.get(inv.invoice_id, {"tax_amount": 0.0, "base_tax_amount": 0.0})
            if inv.currency == "USD":
                iva_usd = flt(iva_info.get("tax_amount") or 0)
                iva_ves = flt(iva_info.get("base_tax_amount") or 0) or flt(iva_usd * conv_rate)
            else:
                iva_ves = flt(iva_info.get("tax_amount") or 0)
                iva_usd = flt(iva_ves / rate) if rate > 0 else 0.0
            
            # Total amounts
            if inv.currency == "USD":
                amount_usd = flt(grand_total)
                amount_ves = flt(base_grand_total) or flt(grand_total * conv_rate)
            else:
                amount_ves = flt(grand_total)
                amount_usd = flt(grand_total / rate) if rate > 0 else 0.0
                
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
        d_from = datetime.datetime.strptime(date_from, "%Y-%m-%d") - datetime.timedelta(days=35)
        d_to = datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=35)
        
        conditions = ["exp_start_date between %(cal_date_from)s and %(cal_date_to)s"]
        params = {
            "cal_date_from": d_from.strftime("%Y-%m-%d"),
            "cal_date_to": d_to.strftime("%Y-%m-%d")
        }
        
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

    # 7. All-time IVA + IGTF totals (historical, maps to get_kpi_cards calculated totals)
    tax_totals = {"iva_ves": 0, "iva_usd": 0, "igtf_ves": 0, "igtf_usd": 0}
    if kpi_cards:
        # Re-use values resolved from get_dashboard_data for perfect match
        tax_totals = {
            "iva_ves":  kpi_cards.get("collected_ves_tax", 0),
            "iva_usd":  kpi_cards.get("collected_usd_tax", 0),
            "igtf_ves": kpi_cards.get("collected_ves_igtf", 0),
            "igtf_usd": kpi_cards.get("collected_usd_igtf", 0)
        }

    # 8. Fetch customer analytics
    customer_analytics = {}
    try:
        customer_analytics = _get_customer_analytics(
            company=company,
            date_from=date_from,
            date_to=date_to,
            branch=branch,
            state=state,
            municipality=municipality
        )
    except Exception as e:
        frappe.log_error(f"Portal dashboard customer analytics error: {e}")

    return {
        "kpi_cards": kpi_cards,
        "payments": payments,
        "trend": trend,
        "expenses_by_category": expenses_by_category,
        "sales_today": sales_today,
        "calendar_tasks": calendar_tasks,
        "exchange_rate": exchange_rate,
        "tax_totals": tax_totals,
        "customer_analytics": customer_analytics
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
    doc.insert(ignore_permissions=True)
    return {"status": "success", "task_id": doc.name}


