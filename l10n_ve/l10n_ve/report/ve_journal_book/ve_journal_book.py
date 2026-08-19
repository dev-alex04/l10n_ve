# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, formatdate
from l10n_ve.utils.accounting import get_hierarchical_balances
from l10n_ve.utils.utils import get_exchange_rate


def execute(filters=None):
    if not filters:
        filters = {}

    company = filters.get("company")
    if not company:
        return [], []

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")
    currency_filter = filters.get("currency_filter") or "VES"
    presentation = filters.get("presentation") or "Detallado"
    voucher_type = filters.get("voucher_type")
    account = filters.get("account")
    party_type = filters.get("party_type")
    party = filters.get("party")
    cost_center = filters.get("cost_center")
    include_cancelled = cint(filters.get("include_cancelled"))

    # Metadatos de la empresa para impresión y exportación
    company_name = frappe.db.get_value("Company", company, "company_name") or company
    company_rif = frappe.db.get_value("Company", company, "tax_id") or ""
    company_logo = frappe.db.get_value("Company", company, "company_logo") or ""

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

    currency_symbol = "Bs." if currency_filter == "VES" else ("$" if currency_filter == "USD" else "Bs. / $")

    # MODO JERÁRQUICO (1° Nivel a 4° Nivel)
    if presentation in ["1° Nivel", "2° Nivel", "3° Nivel", "4° Nivel"]:
        columns, data = get_hierarchical_data(
            company,
            from_date,
            to_date,
            currency_filter,
            presentation,
            cost_center,
            company_name,
            company_rif,
            company_address,
            company_logo,
            currency_symbol
        )
        return columns, data, None, None, None

    # MODO TRANSACCIONAL (Detallado o Resumido)
    columns = get_transactional_columns(currency_filter, presentation)
    data = get_transactional_data(
        company,
        from_date,
        to_date,
        currency_filter,
        presentation,
        voucher_type,
        account,
        party_type,
        party,
        cost_center,
        include_cancelled,
        company_name,
        company_rif,
        company_address,
        company_logo,
        currency_symbol
    )

    return columns, data, None, None, None


