# -*- coding: utf-8 -*-
import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt

class ReporteGerencial(Document):
    pass


def _get_cached_rate(date_str, cache):
    """Helper to cache exchange rates to prevent N+1 query loops."""
    if date_str not in cache:
        from l10n_ve.utils.utils import get_exchange_rate
        cache[date_str] = flt(get_exchange_rate(date_str, "USD")) or 1.0
    return cache[date_str]


# =============================================================================
# ÁRBOL DE SUCURSALES + PERMISOS (replica la lógica del panel ISP)
# =============================================================================
def _ve_branch_children(branch_name):
    """Sucursal + todos sus descendientes (vía lft/rgt)."""
    if not branch_name:
        return []
    info = frappe.db.get_value("VE Branch", branch_name, ["lft", "rgt"], as_dict=True)
    if not info:
        return []
    return frappe.db.get_all(
        "VE Branch",
        filters={"lft": [">=", info.lft], "rgt": ["<=", info.rgt]},
        pluck="name",
    )


def _get_allowed_branches(company=None):
    """Sucursales permitidas para el usuario: None=todas (Administrator), []=sin
    acceso, [list]=permitidas. Basado en User Permission allow='VE Branch' + hijos."""
    user = frappe.session.user
    if user == "Administrator":
        return None

    # Si no hay sucursales registradas para la empresa (o en el sistema), permitir ver todo
    has_company = frappe.get_meta("VE Branch").has_field("company")
    exists_filters = {"company": company} if (company and has_company) else {}
    if not frappe.db.get_value("VE Branch", exists_filters, "name"):
        return None

    perm = frappe.db.get_all(
        "User Permission",
        filters={"user": user, "allow": "VE Branch"},
        pluck="for_value",
    )
    if not perm:
        return []
    allowed = set()
    for b in perm:
        allowed.update(_ve_branch_children(b))
    return list(allowed)


# Campos numéricos que se consolidan (padre = propio + descendientes). Son lineales,
# así que sumar Disponibilidad/Utilidad directamente da el mismo resultado que recalcular.
_TREE_FIELDS = [
    "pending_to_collect", "payment_order", "payment_order_vat", "billed", "vat",
    "vat_after_withholding", "vat_withholding", "islr_withholding", "igtf",
    "ganancia", "perdida", "availability", "spent", "profit",
    "pending_to_collect_vef", "payment_order_vef", "payment_order_vat_vef", "billed_vef",
    "vat_vef", "vat_after_withholding_vef", "vat_withholding_vef", "islr_withholding_vef",
    "igtf_vef", "ganancia_vef", "perdida_vef", "availability_vef", "spent_vef", "profit_vef",
]


def _collect_descendants(branch_name, children_map):
    descendants = [branch_name]
    stack = [branch_name]
    while stack:
        current = stack.pop()
        for child in children_map.get(current, []):
            descendants.append(child)
            stack.append(child)
    return descendants


def _sum_branch_rows(branch_map, names):
    totals = {k: 0.0 for k in _TREE_FIELDS}
    for name in names:
        row = branch_map.get(name, {})
        for k in _TREE_FIELDS:
            totals[k] += flt(row.get(k, 0))
    return totals


def _append_branch_recursive(branch_name, branch_map, children_map, result, indent, allowed_set):
    descendants = _collect_descendants(branch_name, children_map)
    if allowed_set is not None:
        descendants = [d for d in descendants if d in allowed_set]
    totals = _sum_branch_rows(branch_map, descendants)
    direct = children_map.get(branch_name, [])
    visible = [c for c in direct if allowed_set is None or c in allowed_set]
    result.append({"branch": branch_name, "indent": indent, "is_group": len(visible) > 0, **totals})
    for child in visible:
        _append_branch_recursive(child, branch_map, children_map, result, indent + 1, allowed_set)


def _build_branch_tree(branch_map, all_ve_branches, allowed_set, selected_branch):
    """Construye el árbol consolidado (cada nodo = su data + la de sus descendientes)."""
    children_map = {}
    for b in all_ve_branches:
        children_map.setdefault(b.parent_ve_branch or "", []).append(b.name)
    if selected_branch:
        roots = [] if (allowed_set is not None and selected_branch not in allowed_set) else [selected_branch]
    elif allowed_set is not None:
        # Raíz para este usuario: permitida y cuyo padre NO está permitido.
        roots = [
            b.name for b in all_ve_branches
            if b.name in allowed_set and (not b.parent_ve_branch or b.parent_ve_branch not in allowed_set)
        ]
    else:
        roots = children_map.get("", [])
    result = []
    for root in roots:
        _append_branch_recursive(root, branch_map, children_map, result, 0, allowed_set)
    return result


