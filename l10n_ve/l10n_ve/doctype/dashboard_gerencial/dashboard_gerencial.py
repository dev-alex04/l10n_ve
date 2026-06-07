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


def _get_allowed_branches():
    """Sucursales permitidas para el usuario: None=todas (Administrator), []=sin
    acceso, [list]=permitidas. Basado en User Permission allow='VE Branch' + hijos."""
    user = frappe.session.user
    if user == "Administrator":
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
    if cost_center:
        si_filters["name"] = ["in", frappe.get_all("Sales Invoice Item", filters={"cost_center": cost_center}, pluck="parent")]

    # --- Permisos + universo de sucursales (árbol VE Branch, igual que el ISP) ---
    allowed = _get_allowed_branches()                 # None=todas, []=ninguna, [list]
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
    if frappe.db.exists("DocType", "Expense"):
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
        si_igtf = frappe.db.sql(f"""
            SELECT si.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabSales Invoice` si ON gle.voucher_no = si.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s{sql_branch_si}
        """, (tuple(accounts_igtf), from_date, to_date) + ((universe_param,) if universe is not None else ()), as_dict=True)

        # Group by branch for Payment Entry IGTF
        pe_igtf = frappe.db.sql(f"""
            SELECT pe.branch, gle.credit, gle.debit, gle.account_currency, gle.posting_date
            FROM `tabGL Entry` gle
            JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name
            WHERE gle.account IN %s AND gle.docstatus = 1 AND gle.posting_date BETWEEN %s AND %s{sql_branch_pe}
        """, (tuple(accounts_igtf), from_date, to_date) + ((universe_param,) if universe is not None else ()), as_dict=True)

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
    fx_params = {"company": company, "from_date": from_date, "to_date": to_date}
    if universe is not None:
        fx_params["branches"] = universe_param

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
        fields=["name", "net_total", "base_net_total", "grand_total", "total_taxes_and_charges", "bill_control", "currency", "posting_date", "branch", "docstatus"]
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

    return {
        "sales_count": sales_count,
        "exchange_rate": rate_today,
        "branch_financial_summary": branch_financial_summary
    }