def get_hierarchical_data(
    company,
    from_date,
    to_date,
    currency_filter,
    presentation,
    cost_center,
    company_name,
    company_rif,
    company_address,
    company_logo,
    currency_symbol
):
    level_map = {
        "1° Nivel": 1,
        "2° Nivel": 2,
        "3° Nivel": 3,
        "4° Nivel": 4
    }
    max_level = level_map.get(presentation, 4)

    # Columnas según moneda
    columns = [
        {"fieldname": "account_number", "label": _("Código"), "fieldtype": "Data", "width": 130},
        {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Data", "width": 340}
    ]

    if currency_filter == "VES":
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (Bs.)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "credit", "label": _("Haber (Bs.)"), "fieldtype": "Currency", "width": 140}
        ])
    elif currency_filter == "USD":
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (USD)"), "fieldtype": "Currency", "width": 140},
            {"fieldname": "credit", "label": _("Haber (USD)"), "fieldtype": "Currency", "width": 140}
        ])
    else:  # Bimoneda
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (Bs.)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "credit", "label": _("Haber (Bs.)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "debit_usd", "label": _("Debe (USD)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "credit_usd", "label": _("Haber (USD)"), "fieldtype": "Currency", "width": 120}
        ])

    accounts_data = get_hierarchical_balances(company, to_date, from_date=from_date, cost_center=cost_center)
    if not accounts_data:
        return columns, []

    # Tasa promedio / actual para conversión en jerarquía si aplica
    rate = 1.0
    if currency_filter in ["USD", "Bimoneda"]:
        rate_date = to_date or from_date or frappe.utils.nowdate()
        rate = flt(get_exchange_rate(rate_date, "USD")) or 1.0

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

    filtered_accounts = []
    for acc in accounts_data:
        acc.depth = get_depth(acc.account)
        if acc.depth < max_level:
            filtered_accounts.append(acc)

    for acc in filtered_accounts:
        while stack and not is_descendant(acc, stack[-1]):
            closed = stack.pop()
            deb_v = flt(closed.debit)
            cred_v = flt(closed.credit)
            deb_u = round(deb_v / rate, 2) if rate > 0 else 0.0
            cred_u = round(cred_v / rate, 2) if rate > 0 else 0.0

            sub_row = {
                "account_number": "",
                "account": f"Total de {closed.account_number or ''} {closed.account_name}",
                "is_total": 1,
                "is_group_total": 1,
                "indent": closed.depth,
                "company_name": company_name,
                "company_rif": company_rif,
                "company_address": company_address,
                "company_logo": company_logo,
                "currency_filter": currency_filter,
                "currency_symbol": currency_symbol
            }
            if currency_filter == "VES":
                sub_row["debit"] = deb_v
                sub_row["credit"] = cred_v
            elif currency_filter == "USD":
                sub_row["debit"] = deb_u
                sub_row["credit"] = cred_u
            else:
                sub_row["debit"] = deb_v
                sub_row["credit"] = cred_v
                sub_row["debit_usd"] = deb_u
                sub_row["credit_usd"] = cred_u

            data.append(sub_row)

        if acc.depth < max_level - 1 and acc.is_group == 1:
            data.append({
                "account_number": acc.account_number or "",
                "account": acc.account_name,
                "debit": None,
                "credit": None,
                "debit_usd": None,
                "credit_usd": None,
                "is_group_header": 1,
                "indent": acc.depth,
                "company_name": company_name,
                "company_rif": company_rif,
                "company_address": company_address,
                "company_logo": company_logo,
                "currency_filter": currency_filter,
                "currency_symbol": currency_symbol
            })
            stack.append(acc)
        else:
            deb_v = flt(acc.debit)
            cred_v = flt(acc.credit)
            deb_u = round(deb_v / rate, 2) if rate > 0 else 0.0
            cred_u = round(cred_v / rate, 2) if rate > 0 else 0.0

            leaf_row = {
                "account_number": acc.account_number or "",
                "account": acc.account_name,
                "is_leaf": 1,
                "indent": acc.depth,
                "company_name": company_name,
                "company_rif": company_rif,
                "company_address": company_address,
                "company_logo": company_logo,
                "currency_filter": currency_filter,
                "currency_symbol": currency_symbol
            }
            if currency_filter == "VES":
                leaf_row["debit"] = deb_v
                leaf_row["credit"] = cred_v
            elif currency_filter == "USD":
                leaf_row["debit"] = deb_u
                leaf_row["credit"] = cred_u
            else:
                leaf_row["debit"] = deb_v
                leaf_row["credit"] = cred_v
                leaf_row["debit_usd"] = deb_u
                leaf_row["credit_usd"] = cred_u

            data.append(leaf_row)

    while stack:
        closed = stack.pop()
        deb_v = flt(closed.debit)
        cred_v = flt(closed.credit)
        deb_u = round(deb_v / rate, 2) if rate > 0 else 0.0
        cred_u = round(cred_v / rate, 2) if rate > 0 else 0.0

        sub_row = {
            "account_number": "",
            "account": f"Total de {closed.account_number or ''} {closed.account_name}",
            "is_total": 1,
            "is_group_total": 1,
            "indent": closed.depth,
            "company_name": company_name,
            "company_rif": company_rif,
            "company_address": company_address,
            "company_logo": company_logo,
            "currency_filter": currency_filter,
            "currency_symbol": currency_symbol
        }
        if currency_filter == "VES":
            sub_row["debit"] = deb_v
            sub_row["credit"] = cred_v
        elif currency_filter == "USD":
            sub_row["debit"] = deb_u
            sub_row["credit"] = cred_u
        else:
            sub_row["debit"] = deb_v
            sub_row["credit"] = cred_v
            sub_row["debit_usd"] = deb_u
            sub_row["credit_usd"] = cred_u

        data.append(sub_row)

    # Gran Total
    grand_deb_ves = sum(flt(acc.debit) for acc in accounts_data if get_depth(acc.account) == 0)
    grand_cred_ves = sum(flt(acc.credit) for acc in accounts_data if get_depth(acc.account) == 0)
    grand_deb_usd = round(grand_deb_ves / rate, 2) if rate > 0 else 0.0
    grand_cred_usd = round(grand_cred_ves / rate, 2) if rate > 0 else 0.0

    data.append({"account_number": "", "account": "", "debit": 0, "credit": 0, "is_spacer": 1})
    total_row = {
        "account_number": "",
        "account": _("TOTAL GENERAL LIBRO DIARIO"),
        "is_total": 1,
        "is_group": 1,
        "company_name": company_name,
        "company_rif": company_rif,
        "company_address": company_address,
        "company_logo": company_logo,
        "currency_filter": currency_filter,
        "currency_symbol": currency_symbol
    }
    if currency_filter == "VES":
        total_row["debit"] = grand_deb_ves
        total_row["credit"] = grand_cred_ves
    elif currency_filter == "USD":
        total_row["debit"] = grand_deb_usd
        total_row["credit"] = grand_cred_usd
    else:
        total_row["debit"] = grand_deb_ves
        total_row["credit"] = grand_cred_ves
        total_row["debit_usd"] = grand_deb_usd
        total_row["credit_usd"] = grand_cred_usd

    data.append(total_row)
    return columns, data


