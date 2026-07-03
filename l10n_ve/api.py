from frappe.utils import getdate, flt
import datetime
from frappe import _
import frappe

@frappe.whitelist()
def get_portal_banks() -> list[str]:
    cache_key = "l10n_ve:portal_banks"
    portal_banks = frappe.cache().get_value(cache_key)

    if portal_banks:
        return portal_banks

    portal_banks = frappe.db.get_all(
        "Bank",
        fields=["name"],
        ignore_permissions=True,
    )

    frappe.cache().set_value(
        cache_key,
        portal_banks,
        expires_in_sec=3600
    )
    return portal_banks



@frappe.whitelist()
def get_filter_options():
    if frappe.session.user == "Guest":
        frappe.throw(_("Debe iniciar sesión para obtener opciones de filtro."))
        
    if not frappe.has_permission("Reporte Gerencial", "read"):
        frappe.throw(_("No tiene permisos para acceder a este recurso."), frappe.PermissionError)
        
    companies = [{"value": c.name, "label": c.name} for c in frappe.get_all("Company", fields=["name"], order_by="name")]
    branches = [{"value": b.name, "label": b.name} for b in frappe.get_all("VE Branch", fields=["name"], order_by="name")]
    routers = []
    if "domina_isp" in frappe.get_installed_apps():
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
    from l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial import calculate_real_kpis
    return calculate_real_kpis(company, date_from, date_to, branch=branch, exchange_rate=exchange_rate)


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
        LEFT JOIN `tabAddress` addr ON cust.customer_primary_address = addr.name
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
                if d_from_dt.date() <= creation_date.date() <= d_to_dt.date():
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
        
    if not frappe.has_permission("Reporte Gerencial", "read"):
        frappe.throw(_("No tiene permisos para acceder a este recurso."), frappe.PermissionError)
        
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

    if not frappe.has_permission("Reporte Gerencial", "read"):
        frappe.throw(_("No tiene permisos para acceder a este recurso."), frappe.PermissionError)

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