@frappe.whitelist()
def get_dashboard_data(company, from_date, to_date, branch=None, cost_center=None, customer=None):
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
    if cost_center:
        si_filters["name"] = ["in", frappe.get_all("Sales Invoice Item", filters={"cost_center": cost_center}, pluck="parent")]
    if customer:
        si_filters["customer"] = customer

    # --- Permisos + universo de sucursales (árbol VE Branch, igual que el ISP) ---
    allowed = _get_allowed_branches(company)          # None=todas, []=ninguna, [list]
    allowed_set = set(allowed) if allowed is not None else None
    if branch:
        universe = set(_ve_branch_children(branch))   # seleccionada + descendientes
        if allowed_set is not None:
            universe &= allowed_set
    elif allowed_set is not None:
        universe = set(allowed_set)
    else:
        universe = None                                # Administrator: sin filtro (todas)
    # Restringir la DATA a las sucursales del universo (seguridad + selección)
    if universe is not None:
        si_filters["branch"] = ["in", (list(universe) or ["__no_access__"])]
    # Tupla y fragmentos SQL para filtrar las queries crudas (IGTF/FX/Gastos) por
    # sucursal permitida. Sin esto, un usuario restringido vería el FX/IGTF de
    # sucursales fuera de su alcance (p. ej. agregado en "Sin Sucursal").
    universe_param = (tuple(universe) or ("__no_access__",)) if universe is not None else None
    sql_branch_si = " AND si.branch IN %s" if universe is not None else ""
    sql_branch_pe = " AND pe.branch IN %s" if universe is not None else ""
    sql_branch_exp = " AND branch IN %s" if universe is not None else ""

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
    branch_data_map = {}

    all_ve_branches = frappe.get_all(
        "VE Branch",
        filters={"company": company} if frappe.get_meta("VE Branch").has_field("company") else {},
        fields=["name", "parent_ve_branch"],
        order_by="lft",  # orden de árbol (nested set): hermanos en el orden correcto
    )
    branch_names = set(universe) if universe is not None else {b.name for b in all_ve_branches}

    # Retrieve expenses via tabExpense
    expenses_by_branch = {}
    expenses_vef_by_branch = {}
    if frappe.db.exists("DocType", "Expense") and not customer:
        expenses_raw = frappe.db.sql(f"""
            SELECT branch, SUM(
                CASE WHEN spending_currency = 'USD' THEN total_exchange
                WHEN usd_reference_rate > 0 THEN total / usd_reference_rate
                ELSE total
                END
            ) as total_spent,
            SUM(total) as total_spent_vef
            FROM `tabExpense`
            WHERE docstatus = 1 AND company = %s AND expense_date BETWEEN %s AND %s{sql_branch_exp}
            GROUP BY branch
        """, (company, from_date, to_date) + ((universe_param,) if universe is not None else ()), as_dict=True)
        expenses_by_branch = {r.branch: flt(r.total_spent) for r in expenses_raw if r.branch}
        expenses_vef_by_branch = {r.branch: flt(r.total_spent_vef) for r in expenses_raw if r.branch}

    # Retrieve IGTF per branch
    igtf_by_branch = {}
    igtf_vef_by_branch = {}
    if accounts_igtf:
        # Group by branch for Sales Invoice IGTF
        sql_si_cust = " AND si.customer = %s" if customer else ""
        si_igtf = frappe.db.sql(f"""
            SELECT si.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabSales Invoice` si ON gle.voucher_no = si.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s{sql_branch_si}{sql_si_cust}
        """, (tuple(accounts_igtf), from_date, to_date) + 
             ((universe_param,) if universe is not None else ()) + 
             ((customer,) if customer else ()), as_dict=True)

        # Group by branch for Payment Entry IGTF
        sql_pe_cust = " AND pe.party = %s" if customer else ""
        pe_igtf = frappe.db.sql(f"""
            SELECT pe.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s{sql_branch_pe}{sql_pe_cust}
        """, (tuple(accounts_igtf), from_date, to_date) + 
             ((universe_param,) if universe is not None else ()) + 
             ((customer,) if customer else ()), as_dict=True)

        for rows in (si_igtf, pe_igtf):
            for r in rows:
                b = r.branch or "Sin Sucursal"
                if b not in igtf_by_branch:
                    igtf_by_branch[b] = 0.0
                    igtf_vef_by_branch[b] = 0.0
                amount = flt(r.credit) - flt(r.debit)
                igtf_vef_by_branch[b] += amount  # VEF nativo (moneda compañía)
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
    ganancia_vef_by_branch = {}
    perdida_vef_by_branch = {}
    fx_cond = "AND si_fx.branch IN %(branches)s" if universe is not None else ""
    if customer:
        fx_cond += " AND si_fx.customer = %(customer)s"
    fx_params = {"company": company, "from_date": from_date, "to_date": to_date}
    if universe is not None:
        fx_params["branches"] = universe_param
    if customer:
        fx_params["customer"] = customer

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
        ganancia_vef_by_branch[b] = ganancia_vef_by_branch.get(b, 0.0) + flt(fx.ganancia)
        perdida_vef_by_branch[b] = perdida_vef_by_branch.get(b, 0.0) + flt(fx.perdida)

    # 1. Single bulk query of all invoices of the company during the period
    # Incluir borradores (docstatus 0): las facturas de suscripción aún sin número
    # de control deben contar en "Por cobrar" (mismo criterio que el ISP).
    table_filters = dict(si_filters)
    table_filters["docstatus"] = ["!=", 2]
    all_invoices = frappe.get_all(
        "Sales Invoice",
        filters=table_filters,
        fields=["name", "net_total", "base_net_total", "grand_total", "total_taxes_and_charges", "bill_control", "currency", "posting_date", "branch", "docstatus", "customer", "customer_name"]
    )

    # 2. Single bulk query of all withholdings for these invoices
    invoice_names = [inv.name for inv in all_invoices]
    withholdings_by_invoice = {}
    iva_by_invoice = {}
    iva_vef_by_invoice = {}
    if invoice_names:
        taxes_raw = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={
                "parent": ["in", invoice_names],
                "is_tax_withholding_account": 1
            },
            fields=["parent", "account_head", "tax_amount", "base_tax_amount"]
        )
        for t in taxes_raw:
            inv_name = t.parent
            if inv_name not in withholdings_by_invoice:
                withholdings_by_invoice[inv_name] = {"vat": 0.0, "islr": 0.0, "vat_vef": 0.0, "islr_vef": 0.0}
            
            ac_lower = str(t.account_head).lower()
            if "iva" in ac_lower:
                withholdings_by_invoice[inv_name]["vat"] += flt(t.tax_amount)
                withholdings_by_invoice[inv_name]["vat_vef"] += flt(t.base_tax_amount)
            elif "islr" in ac_lower:
                withholdings_by_invoice[inv_name]["islr"] += flt(t.tax_amount)
                withholdings_by_invoice[inv_name]["islr_vef"] += flt(t.base_tax_amount)

        # IVA bruto (fila VAT, no retención) para calcular Facturado = base + IVA bruto
        iva_raw = frappe.db.get_all(
            "Sales Taxes and Charges",
            filters={
                "parent": ["in", invoice_names],
                "is_tax_withholding_account": 0,
                "charge_type": "VAT"
            },
            fields=["parent", "tax_amount", "base_tax_amount"]
        )
        for t in iva_raw:
            iva_by_invoice[t.parent] = iva_by_invoice.get(t.parent, 0.0) + flt(t.tax_amount)
            iva_vef_by_invoice[t.parent] = iva_vef_by_invoice.get(t.parent, 0.0) + flt(t.base_tax_amount)

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
        # Mirrors en VEF NATIVO (base_* de la factura, sin convertir por tasa)
        payment_order_vef = 0.0
        payment_order_vat_vef = 0.0
        billed_vef = 0.0
        vat_billed_vef = 0.0
        vat_withholding_vef = 0.0
        islr_withholding_vef = 0.0
        pending_to_collect_vef = 0.0

        for inv in b_invoices:
            is_usd = (inv.currency == "USD")
            rate = 1.0 if is_usd else _get_cached_rate(str(inv.posting_date), rates_cache)

            inv_withholdings = withholdings_by_invoice.get(inv.name, {"vat": 0.0, "islr": 0.0, "vat_vef": 0.0, "islr_vef": 0.0})
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

            # VEF nativo: base_* (moneda compañía), tal cual el bolívar facturado.
            base_vef = flt(inv.base_net_total)
            tax_vef = flt(iva_vef_by_invoice.get(inv.name, 0.0))
            g_total_vef = base_vef + tax_vef
            ret_iva_vef = flt(inv_withholdings["vat_vef"])
            ret_islr_vef = flt(inv_withholdings["islr_vef"])

            payment_order += g_total_usd
            payment_order_vat += tax_usd
            payment_order_vef += g_total_vef
            payment_order_vat_vef += tax_vef

            # Facturado = aprobada (docstatus 1) CON número de control.
            # Sin número de control (incl. borradores de suscripción) -> Por cobrar.
            has_control = (inv.docstatus == 1 and inv.bill_control is not None and str(inv.bill_control).strip() != "")
            no_control = (inv.bill_control is None or str(inv.bill_control).strip() == "")
            if has_control:
                billed += g_total_usd
                vat_billed += tax_usd
                vat_withholding += ret_iva_usd
                islr_withholding += ret_islr_usd
                billed_vef += g_total_vef
                vat_billed_vef += tax_vef
                vat_withholding_vef += ret_iva_vef
                islr_withholding_vef += ret_islr_vef
            elif no_control:
                pending_to_collect += g_total_usd
                pending_to_collect_vef += g_total_vef

        vat_after_withholding = vat_billed - vat_withholding
        vat_after_withholding_vef = vat_billed_vef - vat_withholding_vef
        ganancia_val = flt(ganancia_by_branch.get(b_name, 0.0))
        perdida_val = flt(perdida_by_branch.get(b_name, 0.0))
        ganancia_vef = flt(ganancia_vef_by_branch.get(b_name, 0.0))
        perdida_vef = flt(perdida_vef_by_branch.get(b_name, 0.0))
        # Disponibilidad incluye el diferencial cambiario, igual que el ISP:
        # (Facturado - IVA) - Ret. ISLR - Pérdida + Ganancia.
        availability = (billed - vat_billed) - islr_withholding - perdida_val + ganancia_val
        availability_vef = (billed_vef - vat_billed_vef) - islr_withholding_vef - perdida_vef + ganancia_vef
        igtf_val = flt(igtf_by_branch.get(b_name, 0.0))
        igtf_vef = flt(igtf_vef_by_branch.get(b_name, 0.0))
        spent = flt(expenses_by_branch.get(b_name, 0.0)) if b_name != "Sin Sucursal" else 0.0
        spent_vef = flt(expenses_vef_by_branch.get(b_name, 0.0)) if b_name != "Sin Sucursal" else 0.0
        profit = availability - spent
        profit_vef = availability_vef - spent_vef

        branch_data_map[b_name] = {
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
            "profit": profit,
            "pending_to_collect_vef": pending_to_collect_vef,
            "payment_order_vef": payment_order_vef,
            "payment_order_vat_vef": payment_order_vat_vef,
            "billed_vef": billed_vef,
            "vat_vef": vat_billed_vef,
            "vat_after_withholding_vef": vat_after_withholding_vef,
            "vat_withholding_vef": vat_withholding_vef,
            "islr_withholding_vef": islr_withholding_vef,
            "igtf_vef": igtf_vef,
            "ganancia_vef": ganancia_vef,
            "perdida_vef": perdida_vef,
            "availability_vef": availability_vef,
            "spent_vef": spent_vef,
            "profit_vef": profit_vef
        }

    # Consolidar en árbol jerárquico (padre = propio + descendientes), respetando permisos.
    branch_financial_summary = _build_branch_tree(branch_data_map, all_ve_branches, allowed_set, branch)
    # "Sin Sucursal" (facturas sin branch) va como fila aparte al final, si tiene data.
    sin = branch_data_map.get("Sin Sucursal")
    if sin and any(flt(sin.get(k, 0)) for k in _TREE_FIELDS):
        branch_financial_summary.append({**sin, "indent": 0, "is_group": False})

    # Group invoices by customer in memory
    customer_data_map = {}
    for inv in all_invoices:
        cust = inv.customer or "Sin Cliente"
        cust_name = inv.customer_name or cust
        if cust not in customer_data_map:
            customer_data_map[cust] = {
                "customer": cust,
                "customer_name": cust_name,
                "pending_to_collect": 0.0,
                "payment_order": 0.0,
                "payment_order_vat": 0.0,
                "billed": 0.0,
                "vat": 0.0,
                "vat_after_withholding": 0.0,
                "vat_withholding": 0.0,
                "islr_withholding": 0.0,
                "availability": 0.0,
                "pending_to_collect_vef": 0.0,
                "payment_order_vef": 0.0,
                "payment_order_vat_vef": 0.0,
                "billed_vef": 0.0,
                "vat_vef": 0.0,
                "vat_after_withholding_vef": 0.0,
                "vat_withholding_vef": 0.0,
                "islr_withholding_vef": 0.0,
                "availability_vef": 0.0,
            }

        is_usd = (inv.currency == "USD")
        rate = 1.0 if is_usd else _get_cached_rate(str(inv.posting_date), rates_cache)

        inv_withholdings = withholdings_by_invoice.get(inv.name, {"vat": 0.0, "islr": 0.0, "vat_vef": 0.0, "islr_vef": 0.0})
        raw_vat_withholding = inv_withholdings["vat"]
        raw_islr_withholding = inv_withholdings["islr"]
        raw_gross_iva = iva_by_invoice.get(inv.name, 0.0)

        base_usd = flt(inv.net_total) if is_usd else flt(inv.net_total) / rate
        tax_usd = flt(raw_gross_iva) if is_usd else flt(raw_gross_iva) / rate
        g_total_usd = base_usd + tax_usd
        ret_iva_usd = flt(raw_vat_withholding) if is_usd else flt(raw_vat_withholding) / rate
        ret_islr_usd = flt(raw_islr_withholding) if is_usd else flt(raw_islr_withholding) / rate

        base_vef = flt(inv.base_net_total)
        tax_vef = flt(iva_vef_by_invoice.get(inv.name, 0.0))
        g_total_vef = base_vef + tax_vef
        ret_iva_vef = flt(inv_withholdings["vat_vef"])
        ret_islr_vef = flt(inv_withholdings["islr_vef"])

        row = customer_data_map[cust]
        row["payment_order"] += g_total_usd
        row["payment_order_vat"] += tax_usd
        row["payment_order_vef"] += g_total_vef
        row["payment_order_vat_vef"] += tax_vef

        has_control = (inv.docstatus == 1 and inv.bill_control is not None and str(inv.bill_control).strip() != "")
        no_control = (inv.bill_control is None or str(inv.bill_control).strip() == "")
        if has_control:
            row["billed"] += g_total_usd
            row["vat"] += tax_usd
            row["vat_withholding"] += ret_iva_usd
            row["islr_withholding"] += ret_islr_usd
            row["billed_vef"] += g_total_vef
            row["vat_vef"] += tax_vef
            row["vat_withholding_vef"] += ret_iva_vef
            row["islr_withholding_vef"] += ret_islr_vef
        elif no_control:
            row["pending_to_collect"] += g_total_usd
            row["pending_to_collect_vef"] += g_total_vef

    for cust, row in customer_data_map.items():
        row["vat_after_withholding"] = row["vat"] - row["vat_withholding"]
        row["vat_after_withholding_vef"] = row["vat_vef"] - row["vat_withholding_vef"]
        row["availability"] = (row["billed"] - row["vat"]) - row["islr_withholding"]
        row["availability_vef"] = (row["billed_vef"] - row["vat_vef"]) - row["islr_withholding_vef"]

    customer_financial_summary = sorted(
        customer_data_map.values(),
        key=lambda x: x["payment_order"],
        reverse=True
    )

    real_kpis = calculate_real_kpis(company, from_date, to_date, branch=branch, exchange_rate=rate_today)

    return {
        "sales_count": sales_count,
        "exchange_rate": rate_today,
        "branch_financial_summary": branch_financial_summary,
        "customer_financial_summary": customer_financial_summary,
        "real_kpis": real_kpis
    }