def get_transactional_columns(currency_filter, presentation):
    if presentation == "Resumido":
        columns = [
            {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 95},
            {"fieldname": "voucher_type", "label": _("Tipo"), "fieldtype": "Data", "width": 140},
            {"fieldname": "voucher_no", "label": _("Comprobante"), "fieldtype": "Data", "width": 150},
            {"fieldname": "display_ref", "label": _("Ref. Fiscal / Control"), "fieldtype": "Data", "width": 140},
            {"fieldname": "narration", "label": _("Descripción / Glosa"), "fieldtype": "Data", "width": 260}
        ]
        if currency_filter == "VES":
            columns.extend([
                {"fieldname": "debit", "label": _("Total Debe (Bs.)"), "fieldtype": "Currency", "width": 130},
                {"fieldname": "credit", "label": _("Total Haber (Bs.)"), "fieldtype": "Currency", "width": 130},
                {"fieldname": "difference", "label": _("Diferencia"), "fieldtype": "Currency", "width": 100}
            ])
        elif currency_filter == "USD":
            columns.extend([
                {"fieldname": "debit", "label": _("Total Debe (USD)"), "fieldtype": "Currency", "width": 130},
                {"fieldname": "credit", "label": _("Total Haber (USD)"), "fieldtype": "Currency", "width": 130},
                {"fieldname": "difference", "label": _("Diferencia"), "fieldtype": "Currency", "width": 100}
            ])
        else:  # Bimoneda
            columns.extend([
                {"fieldname": "debit", "label": _("Debe (Bs.)"), "fieldtype": "Currency", "width": 110},
                {"fieldname": "credit", "label": _("Haber (Bs.)"), "fieldtype": "Currency", "width": 110},
                {"fieldname": "debit_usd", "label": _("Debe (USD)"), "fieldtype": "Currency", "width": 110},
                {"fieldname": "credit_usd", "label": _("Haber (USD)"), "fieldtype": "Currency", "width": 110}
            ])
        return columns

    # Detallado
    columns = [
        {"fieldname": "posting_date", "label": _("Fecha"), "fieldtype": "Date", "width": 95},
        {"fieldname": "voucher_no", "label": _("Comprobante"), "fieldtype": "Data", "width": 150},
        {"fieldname": "display_ref", "label": _("Ref. Fiscal / Control"), "fieldtype": "Data", "width": 130},
        {"fieldname": "account", "label": _("Cuenta Contable"), "fieldtype": "Link", "options": "Account", "width": 240},
        {"fieldname": "party_info", "label": _("Tercero / RIF"), "fieldtype": "Data", "width": 180},
        {"fieldname": "cost_center", "label": _("Centro de Costo"), "fieldtype": "Link", "options": "Cost Center", "width": 130},
        {"fieldname": "narration", "label": _("Descripción / Glosa"), "fieldtype": "Data", "width": 230}
    ]

    if currency_filter == "VES":
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (Bs.)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "credit", "label": _("Haber (Bs.)"), "fieldtype": "Currency", "width": 120}
        ])
    elif currency_filter == "USD":
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (USD)"), "fieldtype": "Currency", "width": 120},
            {"fieldname": "credit", "label": _("Haber (USD)"), "fieldtype": "Currency", "width": 120}
        ])
    else:  # Bimoneda
        columns.extend([
            {"fieldname": "debit", "label": _("Debe (Bs.)"), "fieldtype": "Currency", "width": 110},
            {"fieldname": "credit", "label": _("Haber (Bs.)"), "fieldtype": "Currency", "width": 110},
            {"fieldname": "debit_usd", "label": _("Debe (USD)"), "fieldtype": "Currency", "width": 110},
            {"fieldname": "credit_usd", "label": _("Haber (USD)"), "fieldtype": "Currency", "width": 110}
        ])

    return columns