@frappe.whitelist()
def get_sales_data(company=None, period="today", date_from=None, date_to=None):
    if frappe.session.user == "Guest":
        frappe.throw(_("Debe iniciar sesión para ver los datos."))
        
    if not frappe.has_permission("Reporte Gerencial", "read"):
        frappe.throw(_("No tiene permisos para acceder a este recurso."), frappe.PermissionError)

    if not company:
        company = frappe.defaults.get_user_default("company")
    if not company:
        companies = frappe.get_all("Company", limit=1)
        company = companies[0].name if companies else ""

    from frappe.utils import today, getdate
    import datetime

    # Determine date range for sales based on period
    today_date = getdate(today())
    
    if period == "today":
        start_date = today_date
        end_date = today_date
    elif period == "week":
        # Start of current week (Monday)
        start_date = today_date - datetime.timedelta(days=today_date.weekday())
        end_date = today_date
    elif period == "month":
        # Start of current month
        start_date = today_date.replace(day=1)
        end_date = today_date
    elif period == "custom":
        start_date = getdate(date_from) if date_from else today_date
        end_date = getdate(date_to) if date_to else today_date
    else:
        start_date = today_date
        end_date = today_date

    # Fetch exchange rate to convert VEF/Bs amounts
    rate = 1.0
    try:
        from l10n_ve.utils.utils import get_exchange_rate
        r = get_exchange_rate(end_date.strftime("%Y-%m-%d"), "USD")
        if r:
            rate = flt(r)
    except Exception:
        pass

    # Query sales invoices
    conditions = [
        "si.company = %(company)s",
        "si.docstatus != 2",
        "si.posting_date >= %(start_date)s",
        "si.posting_date <= %(end_date)s"
    ]
    params = {
        "company": company,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d")
    }

    query = f"""
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
        where { " and ".join(conditions) }
        order by si.creation desc
    """
    raw_sales = frappe.db.sql(query, params, as_dict=True)

    if not raw_sales:
        return []

    # Fetch IVA taxes
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
                "tax_amount": flt(row.tax_amount or 0),
                "base_tax_amount": flt(row.base_tax_amount or 0)
            }

    sales_list = []
    for inv in raw_sales:
        grand_total = flt(inv.grand_total or 0)
        base_grand_total = flt(inv.base_grand_total or 0)
        conv_rate = flt(inv.conversion_rate or 1)
        total_igtf_ves = flt(inv.total_igtf or 0)
        
        # Determine exchange rate to use
        inv_rate = conv_rate if conv_rate > 1 else rate
        
        # IGTF amounts
        igtf_ves = flt(total_igtf_ves)
        igtf_usd = flt(total_igtf_ves / inv_rate) if inv_rate > 0 else 0.0
        
        # IVA amounts
        iva_info = iva_map.get(inv.invoice_id, {"tax_amount": 0.0, "base_tax_amount": 0.0})
        if inv.currency == "USD":
            iva_usd = flt(iva_info.get("tax_amount") or 0)
            iva_ves = flt(iva_info.get("base_tax_amount") or 0) or flt(iva_usd * conv_rate)
        else:
            iva_ves = flt(iva_info.get("tax_amount") or 0)
            iva_usd = flt(iva_ves / inv_rate) if inv_rate > 0 else 0.0
        
        # Total amounts
        if inv.currency == "USD":
            amount_usd = flt(grand_total)
            amount_ves = flt(base_grand_total) or flt(grand_total * conv_rate)
        else:
            amount_ves = flt(grand_total)
            amount_usd = flt(grand_total / inv_rate) if inv_rate > 0 else 0.0
            
        sales_list.append({
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

    return sales_list


@frappe.whitelist()
def download_kpi_detail_excel(company, date_from, date_to, kpi_name, branch=None):
    frappe.get_doc("Reporte Gerencial").check_permission("read")
    
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from frappe.utils import flt
    import io
    from l10n_ve.utils.utils import get_exchange_rate
    from l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial import calculate_real_kpis

    # Setup styles
    font_title = Font(name="Calibri", size=16, bold=True, color="1F4E78")
    font_subtitle = Font(name="Calibri", size=11, italic=True, color="595959")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=11, bold=True)
    font_regular = Font(name="Calibri", size=11)
    
    fill_header = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    fill_total = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    
    thin_side = Side(border_style="thin", color="D9D9D9")
    border_data = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    
    double_bottom_side = Side(border_style="double", color="000000")
    top_thin_side = Side(border_style="thin", color="000000")
    border_total = Border(top=top_thin_side, bottom=double_bottom_side)

    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")

    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    exchange_rate = flt(get_exchange_rate(date_to, "USD")) or 1.0

    rates_cache = {}
    def _local_get_cached_rate(d_str):
        if d_str not in rates_cache:
            rates_cache[d_str] = flt(get_exchange_rate(d_str, "USD")) or 1.0
        return rates_cache[d_str]

    def autofit_cols(ws, start_row=1):
        for col in ws.columns:
            max_len = 0
            for cell in col:
                if cell.row >= start_row and cell.value:
                    if isinstance(cell.value, (int, float)):
                        val_str = f"{cell.value:,.2f}"
                    else:
                        val_str = str(cell.value)
                    if len(val_str) > max_len:
                        max_len = len(val_str)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    if kpi_name == "por_cobrar":
        ws = wb.create_sheet(title="Por Cobrar")
        
        ws["A1"] = "Reporte Detallado: Por Cobrar"
        ws["A1"].font = font_title
        ws["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws["A2"].font = font_subtitle
        if branch:
            ws["A3"] = f"Sucursal: {branch}"
            ws["A3"].font = font_subtitle
        
        headers = ["Fecha Registro", "Factura", "Cliente", "Monto Neto (USD)", "IVA (USD)", "Total Factura (USD)", "Total Factura (Bs.)"]
        ws.append([])
        ws.append(headers)
        
        header_row_idx = 4 if not branch else 5
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        from l10n_ve.l10n_ve.doctype.reporte_gerencial.reporte_gerencial import _get_allowed_branches, _ve_branch_children
        si_filters = {
            "docstatus": 1,
            "company": company,
            "posting_date": ["between", [date_from, date_to]]
        }
        allowed = _get_allowed_branches(company)
        allowed_set = set(allowed) if allowed is not None else None
        if branch:
            universe = set(_ve_branch_children(branch))
            if allowed_set is not None:
                universe &= allowed_set
        elif allowed_set is not None:
            universe = set(allowed_set)
        else:
            universe = None

        if universe is not None:
            si_filters["branch"] = ["in", (list(universe) or ["__no_access__"])]

        table_filters = dict(si_filters)
        table_filters["docstatus"] = ["!=", 2]
        all_invoices = frappe.get_all(
            "Sales Invoice",
            filters=table_filters,
            fields=["name", "posting_date", "customer_name", "net_total", "base_net_total", "grand_total", "base_grand_total", "bill_control", "currency"]
        )

        row_idx = header_row_idx + 1
        total_net_usd = 0.0
        total_iva_usd = 0.0
        total_grand_usd = 0.0
        total_grand_vef = 0.0

        for inv in all_invoices:
            no_control = (inv.bill_control is None or str(inv.bill_control).strip() == "")
            if no_control:
                is_usd = (inv.currency == "USD")
                rate = 1.0 if is_usd else _local_get_cached_rate(str(inv.posting_date))
                
                g_total_usd = flt(inv.grand_total)
                g_total_vef = flt(inv.base_grand_total) if hasattr(inv, "base_grand_total") else (g_total_usd * exchange_rate)
                net_usd = flt(inv.net_total) if is_usd else flt(inv.net_total) / rate
                iva_usd = g_total_usd - net_usd

                row_data = [
                    str(inv.posting_date),
                    inv.name,
                    inv.customer_name,
                    net_usd,
                    iva_usd,
                    g_total_usd,
                    g_total_vef
                ]
                ws.append(row_data)
                
                for col_idx in range(1, len(row_data) + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell.font = font_regular
                    cell.border = border_data
                    if col_idx in (1, 2):
                        cell.alignment = align_center
                    elif col_idx == 3:
                        cell.alignment = align_left
                    else:
                        cell.alignment = align_right
                        cell.number_format = '#,##0.00'

                total_net_usd += net_usd
                total_iva_usd += iva_usd
                total_grand_usd += g_total_usd
                total_grand_vef += g_total_vef
                row_idx += 1

        total_row = ["Total", "", "", total_net_usd, total_iva_usd, total_grand_usd, total_grand_vef]
        ws.append(total_row)
        for col_idx in range(1, len(total_row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font_bold
            cell.border = border_total
            cell.fill = fill_total
            if col_idx == 1:
                cell.alignment = align_left
            elif col_idx > 3:
                cell.alignment = align_right
                cell.number_format = '#,##0.00'
                
        autofit_cols(ws, header_row_idx)

    elif kpi_name in ("cobrado_usd", "cobrado_ves"):
        currency_label = "USD" if kpi_name == "cobrado_usd" else "Bs."
        ws = wb.create_sheet(title=f"Cobrado {currency_label}")
        
        ws["A1"] = f"Reporte Detallado: Cobrado en {currency_label}"
        ws["A1"].font = font_title
        ws["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws["A2"].font = font_subtitle
        if branch:
            ws["A3"] = f"Sucursal: {branch}"
            ws["A3"].font = font_subtitle
            
        headers = [
            "Recibo de Pago", "Fecha Pago", "Cliente", "Factura Afectada",
            f"Monto Cobrado ({currency_label})", f"Base Exenta/Gravada ({currency_label})",
            f"IVA ({currency_label})", f"IGTF ({currency_label})"
        ]
        ws.append([])
        ws.append(headers)
        
        header_row_idx = 4 if not branch else 5
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query = """
            select 
                pe.name as payment_entry,
                pe.paid_on_currency,
                pe.paid_currency_amount,
                pe.paid_amount as pe_paid_amount,
                pe.posting_date,
                ref.allocated_amount,
                pe.total_allocated_amount,
                pe.party as customer_name,
                si.name as invoice_name,
                si.base_net_total,
                si.base_grand_total,
                si.total_igtf,
                (select sum(base_tax_amount) from `tabSales Taxes and Charges` where parent = si.name and (description like '%%IVA%%' or description like '%%I.V.A.%%') and is_tax_withholding_account = 0) as base_iva_amount
            from `tabPayment Entry Reference` ref
            join `tabPayment Entry` pe on ref.parent = pe.name
            join `tabSales Invoice` si on ref.reference_name = si.name
            where pe.docstatus = 1
              and pe.company = %(company)s
              and pe.posting_date between %(date_from)s and %(date_to)s
        """
        params = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query += " and si.branch = %(branch)s"
            params["branch"] = branch
            
        res = frappe.db.sql(query, params, as_dict=True)

        row_idx = header_row_idx + 1
        t_cobrado = 0.0
        t_base = 0.0
        t_iva = 0.0
        t_igtf = 0.0

        for row in res:
            curr = row['paid_on_currency'] or 'VEF'
            is_usd_kpi = (kpi_name == "cobrado_usd")
            
            if is_usd_kpi and curr != "USD":
                continue
            if not is_usd_kpi and curr not in ("VEF", "VES"):
                continue

            pe_total_allocated = flt(row['total_allocated_amount'] or 0)
            allocated = flt(row['allocated_amount'] or 0)
            ratio = allocated / pe_total_allocated if pe_total_allocated > 0 else 1.0
            
            paid_currency_total = flt(row['paid_currency_amount'] or 0)
            paid_val = paid_currency_total * ratio if is_usd_kpi else allocated

            total_vef = flt(row['base_grand_total'] or 0)
            base_vef = flt(row['base_net_total'] or 0)
            iva_vef = flt(row['base_iva_amount'] or 0)
            igtf_vef = flt(row['total_igtf'] or 0)
            
            ratio_base = base_vef / total_vef if total_vef > 0 else 1.0
            ratio_tax = iva_vef / total_vef if total_vef > 0 else 0.0
            ratio_igtf = igtf_vef / total_vef if total_vef > 0 else 0.0

            val_base = paid_val * ratio_base
            val_tax = paid_val * ratio_tax
            val_igtf = paid_val * ratio_igtf

            row_data = [
                row['payment_entry'],
                str(row['posting_date']),
                row['customer_name'],
                row['invoice_name'],
                paid_val,
                val_base,
                val_tax,
                val_igtf
            ]
            ws.append(row_data)
            
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_data
                if col_idx in (1, 2, 4):
                    cell.alignment = align_center
                elif col_idx == 3:
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'

            t_cobrado += paid_val
            t_base += val_base
            t_iva += val_tax
            t_igtf += val_igtf
            row_idx += 1

        total_row = ["Total", "", "", "", t_cobrado, t_base, t_iva, t_igtf]
        ws.append(total_row)
        for col_idx in range(1, len(total_row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font_bold
            cell.border = border_total
            cell.fill = fill_total
            if col_idx == 1:
                cell.alignment = align_left
            elif col_idx > 4:
                cell.alignment = align_right
                cell.number_format = '#,##0.00'
                
        autofit_cols(ws, header_row_idx)

    elif kpi_name == "gastos":
        ws = wb.create_sheet(title="Gastos")
        
        ws["A1"] = "Reporte Detallado: Gastos (Egresos)"
        ws["A1"].font = font_title
        ws["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws["A2"].font = font_subtitle
        if branch:
            ws["A3"] = f"Sucursal: {branch}"
            ws["A3"].font = font_subtitle
            
        headers = ["Fecha Gasto", "Documento", "Proveedor", "Categoría / Concepto", "Moneda", "Monto USD", "Monto VES"]
        ws.append([])
        ws.append(headers)
        
        header_row_idx = 4 if not branch else 5
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query_expenses = """
            select 
                expense_date,
                name,
                employee_name as vendor,
                expense_description as category,
                spending_currency,
                total_exchange as total_usd,
                total as total_vef
            from `tabExpense`
            where docstatus = 1 and company = %(company)s and expense_date between %(date_from)s and %(date_to)s
        """
        params_exp = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query_expenses += " and branch = %(branch)s"
            params_exp["branch"] = branch
            
        expenses_res = frappe.db.sql(query_expenses, params_exp, as_dict=True)

        row_idx = header_row_idx + 1
        t_usd = 0.0
        t_vef = 0.0

        for r in expenses_res:
            row_data = [
                str(r['expense_date']),
                r['name'],
                r['vendor'] or "",
                r['category'] or "",
                r['spending_currency'],
                flt(r['total_usd']),
                flt(r['total_vef'])
            ]
            ws.append(row_data)
            
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_data
                if col_idx in (1, 2, 5):
                    cell.alignment = align_center
                elif col_idx in (3, 4):
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'

            t_usd += flt(r['total_usd'])
            t_vef += flt(r['total_vef'])
            row_idx += 1

        total_row = ["Total", "", "", "", "", t_usd, t_vef]
        ws.append(total_row)
        for col_idx in range(1, len(total_row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font_bold
            cell.border = border_total
            cell.fill = fill_total
            if col_idx == 1:
                cell.alignment = align_left
            elif col_idx > 5:
                cell.alignment = align_right
                cell.number_format = '#,##0.00'
                
        autofit_cols(ws, header_row_idx)

    elif kpi_name in ("disponible_usd", "disponible_ves"):
        curr_label = "USD" if kpi_name == "disponible_usd" else "Bs."
        
        ws_sum = wb.create_sheet(title="Resumen Disponibilidad")
        ws_sum["A1"] = f"Resumen de Disponibilidad en {curr_label}"
        ws_sum["A1"].font = font_title
        ws_sum["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws_sum["A2"].font = font_subtitle
        
        real_kpis = calculate_real_kpis(company, date_from, date_to, branch=branch, exchange_rate=exchange_rate)
        if kpi_name == "disponible_usd":
            cobrado = real_kpis.get("collected_usd_total", 0.0)
            spent = real_kpis.get("total_expenses_usd", 0.0)
            avail = real_kpis.get("available_usd", 0.0)
        else:
            cobrado = real_kpis.get("collected_ves_total", 0.0)
            spent = real_kpis.get("total_expenses_vef", 0.0)
            avail = real_kpis.get("available_vef", 0.0)

        ws_sum["A5"] = "Concepto"
        ws_sum["B5"] = "Monto"
        for col_idx in (1, 2):
            cell = ws_sum.cell(row=5, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        ws_sum["A6"] = f"Total Cobrado (Ingresos en {curr_label})"
        ws_sum["B6"] = cobrado
        ws_sum["A7"] = f"Total Gastado (Egresos en {curr_label})"
        ws_sum["B7"] = spent
        ws_sum["A8"] = "Disponible Neto"
        ws_sum["B8"] = avail

        for col_idx in (1, 2):
            for row_idx in (6, 7, 8):
                cell = ws_sum.cell(row=row_idx, column=col_idx)
                if row_idx == 8:
                    cell.font = font_bold
                    cell.border = border_total
                    cell.fill = fill_total
                else:
                    cell.font = font_regular
                    cell.border = border_data
                if col_idx == 1:
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'
                    
        ws_sum.column_dimensions["A"].width = 35
        ws_sum.column_dimensions["B"].width = 20

        ws_pay = wb.create_sheet(title="Detalle Ingresos (Cobros)")
        pay_headers = [
            "Recibo de Pago", "Fecha Pago", "Cliente", "Factura Afectada",
            f"Monto Cobrado ({curr_label})", f"Base Exenta/Gravada ({curr_label})",
            f"IVA ({curr_label})", f"IGTF ({curr_label})"
        ]
        ws_pay.append(pay_headers)
        for col_idx, h in enumerate(pay_headers, 1):
            cell = ws_pay.cell(row=1, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query = """
            select 
                pe.name as payment_entry,
                pe.paid_on_currency,
                pe.paid_currency_amount,
                pe.paid_amount as pe_paid_amount,
                pe.posting_date,
                ref.allocated_amount,
                pe.total_allocated_amount,
                pe.party as customer_name,
                si.name as invoice_name,
                si.base_net_total,
                si.base_grand_total,
                si.total_igtf,
                (select sum(base_tax_amount) from `tabSales Taxes and Charges` where parent = si.name and (description like '%%IVA%%' or description like '%%I.V.A.%%') and is_tax_withholding_account = 0) as base_iva_amount
            from `tabPayment Entry Reference` ref
            join `tabPayment Entry` pe on ref.parent = pe.name
            join `tabSales Invoice` si on ref.reference_name = si.name
            where pe.docstatus = 1
              and pe.company = %(company)s
              and pe.posting_date between %(date_from)s and %(date_to)s
        """
        params = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query += " and si.branch = %(branch)s"
            params["branch"] = branch
            
        res = frappe.db.sql(query, params, as_dict=True)
        row_idx = 2
        for row in res:
            curr = row['paid_on_currency'] or 'VEF'
            is_usd_kpi = (kpi_name == "disponible_usd")
            if is_usd_kpi and curr != "USD":
                continue
            if not is_usd_kpi and curr not in ("VEF", "VES"):
                continue

            pe_total_allocated = flt(row['total_allocated_amount'] or 0)
            allocated = flt(row['allocated_amount'] or 0)
            ratio = allocated / pe_total_allocated if pe_total_allocated > 0 else 1.0
            paid_currency_total = flt(row['paid_currency_amount'] or 0)
            
            paid_val = paid_currency_total * ratio if is_usd_kpi else allocated
            total_vef = flt(row['base_grand_total'] or 0)
            base_vef = flt(row['base_net_total'] or 0)
            iva_vef = flt(row['base_iva_amount'] or 0)
            igtf_vef = flt(row['total_igtf'] or 0)
            
            ratio_base = base_vef / total_vef if total_vef > 0 else 1.0
            ratio_tax = iva_vef / total_vef if total_vef > 0 else 0.0
            ratio_igtf = igtf_vef / total_vef if total_vef > 0 else 0.0

            row_data = [
                row['payment_entry'],
                str(row['posting_date']),
                row['customer_name'],
                row['invoice_name'],
                paid_val,
                paid_val * ratio_base,
                paid_val * ratio_tax,
                paid_val * ratio_igtf
            ]
            ws_pay.append(row_data)
            for col_idx in range(1, len(row_data) + 1):
                cell = ws_pay.cell(row=row_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_data
                if col_idx in (1, 2, 4):
                    cell.alignment = align_center
                elif col_idx == 3:
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'
            row_idx += 1
        autofit_cols(ws_pay, 1)

        ws_exp = wb.create_sheet(title="Detalle Egresos (Gastos)")
        exp_headers = ["Fecha Gasto", "Documento", "Proveedor", "Categoría / Concepto", "Moneda", f"Monto ({curr_label})"]
        ws_exp.append(exp_headers)
        for col_idx, h in enumerate(exp_headers, 1):
            cell = ws_exp.cell(row=1, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query_expenses = """
            select 
                expense_date,
                name,
                employee_name as vendor,
                expense_description as category,
                spending_currency,
                total_exchange as total_usd,
                total as total_vef
            from `tabExpense`
            where docstatus = 1 and company = %(company)s and expense_date between %(date_from)s and %(date_to)s
        """
        params_exp = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query_expenses += " and branch = %(branch)s"
            params_exp["branch"] = branch
        expenses_res = frappe.db.sql(query_expenses, params_exp, as_dict=True)
        
        row_idx = 2
        for r in expenses_res:
            curr = r['spending_currency']
            is_usd_kpi = (kpi_name == "disponible_usd")
            if is_usd_kpi and curr != "USD":
                continue
            if not is_usd_kpi and curr not in ("VEF", "VES"):
                continue
                
            amt = flt(r['total_usd']) if is_usd_kpi else flt(r['total_vef'])
            row_data = [
                str(r['expense_date']),
                r['name'],
                r['vendor'] or "",
                r['category'] or "",
                r['spending_currency'],
                amt
            ]
            ws_exp.append(row_data)
            for col_idx in range(1, len(row_data) + 1):
                cell = ws_exp.cell(row=row_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_data
                if col_idx in (1, 2, 5):
                    cell.alignment = align_center
                elif col_idx in (3, 4):
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'
            row_idx += 1
        autofit_cols(ws_exp, 1)

    elif kpi_name in ("ret_iva", "ret_islr"):
        title_lbl = "Retención IVA" if kpi_name == "ret_iva" else "Retención ISLR"
        ws = wb.create_sheet(title=title_lbl)
        
        ws["A1"] = f"Reporte Detallado: {title_lbl}"
        ws["A1"].font = font_title
        ws["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws["A2"].font = font_subtitle
        if branch:
            ws["A3"] = f"Sucursal: {branch}"
            ws["A3"].font = font_subtitle
            
        headers = ["Fecha Factura", "Factura", "Cliente", "Cuenta Retención", "Monto Retención (USD)", "Monto Retención (Bs.)"]
        ws.append([])
        ws.append(headers)
        
        header_row_idx = 4 if not branch else 5
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query_invoices = """
            select name, posting_date, currency, total_igtf
            from `tabSales Invoice`
            where docstatus = 1 and company = %(company)s
              and posting_date between %(date_from)s and %(date_to)s
        """
        params_inv = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query_invoices += " and branch = %(branch)s"
            params_inv["branch"] = branch
        invoices_list = frappe.db.sql(query_invoices, params_inv, as_dict=True)
        invoice_names = [x.name for x in invoices_list]

        row_idx = header_row_idx + 1
        tot_usd = 0.0
        tot_vef = 0.0

        if invoice_names:
            taxes_raw = frappe.db.get_all(
                "Sales Taxes and Charges",
                filters={"parent": ["in", invoice_names], "is_tax_withholding_account": 1},
                fields=["parent", "account_head", "tax_amount", "base_tax_amount"]
            )
            inv_map = {x.name: x for x in invoices_list}
            for t in taxes_raw:
                ac_lower = str(t.account_head).lower()
                is_iva_match = ("iva" in ac_lower and kpi_name == "ret_iva")
                is_islr_match = ("islr" in ac_lower and kpi_name == "ret_islr")
                if not (is_iva_match or is_islr_match):
                    continue

                inv_doc = inv_map.get(t.parent)
                if not inv_doc:
                    continue
                is_usd = (inv_doc.currency == "USD")
                rate_val = 1.0 if is_usd else _local_get_cached_rate(str(inv_doc.posting_date))
                
                vat_v = flt(t.base_tax_amount)
                vat_usd = flt(t.tax_amount) if is_usd else vat_v / rate_val

                row_data = [
                    str(inv_doc.posting_date),
                    inv_doc.name,
                    frappe.db.get_value("Sales Invoice", inv_doc.name, "customer_name") or "",
                    t.account_head,
                    vat_usd,
                    vat_v
                ]
                ws.append(row_data)
                
                for col_idx in range(1, len(row_data) + 1):
                    cell = ws.cell(row=row_idx, column=col_idx)
                    cell.font = font_regular
                    cell.border = border_data
                    if col_idx in (1, 2):
                        cell.alignment = align_center
                    elif col_idx in (3, 4):
                        cell.alignment = align_left
                    else:
                        cell.alignment = align_right
                        cell.number_format = '#,##0.00'
                tot_usd += vat_usd
                tot_vef += vat_v
                row_idx += 1

        total_row = ["Total", "", "", "", tot_usd, tot_vef]
        ws.append(total_row)
        for col_idx in range(1, len(total_row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font_bold
            cell.border = border_total
            cell.fill = fill_total
            if col_idx == 1:
                cell.alignment = align_left
            elif col_idx > 4:
                cell.alignment = align_right
                cell.number_format = '#,##0.00'
                
        autofit_cols(ws, header_row_idx)

    elif kpi_name == "igtf":
        ws = wb.create_sheet(title="IGTF Total")
        
        ws["A1"] = "Reporte Detallado: IGTF Total"
        ws["A1"].font = font_title
        ws["A2"] = f"Empresa: {company} | Periodo: {date_from} al {date_to}"
        ws["A2"].font = font_subtitle
        if branch:
            ws["A3"] = f"Sucursal: {branch}"
            ws["A3"].font = font_subtitle
            
        headers = ["Fecha Factura", "Factura", "Cliente", "IGTF (USD)", "IGTF (Bs.)"]
        ws.append([])
        ws.append(headers)
        
        header_row_idx = 4 if not branch else 5
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx)
            cell.font = font_header
            cell.fill = fill_header
            cell.alignment = align_center

        query_invoices = """
            select name, posting_date, currency, total_igtf, base_amount_igtf
            from `tabSales Invoice`
            where docstatus = 1 and company = %(company)s
              and posting_date between %(date_from)s and %(date_to)s
        """
        params_inv = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch:
            query_invoices += " and branch = %(branch)s"
            params_inv["branch"] = branch
        invoices_list = frappe.db.sql(query_invoices, params_inv, as_dict=True)

        row_idx = header_row_idx + 1
        tot_usd = 0.0
        tot_vef = 0.0

        for inv in invoices_list:
            igtf_val = flt(inv.total_igtf)
            if igtf_val <= 0:
                continue

            is_usd = (inv.currency == "USD")
            rate_val = flt(_local_get_cached_rate(str(inv.posting_date)))
            
            igtf_usd = igtf_val if is_usd else (igtf_val / rate_val if rate_val > 0 else 0.0)
            
            base_igtf = flt(inv.get("base_amount_igtf") or 0)
            if is_usd:
                igtf_vef = base_igtf if base_igtf > 0 else (igtf_val * rate_val)
            else:
                igtf_vef = igtf_val

            row_data = [
                str(inv.posting_date),
                inv.name,
                frappe.db.get_value("Sales Invoice", inv.name, "customer_name") or "",
                igtf_usd,
                igtf_vef
            ]
            ws.append(row_data)
            
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = font_regular
                cell.border = border_data
                if col_idx in (1, 2):
                    cell.alignment = align_center
                elif col_idx == 3:
                    cell.alignment = align_left
                else:
                    cell.alignment = align_right
                    cell.number_format = '#,##0.00'
            tot_usd += igtf_usd
            tot_vef += igtf_vef
            row_idx += 1

        total_row = ["Total", "", "", tot_usd, tot_vef]
        ws.append(total_row)
        for col_idx in range(1, len(total_row) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font_bold
            cell.border = border_total
            cell.fill = fill_total
            if col_idx == 1:
                cell.alignment = align_left
            elif col_idx > 3:
                cell.alignment = align_right
                cell.number_format = '#,##0.00'
                
        autofit_cols(ws, header_row_idx)

    # Save to BytesIO and return binary response
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    content = out.read()

    frappe.local.response.filename = f"Detalle_{kpi_name}_{date_from}_a_{date_to}.xlsx"
    frappe.local.response.filecontent = content
    frappe.local.response.type = "binary"


