# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_first_day

from l10n_ve.l10n_ve.report.sales_book.sales_book import (
    branch_scope_condition,
    get_branch_subtree,
)
from l10n_ve.utils.utils import get_exchange_rate

# La sucursal de la retención es la del comprobante; la de la factura solo entra
# si el comprobante no la trae. Se define una sola vez porque el WHERE y el
# SELECT tienen que decir exactamente lo mismo: si filtran distinto de lo que
# muestran, el usuario pide una sucursal y ve filas rotuladas con otra.
BRANCH_EXPR = "COALESCE(NULLIF(parent.branch, ''), pi.branch)"


def execute(filters=None):
    if not filters:
        return [], []
        
    columns = get_columns(filters)
    data = get_data(filters)
    return columns, data


def get_columns(filters):
    group_by = filters.get("group_by") or "Detalle"
    
    if group_by == "Por Proveedor":
        return [
            {"fieldname": "tax_id", "label": _("RIF Proveedor"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "supplier_name", "label": _("Nombre Proveedor"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "subtracting", "label": _("Sustraendo"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "bcv_rate", "label": _("Tasa BCV"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount_usd", "label": _("Impuesto Retenido USD"), "fieldtype": "Currency", "width": "auto"}
        ]
    elif group_by == "Por Concepto":
        return [
            {"fieldname": "concept_code", "label": _("Código Concepto"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "concept_description", "label": _("Concepto de Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "subtracting", "label": _("Sustraendo"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "bcv_rate", "label": _("Tasa BCV"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount_usd", "label": _("Impuesto Retenido USD"), "fieldtype": "Currency", "width": "auto"}
        ]
    else:
        return [
            {"fieldname": "tax_id", "label": _("RIF Proveedor"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "supplier_name", "label": _("Nombre Proveedor"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "supplier", "label": _("Proveedor"), "fieldtype": "Link", "options": "Supplier", "width": "auto"},
            {"fieldname": "doc_no", "label": _("Número de Factura"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "bill_date", "label": _("Fecha Factura"), "fieldtype": "Date", "width": "auto"},
            {"fieldname": "concept_code", "label": _("Código Concepto"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "concept_description", "label": _("Concepto de Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "posting_date", "label": _("Fecha Emisión"), "fieldtype": "Date", "width": "auto"},
            {"fieldname": "voucher_no", "label": _("Nro. Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "purchase_invoice", "label": _("Factura de Compra"), "fieldtype": "Link", "options": "Purchase Invoice", "width": "auto"},
            {"fieldname": "bill_control", "label": _("No. Control"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "subtracting", "label": _("Sustraendo"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "rate", "label": _("% Retención ISLR"), "fieldtype": "Percent", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "bcv_rate", "label": _("Tasa BCV"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount_usd", "label": _("Impuesto Retenido USD"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "branch", "label": _("Sucursal"), "fieldtype": "Link", "options": "VE Branch", "width": "auto"},
            {"fieldname": "parent", "label": _("Documento Retención"), "fieldtype": "Link", "options": "ISLR Withholding Voucher", "width": "auto"},
            {"fieldname": "status", "label": _("Estado del Documento"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "declared_status", "label": _("Estado del Comprobante"), "fieldtype": "Data", "width": "auto"}
        ]


def _resolve_branches(filters: dict) -> tuple[str, bool, tuple[str, ...], str, dict]:
    """Resuelve sucursales considerando árbol jerárquico, listas y exclusión."""
    branch_val = filters.get("branch")
    branches_val = filters.get("branches")
    exclude_branches = bool(filters.get("exclude_branches"))

    if isinstance(branch_val, (list, tuple)):
        branches = [b for b in branch_val if b]
        branch = ""
    elif branches_val and isinstance(branches_val, (list, tuple)):
        branches = [b for b in branches_val if b]
        branch = ""
    else:
        branches = []
        branch = str(branch_val or "").strip()

    if exclude_branches and branch and not branches:
        branches = [branch]
        branch = ""

    if branches:
        resolved = set()
        for b in branches:
            sub = get_branch_subtree(b)
            if sub:
                resolved.update(sub)
            else:
                resolved.add(b)
        branch_scope = tuple(sorted(resolved)) if resolved else ("__ninguna__",)
        return branch, exclude_branches, branch_scope, "scope", {"branch_scope": branch_scope}
    elif branch:
        _, branch_params = branch_scope_condition(branch, "branch")
        return branch, False, (), "single", branch_params
    else:
        return "", False, (), "none", {}


def get_data(filters):
    query_params = {
        "from_date": filters.get('from_date'),
        "to_date": filters.get('to_date')
    }

    conditions = ""

    if filters.get("company"):
        conditions += " AND parent.empresa = %(company)s"
        query_params["company"] = filters.get("company")
        
    if filters.get("supplier"):
        conditions += " AND parent.supplier = %(supplier)s"
        query_params["supplier"] = filters.get("supplier")

    branch, exclude_branches, branch_scope, mode, branch_params = _resolve_branches(filters)
    if mode == "scope":
        op = "NOT IN" if exclude_branches else "IN"
        conditions += f" AND IFNULL({BRANCH_EXPR}, '') {op} %(branch_scope)s"
        query_params["branch_scope"] = branch_scope
    elif mode == "single":
        branch_condition, b_params = branch_scope_condition(branch, BRANCH_EXPR)
        conditions += branch_condition
        query_params.update(b_params)

    group_by = filters.get("group_by") or "Detalle"

    if group_by == "Por Proveedor":
        # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
        query = f"""
            SELECT
                supp.tax_id,
                parent.supplier,
                supp.supplier_name,
                SUM(child.islr_base_amount) as islr_base_amount,
                SUM(child.subtracting) as subtracting,
                SUM(child.islr_amount) as islr_amount
            FROM
                `tabISLR Withholding Voucher Item` child
            INNER JOIN
                `tabISLR Withholding Voucher` parent ON child.parent = parent.name
            INNER JOIN
                `tabSupplier` supp ON parent.supplier = supp.name
            LEFT JOIN
                `tabPurchase Invoice` pi ON child.purchase_invoice = pi.name
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND parent.docstatus = 1
                {conditions}
            GROUP BY
                parent.supplier, supp.tax_id, supp.supplier_name
            ORDER BY
                supp.tax_id ASC
        """
    elif group_by == "Por Concepto":
        # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
        query = f"""
            SELECT
                child.code as concept_code,
                COALESCE(tab_islr.descripcion, child.code) as concept_description,
                SUM(child.islr_base_amount) as islr_base_amount,
                SUM(child.subtracting) as subtracting,
                SUM(child.islr_amount) as islr_amount
            FROM
                `tabISLR Withholding Voucher Item` child
            INNER JOIN
                `tabISLR Withholding Voucher` parent ON child.parent = parent.name
            LEFT JOIN (
                SELECT codigo, MAX(descripcion) AS descripcion
                FROM `tabTabulator ISLR`
                GROUP BY codigo
            ) tab_islr ON child.code = tab_islr.codigo
            LEFT JOIN
                `tabPurchase Invoice` pi ON child.purchase_invoice = pi.name
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND parent.docstatus = 1
                {conditions}
            GROUP BY
                child.code, tab_islr.descripcion
            ORDER BY
                child.code ASC
        """
    else:
        # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
        query = f"""
            SELECT
                supp.tax_id,
                parent.supplier,
                supp.supplier_name,
                child.doc_no,
                child.posting_date as bill_date,
                child.code as concept_code,
                COALESCE(tab_islr.descripcion, child.code) as concept_description,
                child.posting_date as posting_date,
                COALESCE(parent.voucher_number, parent.name) as voucher_no,
                child.purchase_invoice,
                child.bill_control,
                child.islr_base_amount,
                child.subtracting,
                child.rate,
                child.islr_amount,
                {BRANCH_EXPR} AS branch,
                child.parent,
                parent.is_declared,
                CASE 
                    WHEN parent.is_declared = 1 THEN '{_("Declarado")}'
                    ELSE '{_("Pendiente")}'
                END as declared_status,
                CASE 
                    WHEN parent.docstatus = 0 THEN '{_("Borrador")}'
                    WHEN parent.docstatus = 1 THEN '{_("Aprobado")}'
                    WHEN parent.docstatus = 2 THEN '{_("Cancelado")}'
                END as status
            FROM
                `tabISLR Withholding Voucher Item` child
            INNER JOIN
                `tabISLR Withholding Voucher` parent ON child.parent = parent.name
            INNER JOIN
                `tabSupplier` supp ON parent.supplier = supp.name
            LEFT JOIN (
                SELECT codigo, MAX(descripcion) AS descripcion
                FROM `tabTabulator ISLR`
                GROUP BY codigo
            ) tab_islr ON child.code = tab_islr.codigo
            LEFT JOIN
                `tabPurchase Invoice` pi ON child.purchase_invoice = pi.name
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                AND parent.docstatus != 2
                {conditions}
            ORDER BY
                child.posting_date DESC, child.idx ASC
        """
    
    raw_data = frappe.db.sql(query, query_params, as_dict=True)

    rates_cache = {}
    for d in raw_data:
        ref_date = d.get("posting_date") or d.get("bill_date") or filters.get("from_date")
        bcv_rate = 0.0
        if ref_date:
            try:
                first_day = str(get_first_day(ref_date))
                if first_day not in rates_cache:
                    rates_cache[first_day] = flt(get_exchange_rate(first_day, "USD"))
                bcv_rate = rates_cache[first_day]
            except Exception:
                bcv_rate = 0.0
        d["bcv_rate"] = bcv_rate
        ret_bs = flt(d.get("islr_amount", 0))
        d["islr_amount_usd"] = flt(ret_bs / bcv_rate, 2) if bcv_rate > 0 else 0.0

    return raw_data