def get_transactional_data(
    company,
    from_date,
    to_date,
    currency_filter,
    presentation,
    voucher_type,
    account,
    party_type,
    party,
    cost_center,
    include_cancelled,
    company_name,
    company_rif,
    company_address,
    company_logo,
    currency_symbol
):
    conditions = ["gle.company = %s", "gle.docstatus = 1"]
    args = [company]

    if not include_cancelled:
        conditions.append("IFNULL(gle.is_cancelled, 0) = 0")

    if from_date:
        conditions.append("gle.posting_date >= %s")
        args.append(from_date)

    if to_date:
        conditions.append("gle.posting_date <= %s")
        args.append(to_date)

    if voucher_type and voucher_type != "Todos":
        conditions.append("gle.voucher_type = %s")
        args.append(voucher_type)

    if account:
        conditions.append("gle.account = %s")
        args.append(account)

    if party_type:
        conditions.append("gle.party_type = %s")
        args.append(party_type)

    if party:
        conditions.append("gle.party = %s")
        args.append(party)

    if cost_center:
        conditions.append("gle.cost_center = %s")
        args.append(cost_center)

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT 
            gle.name as gle_id,
            gle.posting_date, 
            gle.voucher_no, 
            gle.voucher_type,
            gle.account, 
            gle.party_type,
            gle.party,
            gle.cost_center,
            gle.project,
            gle.remarks, 
            gle.debit, 
            gle.credit,
            gle.debit_in_account_currency,
            gle.credit_in_account_currency,
            gle.account_currency,
            gle.is_cancelled,
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
            ) as display_ref,
            COALESCE(
                CASE 
                    WHEN gle.voucher_type = 'Sales Invoice' THEN NULLIF(si.bill_control, '')
                    WHEN gle.voucher_type = 'Purchase Invoice' THEN NULLIF(pi.bill_control, '')
                    WHEN gle.voucher_type = 'VE Sales Debit Note' THEN NULLIF(vsdn.bill_control, '')
                    WHEN gle.voucher_type = 'VE Sales Credit Note' THEN NULLIF(vscn.bill_control, '')
                    WHEN gle.voucher_type = 'VE Purchase Debit Note' THEN NULLIF(vpdn.bill_control, '')
                    WHEN gle.voucher_type = 'VE Purchase Credit Note' THEN NULLIF(vpcn.bill_control, '')
                    ELSE NULL
                END,
                ''
            ) as fiscal_control,
            COALESCE(
                CASE 
                    WHEN gle.voucher_type = 'Sales Invoice' THEN si.conversion_rate
                    WHEN gle.voucher_type = 'Purchase Invoice' THEN pi.conversion_rate
                    WHEN gle.voucher_type = 'Payment Entry' THEN COALESCE(NULLIF(pe.source_exchange_rate, 0), pe.target_exchange_rate)
                    ELSE NULL
                END,
                NULL
            ) as doc_rate
        FROM `tabGL Entry` gle
        LEFT JOIN `tabSales Invoice` si ON gle.voucher_no = si.name AND gle.voucher_type = 'Sales Invoice'
        LEFT JOIN `tabPurchase Invoice` pi ON gle.voucher_no = pi.name AND gle.voucher_type = 'Purchase Invoice'
        LEFT JOIN `tabPayment Entry` pe ON gle.voucher_no = pe.name AND gle.voucher_type = 'Payment Entry'
        LEFT JOIN `tabJournal Entry` je ON gle.voucher_no = je.name AND gle.voucher_type = 'Journal Entry'
        LEFT JOIN `tabVE Sales Debit Note` vsdn ON gle.voucher_no = vsdn.name AND gle.voucher_type = 'VE Sales Debit Note'
        LEFT JOIN `tabVE Sales Credit Note` vscn ON gle.voucher_no = vscn.name AND gle.voucher_type = 'VE Sales Credit Note'
        LEFT JOIN `tabVE Purchase Debit Note` vpdn ON gle.voucher_no = vpdn.name AND gle.voucher_type = 'VE Purchase Debit Note'
        LEFT JOIN `tabVE Purchase Credit Note` vpcn ON gle.voucher_no = vpcn.name AND gle.voucher_type = 'VE Purchase Credit Note'
        WHERE {where_clause}
        ORDER BY gle.posting_date, gle.voucher_no, gle.creation
    """

    gl_entries = frappe.db.sql(query, tuple(args), as_dict=True)
    if not gl_entries:
        return []

    # Precargar terceros para resolver nombres y RIF eficientemente
    customers = {}
    suppliers = {}
    employees = {}

    cust_ids = {e.party for e in gl_entries if e.party_type == "Customer" and e.party}
    supp_ids = {e.party for e in gl_entries if e.party_type == "Supplier" and e.party}
    emp_ids = {e.party for e in gl_entries if e.party_type == "Employee" and e.party}

    if cust_ids:
        for c in frappe.get_all("Customer", filters={"name": ["in", list(cust_ids)]}, fields=["name", "customer_name", "tax_id"]):
            tax_str = f" [{c.tax_id}]" if c.tax_id else ""
            customers[c.name] = f"{c.customer_name or c.name}{tax_str}"

    if supp_ids:
        for s in frappe.get_all("Supplier", filters={"name": ["in", list(supp_ids)]}, fields=["name", "supplier_name", "tax_id"]):
            tax_str = f" [{s.tax_id}]" if s.tax_id else ""
            suppliers[s.name] = f"{s.supplier_name or s.name}{tax_str}"

    if emp_ids:
        for em in frappe.get_all("Employee", filters={"name": ["in", list(emp_ids)]}, fields=["name", "employee_name"]):
            employees[em.name] = em.employee_name or em.name

    rate_cache = {}

    def get_rate(posting_date, doc_rate):
        if doc_rate and flt(doc_rate) > 0:
            return flt(doc_rate)
        d_str = str(posting_date)
        if d_str not in rate_cache:
            rate_cache[d_str] = flt(get_exchange_rate(d_str, "USD")) or 1.0
        return rate_cache[d_str]

    data = []

    # MODO RESUMIDO
    if presentation == "Resumido":
        summary = {}
        for entry in gl_entries:
            key = entry.voucher_no
            rate = get_rate(entry.posting_date, entry.doc_rate)
            deb_ves = flt(entry.debit)
            cred_ves = flt(entry.credit)

            if entry.account_currency == "USD" and (flt(entry.debit_in_account_currency) or flt(entry.credit_in_account_currency)):
                deb_usd = flt(entry.debit_in_account_currency)
                cred_usd = flt(entry.credit_in_account_currency)
            else:
                deb_usd = round(deb_ves / rate, 2) if rate > 0 else 0.0
                cred_usd = round(cred_ves / rate, 2) if rate > 0 else 0.0

            ref_str = entry.display_ref
            if entry.fiscal_control and entry.fiscal_control != entry.display_ref:
                ref_str = f"{entry.display_ref} (Ctrl: {entry.fiscal_control})"

            if key not in summary:
                summary[key] = {
                    "posting_date": entry.posting_date,
                    "voucher_type": entry.voucher_type,
                    "voucher_no": entry.voucher_no,
                    "display_ref": ref_str,
                    "narration": entry.remarks or "",
                    "debit_ves": 0.0,
                    "credit_ves": 0.0,
                    "debit_usd": 0.0,
                    "credit_usd": 0.0,
                    "company_name": company_name,
                    "company_rif": company_rif,
                    "company_address": company_address,
                    "company_logo": company_logo,
                    "currency_filter": currency_filter,
                    "currency_symbol": currency_symbol
                }
            summary[key]["debit_ves"] += deb_ves
            summary[key]["credit_ves"] += cred_ves
            summary[key]["debit_usd"] += deb_usd
            summary[key]["credit_usd"] += cred_usd

        grand_deb_ves = 0.0
        grand_cred_ves = 0.0
        grand_deb_usd = 0.0
        grand_cred_usd = 0.0

        for key in sorted(summary.keys(), key=lambda k: (summary[k]["posting_date"], summary[k]["voucher_no"])):
            row = summary[key]
            deb_v = round(row["debit_ves"], 2)
            cred_v = round(row["credit_ves"], 2)
            deb_u = round(row["debit_usd"], 2)
            cred_u = round(row["credit_usd"], 2)

            grand_deb_ves += deb_v
            grand_cred_ves += cred_v
            grand_deb_usd += deb_u
            grand_cred_usd += cred_u

            diff = round(deb_v - cred_v, 2) if currency_filter == "VES" else round(deb_u - cred_u, 2)

            out_row = {
                "posting_date": row["posting_date"],
                "voucher_type": row["voucher_type"],
                "voucher_no": row["voucher_no"],
                "display_ref": row["display_ref"],
                "narration": row["narration"],
                "difference": diff,
                "company_name": company_name,
                "company_rif": company_rif,
                "company_address": company_address,
                "company_logo": company_logo,
                "currency_filter": currency_filter,
                "currency_symbol": currency_symbol
            }
            if currency_filter == "VES":
                out_row["debit"] = deb_v
                out_row["credit"] = cred_v
            elif currency_filter == "USD":
                out_row["debit"] = deb_u
                out_row["credit"] = cred_u
            else:
                out_row["debit"] = deb_v
                out_row["credit"] = cred_v
                out_row["debit_usd"] = deb_u
                out_row["credit_usd"] = cred_u

            data.append(out_row)

        data.append({"posting_date": "", "voucher_no": "", "voucher_type": "", "display_ref": "", "narration": "", "debit": 0, "credit": 0, "is_spacer": 1})
        grand_diff = round(grand_deb_ves - grand_cred_ves, 2) if currency_filter == "VES" else round(grand_deb_usd - grand_cred_usd, 2)
        total_row = {
            "posting_date": "",
            "voucher_type": "",
            "voucher_no": "",
            "display_ref": "",
            "narration": _("TOTAL GENERAL LIBRO DIARIO"),
            "difference": grand_diff,
            "is_total": 1,
            "is_group": 1,
            "company_name": company_name,
            "company_rif": company_rif,
            "company_address": company_address,
            "company_logo": company_logo,
            "currency_filter": currency_filter,
            "currency_symbol": currency_symbol
        }
        if currency_filter == "VES":
            total_row["debit"] = round(grand_deb_ves, 2)
            total_row["credit"] = round(grand_cred_ves, 2)
        elif currency_filter == "USD":
            total_row["debit"] = round(grand_deb_usd, 2)
            total_row["credit"] = round(grand_cred_usd, 2)
        else:
            total_row["debit"] = round(grand_deb_ves, 2)
            total_row["credit"] = round(grand_cred_ves, 2)
            total_row["debit_usd"] = round(grand_deb_usd, 2)
            total_row["credit_usd"] = round(grand_cred_usd, 2)

        data.append(total_row)
        return data

    # MODO DETALLADO
    current_voucher = None
    v_deb_ves = 0.0
    v_cred_ves = 0.0
    v_deb_usd = 0.0
    v_cred_usd = 0.0

    grand_deb_ves = 0.0
    grand_cred_ves = 0.0
    grand_deb_usd = 0.0
    grand_cred_usd = 0.0

    for entry in gl_entries:
        if current_voucher and current_voucher != entry.voucher_no:
            # Subtotal del comprobante anterior
            v_sub_row = {
                "posting_date": "",
                "voucher_no": "",
                "display_ref": "",
                "account": f"Total Comprobante {current_voucher}",
                "party_info": "",
                "cost_center": "",
                "narration": "",
                "is_voucher_total": 1,
                "is_total": 1,
                "is_balanced": 1 if abs(v_deb_ves - v_cred_ves) < 0.01 else 0,
                "difference": round(abs(v_deb_ves - v_cred_ves), 2),
                "company_name": company_name,
                "company_rif": company_rif,
                "company_address": company_address,
                "company_logo": company_logo,
                "currency_filter": currency_filter,
                "currency_symbol": currency_symbol
            }
            if currency_filter == "VES":
                v_sub_row["debit"] = round(v_deb_ves, 2)
                v_sub_row["credit"] = round(v_cred_ves, 2)
            elif currency_filter == "USD":
                v_sub_row["debit"] = round(v_deb_usd, 2)
                v_sub_row["credit"] = round(v_cred_usd, 2)
            else:
                v_sub_row["debit"] = round(v_deb_ves, 2)
                v_sub_row["credit"] = round(v_cred_ves, 2)
                v_sub_row["debit_usd"] = round(v_deb_usd, 2)
                v_sub_row["credit_usd"] = round(v_cred_usd, 2)

            data.append(v_sub_row)
            data.append({"posting_date": "", "voucher_no": "", "account": "", "narration": "", "debit": 0, "credit": 0, "is_spacer": 1})

            v_deb_ves = 0.0
            v_cred_ves = 0.0
            v_deb_usd = 0.0
            v_cred_usd = 0.0

        current_voucher = entry.voucher_no
        rate = get_rate(entry.posting_date, entry.doc_rate)
        deb_v = flt(entry.debit)
        cred_v = flt(entry.credit)

        if entry.account_currency == "USD" and (flt(entry.debit_in_account_currency) or flt(entry.credit_in_account_currency)):
            deb_u = flt(entry.debit_in_account_currency)
            cred_u = flt(entry.credit_in_account_currency)
        else:
            deb_u = round(deb_v / rate, 2) if rate > 0 else 0.0
            cred_u = round(cred_v / rate, 2) if rate > 0 else 0.0

        v_deb_ves += deb_v
        v_cred_ves += cred_v
        v_deb_usd += deb_u
        v_cred_usd += cred_u

        grand_deb_ves += deb_v
        grand_cred_ves += cred_v
        grand_deb_usd += deb_u
        grand_cred_usd += cred_u

        # Resolver información de tercero
        party_name_str = ""
        if entry.party_type == "Customer" and entry.party in customers:
            party_name_str = customers[entry.party]
        elif entry.party_type == "Supplier" and entry.party in suppliers:
            party_name_str = suppliers[entry.party]
        elif entry.party_type == "Employee" and entry.party in employees:
            party_name_str = employees[entry.party]
        elif entry.party:
            party_name_str = f"{entry.party_type}: {entry.party}"

        ref_str = entry.display_ref
        if entry.fiscal_control and entry.fiscal_control != entry.display_ref:
            ref_str = f"{entry.display_ref} (Ctrl: {entry.fiscal_control})"

        line_row = {
            "posting_date": entry.posting_date,
            "voucher_no": entry.voucher_no,
            "voucher_type": entry.voucher_type,
            "display_ref": ref_str,
            "account": entry.account,
            "party_info": party_name_str,
            "cost_center": entry.cost_center or "",
            "narration": entry.remarks or "",
            "company_name": company_name,
            "company_rif": company_rif,
            "company_address": company_address,
            "company_logo": company_logo,
            "currency_filter": currency_filter,
            "currency_symbol": currency_symbol
        }
        if currency_filter == "VES":
            line_row["debit"] = deb_v
            line_row["credit"] = cred_v
        elif currency_filter == "USD":
            line_row["debit"] = deb_u
            line_row["credit"] = cred_u
        else:
            line_row["debit"] = deb_v
            line_row["credit"] = cred_v
            line_row["debit_usd"] = deb_u
            line_row["credit_usd"] = cred_u

        data.append(line_row)

    if current_voucher:
        v_sub_row = {
            "posting_date": "",
            "voucher_no": "",
            "display_ref": "",
            "account": f"Total Comprobante {current_voucher}",
            "party_info": "",
            "cost_center": "",
            "narration": "",
            "is_voucher_total": 1,
            "is_total": 1,
            "is_balanced": 1 if abs(v_deb_ves - v_cred_ves) < 0.01 else 0,
            "difference": round(abs(v_deb_ves - v_cred_ves), 2),
            "company_name": company_name,
            "company_rif": company_rif,
            "company_address": company_address,
            "company_logo": company_logo,
            "currency_filter": currency_filter,
            "currency_symbol": currency_symbol
        }
        if currency_filter == "VES":
            v_sub_row["debit"] = round(v_deb_ves, 2)
            v_sub_row["credit"] = round(v_cred_ves, 2)
        elif currency_filter == "USD":
            v_sub_row["debit"] = round(v_deb_usd, 2)
            v_sub_row["credit"] = round(v_cred_usd, 2)
        else:
            v_sub_row["debit"] = round(v_deb_ves, 2)
            v_sub_row["credit"] = round(v_cred_ves, 2)
            v_sub_row["debit_usd"] = round(v_deb_usd, 2)
            v_sub_row["credit_usd"] = round(v_cred_usd, 2)

        data.append(v_sub_row)

    data.append({"posting_date": "", "voucher_no": "", "account": "", "narration": "", "debit": 0, "credit": 0, "is_spacer": 1})
    total_row = {
        "posting_date": "",
        "voucher_no": "",
        "display_ref": "",
        "account": _("TOTAL GENERAL LIBRO DIARIO"),
        "party_info": "",
        "cost_center": "",
        "narration": "",
        "is_total": 1,
        "is_group": 1,
        "company_name": company_name,
        "company_rif": company_rif,
        "company_address": company_address,
        "company_logo": company_logo,
        "currency_filter": currency_filter,
        "currency_symbol": currency_symbol
    }
    if currency_filter == "VES":
        total_row["debit"] = round(grand_deb_ves, 2)
        total_row["credit"] = round(grand_cred_ves, 2)
    elif currency_filter == "USD":
        total_row["debit"] = round(grand_deb_usd, 2)
        total_row["credit"] = round(grand_cred_usd, 2)
    else:
        total_row["debit"] = round(grand_deb_ves, 2)
        total_row["credit"] = round(grand_cred_ves, 2)
        total_row["debit_usd"] = round(grand_deb_usd, 2)
        total_row["credit_usd"] = round(grand_cred_usd, 2)

    data.append(total_row)
    return data