def format_currency_ve_py(val, currency="USD"):
    symbol = "REF " if currency == "USD" else "Bs. "
    try:
        val_str = "{:,.2f}".format(flt(val))
        parts = val_str.split('.')
        integer_part = parts[0].replace(',', '.')
        decimal_part = parts[1]
        return f"{symbol}{integer_part},{decimal_part}"
    except Exception:
        return f"{symbol}{flt(val):.2f}"


def _draw_excel_card(ws, start_col, start_row, label, usd_val, vef_val, accent_color, is_qty=False):
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    end_col = start_col + 4
    end_row = start_row + 2
    
    thin_border_side = Side(style='thin', color="CBD5E1")
    thick_top_side = Side(style='medium', color=accent_color)
    
    card_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    
    label_font = Font(name="Segoe UI", size=8.5, bold=True, color=accent_color)
    val_font = Font(name="Segoe UI", size=13.5, bold=True, color="0F172A")
    sub_font = Font(name="Segoe UI", size=9, italic=True, color="64748B")
    
    align_center = Alignment(horizontal="center", vertical="center")
    
    # Merge cells for each row inside the card
    ws.merge_cells(start_row=start_row, start_column=start_col, end_row=start_row, end_column=end_col)
    lbl_cell = ws.cell(row=start_row, column=start_col, value=label.upper())
    lbl_cell.font = label_font
    lbl_cell.alignment = align_center
    
    ws.merge_cells(start_row=start_row+1, start_column=start_col, end_row=start_row+1, end_column=end_col)
    val_cell = ws.cell(row=start_row+1, column=start_col, value=usd_val)
    val_cell.font = val_font
    val_cell.alignment = align_center
    if is_qty:
        val_cell.number_format = '#,##0'
    else:
        val_cell.number_format = '"REF "#,##0.00;("REF "#,##0.00);"-"'
        
    ws.merge_cells(start_row=start_row+2, start_column=start_col, end_row=start_row+2, end_column=end_col)
    if is_qty:
        sub_cell = ws.cell(row=start_row+2, column=start_col, value="Facturas del período")
        sub_cell.font = sub_font
        sub_cell.alignment = align_center
    else:
        sub_cell = ws.cell(row=start_row+2, column=start_col, value=vef_val)
        sub_cell.font = sub_font
        sub_cell.alignment = align_center
        sub_cell.number_format = '"Bs. "#,##0.00;("Bs. "#,##0.00);"-"'
        
    for r in range(start_row, start_row + 3):
        for c in range(start_col, start_col + 5):
            cell = ws.cell(row=r, column=c)
            cell.fill = card_fill
            
            border_kwargs = {}
            if c == start_col:
                border_kwargs["left"] = thin_border_side
            if c == end_col:
                border_kwargs["right"] = thin_border_side
            if r == start_row:
                border_kwargs["top"] = thick_top_side
            if r == end_row:
                border_kwargs["bottom"] = thin_border_side
                
            cell.border = Border(**border_kwargs)



def _get_company_details(company_name):
    if not company_name:
        return {"name": "EMPRESA", "tax_id": "", "address": ""}
    company_doc = frappe.get_cached_doc("Company", company_name)
    company_doc.check_permission("read")
    company_tax_id = company_doc.get("tax_id") or ""
    company_address = ""
    if company_doc.get("custom_company_primary_address"):
        try:
            address_doc = frappe.get_cached_doc("Address", company_doc.get("custom_company_primary_address"))
            company_address = address_doc.address_line1
        except Exception:
            pass
    return {"name": company_name, "tax_id": company_tax_id, "address": company_address}


@frappe.whitelist()
def download_pdf(company, from_date, to_date, branch=None, cost_center=None, customer=None):
    # Validar permiso de lectura sobre el reporte antes de exponer datos financieros
    frappe.get_doc("Reporte Gerencial").check_permission("read")
    from l10n_ve.utils.pdf_utils import safe_get_pdf
    from frappe.utils import formatdate, nowdate
    
    data = get_dashboard_data(company, from_date, to_date, branch, cost_center, customer)
    rate_today = data.get("exchange_rate", 1.0)
    company_details = _get_company_details(company)
    
    summary_data = []
    t_cobrar = t_op = t_iva_op = t_fact = t_iva = t_neto = t_ret_iva = t_ret_islr = t_igtf = t_disp = t_spent = t_util = 0.0
    v_cobrar = v_op = v_iva_op = v_fact = v_iva = v_neto = v_ret_iva = v_ret_islr = v_igtf = v_disp = v_spent = v_util = 0.0
    
    for r in data.get("branch_financial_summary") or []:
        if flt(r.get("indent", 0)) == 0.0:
            t_cobrar += flt(r.get("pending_to_collect", 0))
            v_cobrar += flt(r.get("pending_to_collect_vef", 0))
            t_op += flt(r.get("payment_order", 0))
            v_op += flt(r.get("payment_order_vef", 0))
            t_iva_op += flt(r.get("payment_order_vat", 0))
            v_iva_op += flt(r.get("payment_order_vat_vef", 0))
            t_fact += flt(r.get("billed", 0))
            v_fact += flt(r.get("billed_vef", 0))
            t_iva += flt(r.get("vat", 0))
            v_iva += flt(r.get("vat_vef", 0))
            t_neto += flt(r.get("vat_after_withholding", 0))
            v_neto += flt(r.get("vat_after_withholding_vef", 0))
            t_ret_iva += flt(r.get("vat_withholding", 0))
            v_ret_iva += flt(r.get("vat_withholding_vef", 0))
            t_ret_islr += flt(r.get("islr_withholding", 0))
            v_ret_islr += flt(r.get("islr_withholding_vef", 0))
            t_igtf += flt(r.get("igtf", 0))
            v_igtf += flt(r.get("igtf_vef", 0))
            t_disp += flt(r.get("availability", 0))
            v_disp += flt(r.get("availability_vef", 0))
            t_spent += flt(r.get("spent", 0))
            v_spent += flt(r.get("spent_vef", 0))
            t_util += flt(r.get("profit", 0))
            v_util += flt(r.get("profit_vef", 0))

        summary_data.append({
            "branch": r.get("branch"),
            "indent": r.get("indent", 0),
            "is_group": r.get("is_group", False),
            "is_total": False,
            "availability": r.get("availability", 0),
            "profit": r.get("profit", 0),
            "pending_to_collect_f": format_currency_ve_py(r.get("pending_to_collect", 0), "USD"),
            "pending_to_collect_vef_f": format_currency_ve_py(r.get("pending_to_collect_vef", 0), "VEF"),
            "payment_order_f": format_currency_ve_py(r.get("payment_order", 0), "USD"),
            "payment_order_vef_f": format_currency_ve_py(r.get("payment_order_vef", 0), "VEF"),
            "payment_order_vat_f": format_currency_ve_py(r.get("payment_order_vat", 0), "USD"),
            "payment_order_vat_vef_f": format_currency_ve_py(r.get("payment_order_vat_vef", 0), "VEF"),
            "billed_f": format_currency_ve_py(r.get("billed", 0), "USD"),
            "billed_vef_f": format_currency_ve_py(r.get("billed_vef", 0), "VEF"),
            "vat_f": format_currency_ve_py(r.get("vat", 0), "USD"),
            "vat_vef_f": format_currency_ve_py(r.get("vat_vef", 0), "VEF"),
            "vat_after_withholding_f": format_currency_ve_py(r.get("vat_after_withholding", 0), "USD"),
            "vat_after_withholding_vef_f": format_currency_ve_py(r.get("vat_after_withholding_vef", 0), "VEF"),
            "vat_withholding_f": format_currency_ve_py(r.get("vat_withholding", 0), "USD"),
            "vat_withholding_vef_f": format_currency_ve_py(r.get("vat_withholding_vef", 0), "VEF"),
            "islr_withholding_f": format_currency_ve_py(r.get("islr_withholding", 0), "USD"),
            "islr_withholding_vef_f": format_currency_ve_py(r.get("islr_withholding_vef", 0), "VEF"),
            "igtf_f": format_currency_ve_py(r.get("igtf", 0), "USD"),
            "igtf_vef_f": format_currency_ve_py(r.get("igtf_vef", 0), "VEF"),
            "availability_f": format_currency_ve_py(r.get("availability", 0), "USD"),
            "availability_vef_f": format_currency_ve_py(r.get("availability_vef", 0), "VEF"),
            "spent_f": format_currency_ve_py(r.get("spent", 0), "USD"),
            "spent_vef_f": format_currency_ve_py(r.get("spent_vef", 0), "VEF"),
            "profit_f": format_currency_ve_py(r.get("profit", 0), "USD"),
            "profit_vef_f": format_currency_ve_py(r.get("profit_vef", 0), "VEF"),
        })

    summary_data.append({
        "branch": "TOTAL",
        "indent": 0,
        "is_group": False,
        "is_total": True,
        "availability": t_disp,
        "profit": t_util,
        "pending_to_collect_f": format_currency_ve_py(t_cobrar, "USD"),
        "pending_to_collect_vef_f": format_currency_ve_py(v_cobrar, "VEF"),
        "payment_order_f": format_currency_ve_py(t_op, "USD"),
        "payment_order_vef_f": format_currency_ve_py(v_op, "VEF"),
        "payment_order_vat_f": format_currency_ve_py(t_iva_op, "USD"),
        "payment_order_vat_vef_f": format_currency_ve_py(v_iva_op, "VEF"),
        "billed_f": format_currency_ve_py(t_fact, "USD"),
        "billed_vef_f": format_currency_ve_py(v_fact, "VEF"),
        "vat_f": format_currency_ve_py(t_iva, "USD"),
        "vat_vef_f": format_currency_ve_py(v_iva, "VEF"),
        "vat_after_withholding_f": format_currency_ve_py(t_neto, "USD"),
        "vat_after_withholding_vef_f": format_currency_ve_py(v_neto, "VEF"),
        "vat_withholding_f": format_currency_ve_py(t_ret_iva, "USD"),
        "vat_withholding_vef_f": format_currency_ve_py(v_ret_iva, "VEF"),
        "islr_withholding_f": format_currency_ve_py(t_ret_islr, "USD"),
        "islr_withholding_vef_f": format_currency_ve_py(v_ret_islr, "VEF"),
        "igtf_f": format_currency_ve_py(t_igtf, "USD"),
        "igtf_vef_f": format_currency_ve_py(v_igtf, "VEF"),
        "availability_f": format_currency_ve_py(t_disp, "USD"),
        "availability_vef_f": format_currency_ve_py(v_disp, "VEF"),
        "spent_f": format_currency_ve_py(t_spent, "USD"),
        "spent_vef_f": format_currency_ve_py(v_spent, "VEF"),
        "profit_f": format_currency_ve_py(t_util, "USD"),
        "profit_vef_f": format_currency_ve_py(v_util, "VEF"),
    })

    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 7.5pt; margin: 0; color: #1e293b; }
            .header-container { margin-bottom: 15px; }
            .company-name { font-size: 13pt; font-weight: bold; color: #0f172a; text-transform: uppercase; }
            .company-info { font-size: 8.5pt; color: #475569; margin-top: 3px; }
            .title-banner { background-color: #0f172a; color: #ffffff; text-align: center; font-weight: bold; padding: 8px; margin: 15px 0; font-size: 11pt; border-radius: 4px; letter-spacing: 0.5px; }
            .filters-banner { font-size: 8.5pt; color: #1e293b; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 12px; margin-bottom: 15px; }
            .filter-item { display: inline-block; margin-right: 20px; }
            .filter-item strong { color: #475569; }
            
            /* Mini cards layout */
            .cards-container { display: table; width: 100%; table-layout: fixed; margin-bottom: 15px; }
            .cards-row { display: table-row; }
            .card-cell { display: table-cell; padding: 4px; }
            .mini-card { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; text-align: left; }
            .mini-card-label { font-size: 6.5pt; text-transform: uppercase; font-weight: bold; color: #64748b; margin-bottom: 2px; }
            .mini-card-value { font-size: 10.5pt; font-weight: bold; color: #0f172a; }
            .mini-card-subtext { font-size: 7.5pt; color: #64748b; margin-top: 1px; }
            
            table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 7pt; }
            th, td { border: 1px solid #cbd5e1; padding: 6px 4px; vertical-align: middle; }
            th { background-color: #0f172a; color: #ffffff; font-weight: bold; text-align: center; text-transform: uppercase; font-size: 6.5pt; letter-spacing: 0.5px; }
            .branch-col { font-weight: 600; text-align: left; }
            .text-right { text-align: right; }
            .text-center { text-align: center; }
            
            .row-even { background-color: #ffffff; }
            .row-odd { background-color: #f8fafc; }
            .row-group { font-weight: bold; background-color: #f1f5f9; }
            .row-total { background-color: #e2e8f0; font-weight: bold; border-top: 2px solid #0f172a; border-bottom: 2px double #0f172a; color: #0f172a; }
            
            .currency-usd { font-weight: 600; color: #1e293b; }
            .currency-vef { font-size: 6.5pt; color: #64748b; margin-top: 2px; }
        </style>
    </head>
    <body>
        <div class="header-container">
            <div class="company-name">{{ company_name }}</div>
            <div class="company-info">R.I.F.: {{ company_tax_id }} | Dirección: {{ company_address }}</div>
            <div class="company-info">Fecha de Emisión: {{ print_date }}</div>
        </div>

        <div class="title-banner">DASHBOARD GERENCIAL - RESUMEN FINANCIERO</div>

        <div class="filters-banner">
            <div class="filter-item"><strong>Periodo:</strong> Desde {{ from_date }} Hasta {{ to_date }}</div>
            {% if branch %}
            <div class="filter-item"><strong>Sucursal:</strong> {{ branch }}</div>
            {% endif %}
            {% if cost_center %}
            <div class="filter-item"><strong>Centro de Costo:</strong> {{ cost_center }}</div>
            {% endif %}
        </div>

        <!-- Mini tarjetas de Resumen -->
        <div class="cards-container">
            <div class="cards-row">
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #8b5cf6;">
                        <div class="mini-card-label">Cantidad de Ventas</div>
                        <div class="mini-card-value">{{ sales_count }}</div>
                        <div class="mini-card-subtext">&nbsp;</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #64748b;">
                        <div class="mini-card-label">Por Cobrar</div>
                        <div class="mini-card-value">{{ t_cobrar_f }}</div>
                        <div class="mini-card-subtext">{{ t_cobrar_vef_f }}</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #06b6d4;">
                        <div class="mini-card-label">Facturado</div>
                        <div class="mini-card-value">{{ t_fact_f }}</div>
                        <div class="mini-card-subtext">{{ t_fact_vef_f }}</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #f97316;">
                        <div class="mini-card-label">IVA</div>
                        <div class="mini-card-value">{{ t_iva_f }}</div>
                        <div class="mini-card-subtext">{{ t_iva_vef_f }}</div>
                    </div>
                </div>
            </div>
            <div style="height: 6px;"></div>
            <div class="cards-row">
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #ef4444;">
                        <div class="mini-card-label">IGTF</div>
                        <div class="mini-card-value">{{ t_igtf_f }}</div>
                        <div class="mini-card-subtext">{{ t_igtf_vef_f }}</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #10b981;">
                        <div class="mini-card-label">Disponibilidad</div>
                        <div class="mini-card-value" style="color: {% if t_disp >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ t_disp_f }}</div>
                        <div class="mini-card-subtext" style="color: {% if t_disp >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ t_disp_vef_f }}</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #ec4899;">
                        <div class="mini-card-label">Gastos</div>
                        <div class="mini-card-value" style="color: #dc2626;">{{ t_spent_f }}</div>
                        <div class="mini-card-subtext" style="color: #dc2626;">{{ t_spent_vef_f }}</div>
                    </div>
                </div>
                <div class="card-cell">
                    <div class="mini-card" style="border-top: 3px solid #059669;">
                        <div class="mini-card-label">Utilidad</div>
                        <div class="mini-card-value" style="color: {% if t_util >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ t_util_f }}</div>
                        <div class="mini-card-subtext" style="color: {% if t_util >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ t_util_vef_f }}</div>
                    </div>
                </div>
            </div>
        </div>

        <div style="font-size: 9pt; font-weight: bold; color: #0f172a; margin-top: 15px; margin-bottom: 5px; text-transform: uppercase; border-bottom: 1px solid #cbd5e1; padding-bottom: 3px;">
            Resumen Financiero por Sucursal
        </div>

        <table>
            <thead>
                <tr>
                    <th style="width: 13%;">Sucursal</th>
                    <th style="width: 7.2%;">Por Cobrar</th>
                    <th style="width: 7.2%;">Orden de Pago</th>
                    <th style="width: 7.2%;">IVA Orden Pago</th>
                    <th style="width: 7.2%;">Facturado</th>
                    <th style="width: 7.2%;">IVA</th>
                    <th style="width: 7.2%;">IVA desp. Ret.</th>
                    <th style="width: 7.2%;">Ret. IVA</th>
                    <th style="width: 7.2%;">Ret. ISLR</th>
                    <th style="width: 7.2%;">IGTF</th>
                    <th style="width: 7.2%;">Disponibilidad</th>
                    <th style="width: 7.2%;">Gastos</th>
                    <th style="width: 7.2%;">Utilidad</th>
                </tr>
            </thead>
            <tbody>
                {% for r in summary %}
                <tr class="{% if r.is_total %}row-total{% elif r.is_group %}row-group{% else %}{{ loop.cycle('row-even', 'row-odd') }}{% endif %}">
                    <td class="branch-col">
                        {% if r.indent > 0 %}
                            {% for i in range(r.indent) %}&nbsp;&nbsp;&nbsp;&nbsp;{% endfor %}
                        {% endif %}
                        {{ r.branch }}
                    </td>
                    <td class="text-right">
                        <div class="currency-usd">{{ r.pending_to_collect_f }}</div>
                        <div class="currency-vef">{{ r.pending_to_collect_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: #2563eb;">
                        <div class="currency-usd" style="color: #2563eb;">{{ r.payment_order_f }}</div>
                        <div class="currency-vef">{{ r.payment_order_vef_f }}</div>
                    </td>
                    <td class="text-right">
                        <div class="currency-usd">{{ r.payment_order_vat_f }}</div>
                        <div class="currency-vef">{{ r.payment_order_vat_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: #2563eb;">
                        <div class="currency-usd" style="color: #2563eb;">{{ r.billed_f }}</div>
                        <div class="currency-vef">{{ r.billed_vef_f }}</div>
                    </td>
                    <td class="text-right">
                        <div class="currency-usd">{{ r.vat_f }}</div>
                        <div class="currency-vef">{{ r.vat_vef_f }}</div>
                    </td>
                    <td class="text-right">
                        <div class="currency-usd">{{ r.vat_after_withholding_f }}</div>
                        <div class="currency-vef">{{ r.vat_after_withholding_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: #7c3aed;">
                        <div class="currency-usd" style="color: #7c3aed;">{{ r.vat_withholding_f }}</div>
                        <div class="currency-vef">{{ r.vat_withholding_vef_f }}</div>
                    </td>
                    <td class="text-right">
                        <div class="currency-usd">{{ r.islr_withholding_f }}</div>
                        <div class="currency-vef">{{ r.islr_withholding_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: #dc2626;">
                        <div class="currency-usd" style="color: #dc2626;">{{ r.igtf_f }}</div>
                        <div class="currency-vef">{{ r.igtf_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: {% if r.availability >= 0 %}#059669{% else %}#dc2626{% endif %}; font-weight: bold;">
                        <div class="currency-usd" style="color: {% if r.availability >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ r.availability_f }}</div>
                        <div class="currency-vef">{{ r.availability_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: #dc2626;">
                        <div class="currency-usd" style="color: #dc2626;">{{ r.spent_f }}</div>
                        <div class="currency-vef">{{ r.spent_vef_f }}</div>
                    </td>
                    <td class="text-right" style="color: {% if r.profit >= 0 %}#059669{% else %}#dc2626{% endif %}; font-weight: bold;">
                        <div class="currency-usd" style="color: {% if r.profit >= 0 %}#059669{% else %}#dc2626{% endif %};">{{ r.profit_f }}</div>
                        <div class="currency-vef">{{ r.profit_vef_f }}</div>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </body>
    </html>
    """
    
    context = {
        "company_name": company_details.get("name"),
        "company_tax_id": company_details.get("tax_id"),
        "company_address": company_details.get("address"),
        "print_date": formatdate(nowdate()),
        "from_date": formatdate(from_date),
        "to_date": formatdate(to_date),
        "exchange_rate_f": format_currency_ve_py(rate_today, "VEF"),
        "branch": branch,
        "cost_center": cost_center,
        "summary": summary_data,
        "sales_count": data.get("sales_count", 0),
        "t_cobrar": t_cobrar,
        "t_cobrar_f": format_currency_ve_py(t_cobrar, "USD"),
        "t_cobrar_vef_f": format_currency_ve_py(v_cobrar, "VEF"),
        "t_fact": t_fact,
        "t_fact_f": format_currency_ve_py(t_fact, "USD"),
        "t_fact_vef_f": format_currency_ve_py(v_fact, "VEF"),
        "t_iva": t_iva,
        "t_iva_f": format_currency_ve_py(t_iva, "USD"),
        "t_iva_vef_f": format_currency_ve_py(v_iva, "VEF"),
        "t_igtf": t_igtf,
        "t_igtf_f": format_currency_ve_py(t_igtf, "USD"),
        "t_igtf_vef_f": format_currency_ve_py(v_igtf, "VEF"),
        "t_disp": t_disp,
        "t_disp_f": format_currency_ve_py(t_disp, "USD"),
        "t_disp_vef_f": format_currency_ve_py(v_disp, "VEF"),
        "t_spent": t_spent,
        "t_spent_f": format_currency_ve_py(t_spent, "USD"),
        "t_spent_vef_f": format_currency_ve_py(v_spent, "VEF"),
        "t_util": t_util,
        "t_util_f": format_currency_ve_py(t_util, "USD"),
        "t_util_vef_f": format_currency_ve_py(v_util, "VEF")
    }
    
    final_html = frappe.render_template(html_template, context)
    pdf_content = safe_get_pdf(final_html, {"orientation": "Landscape"})
    
    frappe.local.response.filename = f"Reporte_Gerencial_{nowdate()}.pdf"
    frappe.local.response.filecontent = pdf_content
    frappe.local.response.type = "download"


@frappe.whitelist()
def download_excel(company, from_date, to_date, branch=None, cost_center=None, customer=None):
    # Validar permiso de lectura sobre el reporte antes de exponer datos financieros
    frappe.get_doc("Reporte Gerencial").check_permission("read")
    import io
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    from frappe.utils import formatdate, nowdate
    
    data = get_dashboard_data(company, from_date, to_date, branch, cost_center, customer)
    company_details = _get_company_details(company)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumen Financiero"
    
    ws.views.sheetView[0].showGridLines = True
    
    font_family = "Segoe UI"
    
    title_font = Font(name=font_family, size=15, bold=True, color="0F172A")
    subtitle_font = Font(name=font_family, size=9.5, italic=True, color="475569")
    filter_val_font = Font(name=font_family, size=9, italic=True, color="1E293B")
    
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    
    data_font = Font(name=font_family, size=10, color="1E293B")
    group_font = Font(name=font_family, size=10, bold=True, color="0F172A")
    total_font = Font(name=font_family, size=10, bold=True, color="0F172A")
    
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    group_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    
    thin_grid = Side(style='thin', color="E2E8F0")
    thin_accent = Side(style='thin', color="475569")
    double_accent = Side(style='double', color="0F172A")
    
    data_border = Border(left=thin_grid, right=thin_grid, top=thin_grid, bottom=thin_grid)
    total_border = Border(left=thin_grid, right=thin_grid, top=thin_accent, bottom=double_accent)
    
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")
    
    ws.cell(row=1, column=1).value = company_details.get("name").upper()
    ws.cell(row=1, column=1).font = title_font
    ws.row_dimensions[1].height = 24
    
    generated_on = frappe.utils.now_datetime().strftime("%Y-%m-%d %H:%M:%S")
    ws.cell(row=2, column=1).value = f"Reporte Gerencial - Resumen Financiero por Sucursal | Generado: {generated_on}"
    ws.cell(row=2, column=1).font = subtitle_font
    ws.row_dimensions[2].height = 16
    
    filters_text = f"Periodo: Desde {formatdate(from_date)} Hasta {formatdate(to_date)}"
    if branch:
        filters_text += f" | Sucursal: {branch}"
    if cost_center:
        filters_text += f" | Centro de Costo: {cost_center}"
    ws.cell(row=3, column=1).value = filters_text
    ws.cell(row=3, column=1).font = filter_val_font
    ws.row_dimensions[3].height = 18
    
    for c in range(1, 26):
        ws.cell(row=4, column=c).border = Border(bottom=thin_accent)
    ws.row_dimensions[4].height = 10
    
    # Pre-calcular totales de branches raíz (indent == 0) para las tarjetas y fila final
    t_cobrar = t_op = t_iva_op = t_fact = t_iva = t_neto = t_ret_iva = t_ret_islr = t_igtf = t_disp = t_spent = t_util = 0.0
    v_cobrar = v_op = v_iva_op = v_fact = v_iva = v_neto = v_ret_iva = v_ret_islr = v_igtf = v_disp = v_spent = v_util = 0.0
    for r in data.get("branch_financial_summary") or []:
        if flt(r.get("indent", 0)) == 0.0:
            t_cobrar += flt(r.get("pending_to_collect", 0))
            v_cobrar += flt(r.get("pending_to_collect_vef", 0))
            t_op += flt(r.get("payment_order", 0))
            v_op += flt(r.get("payment_order_vef", 0))
            t_iva_op += flt(r.get("payment_order_vat", 0))
            v_iva_op += flt(r.get("payment_order_vat_vef", 0))
            t_fact += flt(r.get("billed", 0))
            v_fact += flt(r.get("billed_vef", 0))
            t_iva += flt(r.get("vat", 0))
            v_iva += flt(r.get("vat_vef", 0))
            t_neto += flt(r.get("vat_after_withholding", 0))
            v_neto += flt(r.get("vat_after_withholding_vef", 0))
            t_ret_iva += flt(r.get("vat_withholding", 0))
            v_ret_iva += flt(r.get("vat_withholding_vef", 0))
            t_ret_islr += flt(r.get("islr_withholding", 0))
            v_ret_islr += flt(r.get("islr_withholding_vef", 0))
            t_igtf += flt(r.get("igtf", 0))
            v_igtf += flt(r.get("igtf_vef", 0))
            t_disp += flt(r.get("availability", 0))
            v_disp += flt(r.get("availability_vef", 0))
            t_spent += flt(r.get("spent", 0))
            v_spent += flt(r.get("spent_vef", 0))
            t_util += flt(r.get("profit", 0))
            v_util += flt(r.get("profit_vef", 0))
            
    # Dibujar mini tarjetas (2 filas de 4 tarjetas cada una)
    # Fila 1 de Tarjetas (Filas 5 a 7)
    # 1. Cantidad de ventas
    _draw_excel_card(ws, start_col=2, start_row=5, label="Cantidad de ventas", usd_val=data.get("sales_count", 0), vef_val=None, accent_color="8B5CF6", is_qty=True)
    # 2. Por cobrar
    _draw_excel_card(ws, start_col=8, start_row=5, label="Por cobrar", usd_val=t_cobrar, vef_val=v_cobrar, accent_color="64748B")
    # 3. Facturado
    _draw_excel_card(ws, start_col=14, start_row=5, label="Facturado", usd_val=t_fact, vef_val=v_fact, accent_color="06B6D4")
    # 4. IVA
    _draw_excel_card(ws, start_col=20, start_row=5, label="IVA", usd_val=t_iva, vef_val=v_iva, accent_color="F97316")
    
    ws.row_dimensions[5].height = 16
    ws.row_dimensions[6].height = 22
    ws.row_dimensions[7].height = 18
    
    # Separador (Fila 8)
    ws.row_dimensions[8].height = 10
    
    # Fila 2 de Tarjetas (Filas 9 a 11)
    # 5. IGTF
    _draw_excel_card(ws, start_col=2, start_row=9, label="IGTF", usd_val=t_igtf, vef_val=v_igtf, accent_color="EF4444")
    # 6. Disponibilidad
    _draw_excel_card(ws, start_col=8, start_row=9, label="Disponibilidad", usd_val=t_disp, vef_val=v_disp, accent_color="10B981")
    # 7. Gastos
    _draw_excel_card(ws, start_col=14, start_row=9, label="Gastos", usd_val=t_spent, vef_val=v_spent, accent_color="EC4899")
    # 8. Utilidad
    _draw_excel_card(ws, start_col=20, start_row=9, label="Utilidad", usd_val=t_util, vef_val=v_util, accent_color="059669")
    
    ws.row_dimensions[9].height = 16
    ws.row_dimensions[10].height = 22
    ws.row_dimensions[11].height = 18
    
    # Separador (Fila 12)
    ws.row_dimensions[12].height = 12
    
    # Título de Sección "Resumen Financiero por Sucursal" (Fila 13)
    ws.row_dimensions[13].height = 22
    ws.merge_cells(start_row=13, start_column=1, end_row=13, end_column=25)
    title_cell = ws.cell(row=13, column=1, value="RESUMEN FINANCIERO POR SUCURSAL")
    title_cell.font = Font(name=font_family, size=11, bold=True, color="0F172A")
    title_cell.alignment = align_left
    
    title_border_side = Side(style='thin', color="CBD5E1")
    for col_idx in range(1, 26):
        ws.cell(row=13, column=col_idx).border = Border(bottom=title_border_side)
        
    # Separador (Fila 14)
    ws.row_dimensions[14].height = 8
    
    headers = [
        "Sucursal",
        "Por cobrar (USD)", "Por cobrar (Bs.)",
        "Orden de Pago (USD)", "Orden de Pago (Bs.)",
        "IVA Orden de Pago (USD)", "IVA Orden de Pago (Bs.)",
        "Facturado (USD)", "Facturado (Bs.)",
        "IVA (USD)", "IVA (Bs.)",
        "IVA desp. Retención (USD)", "IVA desp. Retención (Bs.)",
        "Ret. IVA (USD)", "Ret. IVA (Bs.)",
        "Ret. ISLR (USD)", "Ret. ISLR (Bs.)",
        "IGTF (USD)", "IGTF (Bs.)",
        "Disponibilidad (USD)", "Disponibilidad (Bs.)",
        "Gastos (USD)", "Gastos (Bs.)",
        "Utilidad (USD)", "Utilidad (Bs.)"
    ]
    
    # Cabeceras de la tabla (Fila 15)
    ws.row_dimensions[15].height = 28
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=15, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = Border(left=thin_grid, right=thin_grid, top=thin_accent, bottom=thin_accent)
        
    row_num = 16
    for r in data.get("branch_financial_summary") or []:
        is_grp = r.get("is_group", False)
        indent = r.get("indent", 0)
        branch_name = "    " * indent + str(r.get("branch") or "")
        
        row_fill = group_fill if is_grp else (zebra_fill if row_num % 2 == 0 else PatternFill(fill_type=None))
        row_font = group_font if is_grp else data_font
        
        ws.row_dimensions[row_num].height = 20
        
        cell = ws.cell(row=row_num, column=1, value=branch_name)
        cell.font = row_font
        cell.alignment = align_left
        cell.border = data_border
        if row_fill.fill_type:
            cell.fill = row_fill
            
        col_vals = [
            r.get("pending_to_collect", 0), flt(r.get("pending_to_collect_vef", 0)),
            r.get("payment_order", 0), flt(r.get("payment_order_vef", 0)),
            r.get("payment_order_vat", 0), flt(r.get("payment_order_vat_vef", 0)),
            r.get("billed", 0), flt(r.get("billed_vef", 0)),
            r.get("vat", 0), flt(r.get("vat_vef", 0)),
            r.get("vat_after_withholding", 0), flt(r.get("vat_after_withholding_vef", 0)),
            r.get("vat_withholding", 0), flt(r.get("vat_withholding_vef", 0)),
            r.get("islr_withholding", 0), flt(r.get("islr_withholding_vef", 0)),
            r.get("igtf", 0), flt(r.get("igtf_vef", 0)),
            r.get("availability", 0), flt(r.get("availability_vef", 0)),
            r.get("spent", 0), flt(r.get("spent_vef", 0)),
            r.get("profit", 0), flt(r.get("profit_vef", 0)),
        ]
        
        for idx, val in enumerate(col_vals, 2):
            cell = ws.cell(row=row_num, column=idx, value=val)
            cell.font = row_font
            cell.alignment = align_right
            cell.border = data_border
            cell.number_format = '#,##0.00;(#,##0.00);"-"'
            if row_fill.fill_type:
                cell.fill = row_fill
                
        row_num += 1
        
    # Fila de TOTAL final
    ws.row_dimensions[row_num].height = 22
    cell = ws.cell(row=row_num, column=1, value="TOTAL")
    cell.font = total_font
    cell.alignment = align_left
    cell.border = total_border
    cell.fill = total_fill
    
    total_vals = [
        t_cobrar, v_cobrar,
        t_op, v_op,
        t_iva_op, v_iva_op,
        t_fact, v_fact,
        t_iva, v_iva,
        t_neto, v_neto,
        t_ret_iva, v_ret_iva,
        t_ret_islr, v_ret_islr,
        t_igtf, v_igtf,
        t_disp, v_disp,
        t_spent, v_spent,
        t_util, v_util,
    ]
    
    for idx, val in enumerate(total_vals, 2):
        cell = ws.cell(row=row_num, column=idx, value=val)
        cell.font = total_font
        cell.alignment = align_right
        cell.border = total_border
        cell.number_format = '#,##0.00;(#,##0.00);"-"'
        cell.fill = total_fill
        
    # Ajustar ancho de columnas escaneando desde la cabecera de la tabla (fila 15) en adelante
    for col_idx in range(1, 26):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for r in range(15, row_num + 1):
            cell_val = ws.cell(row=r, column=col_idx).value
            if cell_val is not None:
                val_str = f"{cell_val:,.2f}" if isinstance(cell_val, (int, float)) else str(cell_val)
                if len(val_str) > max_len:
                    max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)
        
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    content = out.read()
    
    frappe.local.response.filename = f"Reporte_Gerencial_{nowdate()}.xlsx"
    frappe.local.response.filecontent = content
    frappe.local.response.type = "binary"


@frappe.whitelist()
def get_customer_list(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
    frappe.get_doc("Reporte Gerencial").check_permission("read")
    if isinstance(filters, str):
        import json
        try:
            filters = json.loads(filters)
        except ValueError:
            filters = {}

    company = filters.get("company") if filters else None
    if not company:
        return []
    query = """
        SELECT DISTINCT customer, customer_name 
        FROM `tabSales Invoice` 
        WHERE company = %s AND docstatus != 2
    """
    params = [company]
    if txt:
        query += " AND (customer LIKE %s OR customer_name LIKE %s)"
        params.extend([f"%{txt}%", f"%{txt}%"])
    query += " LIMIT %s, %s"
    params.extend([int(start or 0), int(page_len or 20)])
    db_results = frappe.db.sql(query, params)
    return [{"value": r[0], "label": r[1] or r[0]} for r in db_results if r[0]]


def calculate_real_kpis(company, date_from, date_to, branch=None, exchange_rate=None, tree=None):
    from l10n_ve.utils.utils import get_exchange_rate
    from frappe.utils import flt

    if not exchange_rate:
        exchange_rate = flt(get_exchange_rate(date_to, "USD")) or 1.0

    # Calculate allowed branch universe (hierarchy)
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

    branch_list = list(universe) if universe is not None else None

    # 1. Real Collections from standard Payment Entry and Payment Entry Reference
    query = """
        select 
            pe.name,
            pe.paid_on_currency,
            pe.paid_currency_amount,
            pe.paid_amount as pe_paid_amount,
            pe.posting_date,
            ref.allocated_amount,
            pe.total_allocated_amount,
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
    if branch_list is not None:
        query += " and si.branch in %(branches)s"
        params["branches"] = branch_list or ["__no_access__"]

    res = frappe.db.sql(query, params, as_dict=True)

    rates_cache = {}
    def _local_get_cached_rate(d_str):
        if d_str not in rates_cache:
            rates_cache[d_str] = flt(get_exchange_rate(d_str, "USD")) or 1.0
        return rates_cache[d_str]

    collected_usd_total = 0.0
    collected_usd_base = 0.0
    collected_usd_tax = 0.0
    collected_usd_igtf = 0.0

    collected_ves_total = 0.0
    collected_ves_base = 0.0
    collected_ves_tax = 0.0
    collected_ves_igtf = 0.0
    collected_ves_equivalent_usd = 0.0

    for row in res:
        currency = row['paid_on_currency'] or 'VEF'
        pe_total_allocated = flt(row['total_allocated_amount'] or 0)
        allocated = flt(row['allocated_amount'] or 0)
        
        ratio = allocated / pe_total_allocated if pe_total_allocated > 0 else 1.0
        
        paid_currency_total = flt(row['paid_currency_amount'] or 0)
        paid_currency_ref = paid_currency_total * ratio
        paid_loc = allocated
        
        total_vef = flt(row['base_grand_total'] or 0)
        base_vef = flt(row['base_net_total'] or 0)
        iva_vef = flt(row['base_iva_amount'] or 0)
        igtf_vef = flt(row['total_igtf'] or 0)
        
        ratio_base = base_vef / total_vef if total_vef > 0 else 1.0
        ratio_tax = iva_vef / total_vef if total_vef > 0 else 0.0
        ratio_igtf = igtf_vef / total_vef if total_vef > 0 else 0.0
        
        if currency == 'USD':
            collected_usd_total += paid_currency_ref
            collected_usd_base += paid_currency_ref * ratio_base
            collected_usd_tax += paid_currency_ref * ratio_tax
            collected_usd_igtf += paid_currency_ref * ratio_igtf
            
            # Convert USD IGTF portion of the payment to VEF using payment posting date rate
            r_val = _local_get_cached_rate(str(row['posting_date']))
            collected_ves_igtf += (paid_currency_ref * ratio_igtf) * r_val
        elif currency in ('VEF', 'VES'):
            collected_ves_total += paid_loc
            collected_ves_base += paid_loc * ratio_base
            collected_ves_tax += paid_loc * ratio_tax
            collected_ves_igtf += paid_loc * ratio_igtf
            
            # Convert VEF payment to USD equivalent using exchange rate of payment date
            r_val = _local_get_cached_rate(str(row['posting_date']))
            collected_ves_equivalent_usd += paid_loc / r_val if r_val > 0 else 0.0

    # 2. Real Expenses paid in USD and VEF
    query_expenses = """
        select 
            spending_currency,
            sum(total_exchange) as total_usd,
            sum(total) as total_vef
        from `tabExpense`
        where docstatus = 1 and company = %(company)s and expense_date between %(date_from)s and %(date_to)s
    """
    params_exp = {"company": company, "date_from": date_from, "date_to": date_to}
    if branch_list is not None:
        query_expenses += " and branch in %(branches)s"
        params_exp["branches"] = branch_list or ["__no_access__"]
    query_expenses += " group by spending_currency"

    expenses_res = frappe.db.sql(query_expenses, params_exp, as_dict=True)
    real_spent_usd = 0.0
    real_spent_vef = 0.0
    for row in expenses_res:
        if row['spending_currency'] == 'USD':
            real_spent_usd += flt(row['total_usd'] or 0)
        elif row['spending_currency'] in ('VEF', 'VES'):
            real_spent_vef += flt(row['total_vef'] or 0)

    # 3. Real Withholdings from Sales Taxes and Charges (same pattern as get_dashboard_data)
    real_ret_iva_usd = 0.0
    real_ret_iva_vef = 0.0
    real_ret_islr_usd = 0.0
    real_ret_islr_vef = 0.0
    real_igtf_usd = 0.0
    real_igtf_vef = 0.0

    if tree:
        for node in tree:
            if node.get("indent") == 0:
                real_ret_iva_usd += flt(node.get("vat_withholding") or 0)
                real_ret_iva_vef += flt(node.get("vat_withholding_vef") or 0)
                real_ret_islr_usd += flt(node.get("islr_withholding") or 0)
                real_ret_islr_vef += flt(node.get("islr_withholding_vef") or 0)
                real_igtf_usd += flt(node.get("igtf") or 0)
                real_igtf_vef += flt(node.get("igtf_vef") or 0)
    else:
        # Fetch all invoices in range with GL entry movements (docstatus=1)
        query_invoices = """
            select name, posting_date, currency, total_igtf, base_amount_igtf
            from `tabSales Invoice`
            where docstatus = 1 and company = %(company)s
              and posting_date between %(date_from)s and %(date_to)s
        """
        params_inv = {"company": company, "date_from": date_from, "date_to": date_to}
        if branch_list is not None:
            query_invoices += " and branch in %(branches)s"
            params_inv["branches"] = branch_list or ["__no_access__"]

        invoices_list = frappe.db.sql(query_invoices, params_inv, as_dict=True)
        invoice_names = [x.name for x in invoices_list]

        if invoice_names:
            # IGTF: sum from Sales Invoice directly
            for inv in invoices_list:
                is_usd = (inv.currency == "USD")
                rate_val = flt(_local_get_cached_rate(str(inv.posting_date)))
                igtf_val = flt(inv.total_igtf)
                real_igtf_usd += igtf_val if is_usd else (igtf_val / rate_val if rate_val > 0 else 0.0)
                
                base_igtf = flt(inv.get("base_amount_igtf") or 0)
                if is_usd:
                    real_igtf_vef += base_igtf if base_igtf > 0 else (igtf_val * rate_val)
                else:
                    real_igtf_vef += igtf_val

            # Withholdings: from Sales Taxes and Charges (same as get_dashboard_data)
            taxes_raw = frappe.db.get_all(
                "Sales Taxes and Charges",
                filters={"parent": ["in", invoice_names], "is_tax_withholding_account": 1},
                fields=["parent", "account_head", "tax_amount", "base_tax_amount"]
            )
            inv_map = {x.name: x for x in invoices_list}
            for t in taxes_raw:
                inv_doc = inv_map.get(t.parent)
                if not inv_doc:
                    continue
                is_usd = (inv_doc.currency == "USD")
                rate_val = 1.0 if is_usd else _local_get_cached_rate(str(inv_doc.posting_date))

                ac_lower = str(t.account_head).lower()
                vat_v = flt(t.base_tax_amount)
                vat_usd = flt(t.tax_amount) if is_usd else vat_v / rate_val

                if "iva" in ac_lower:
                    real_ret_iva_vef += vat_v
                    real_ret_iva_usd += vat_usd
                elif "islr" in ac_lower:
                    real_ret_islr_vef += vat_v
                    real_ret_islr_usd += vat_usd

    # 4. Real Available
    available_usd = collected_usd_total - real_spent_usd
    available_vef = collected_ves_total - real_spent_vef

    # 5. Outstanding / Pending Invoices
    si_filters = {
        "docstatus": 1,
        "company": company,
        "posting_date": ["between", [date_from, date_to]]
    }

    if branch_list is not None:
        si_filters["branch"] = ["in", (branch_list or ["__no_access__"])]

    table_filters = dict(si_filters)
    table_filters["docstatus"] = ["!=", 2]
    all_invoices = frappe.get_all(
        "Sales Invoice",
        filters=table_filters,
        fields=["name", "base_net_total", "base_grand_total", "grand_total", "bill_control", "docstatus"]
    )

    total_pendiente_usd = 0.0
    total_pendiente_vef = 0.0
    for inv in all_invoices:
        no_control = (inv.bill_control is None or str(inv.bill_control).strip() == "")
        if no_control:
            g_total_usd = flt(inv.grand_total)
            g_total_vef = flt(inv.base_grand_total) if hasattr(inv, "base_grand_total") else (g_total_usd * exchange_rate)
            total_pendiente_usd += g_total_usd
            total_pendiente_vef += g_total_vef

    unpaid_count = sum(1 for inv in all_invoices if not inv.bill_control)

    return {
        "unpaid_orders_count": unpaid_count,
        "grand_total": total_pendiente_usd,
        "total_pendiente_usd": total_pendiente_usd,
        "total_pendiente_vef": total_pendiente_vef,
        "pending_base_amount": 0.0,
        "pending_tax_amount": 0.0,
        
        "actual_collected_total": collected_usd_total,
        
        "collected_usd_total": collected_usd_total,
        "collected_usd_base": collected_usd_base,
        "collected_usd_tax": collected_usd_tax,
        "collected_usd_igtf": collected_usd_igtf,
        
        "collected_ves_total": collected_ves_total,
        "collected_ves_base": collected_ves_base,
        "collected_ves_tax": collected_ves_tax,
        "collected_ves_igtf": collected_ves_igtf,
        "collected_ves_equivalent_usd": collected_ves_equivalent_usd,
        
        "total_expenses_usd": real_spent_usd,
        "total_expenses_vef": real_spent_vef,
        
        "collected_total_usd": collected_usd_total,
        "collected_total_vef": collected_ves_total,
        
        "available_usd": available_usd,
        "available_vef": available_vef,
        
        "ret_iva_usd": real_ret_iva_usd,
        "ret_iva_vef": real_ret_iva_vef,
        "ret_islr_usd": real_ret_islr_usd,
        "ret_islr_vef": real_ret_islr_vef,
        "igtf_total": collected_usd_igtf,
        "igtf_vef": collected_ves_igtf,
    }

