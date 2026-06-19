# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _

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
            {"fieldname": "supplier", "label": _("Nombre Proveedor"), "fieldtype": "Link", "options": "Supplier", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"}
        ]
    elif group_by == "Por Concepto":
        return [
            {"fieldname": "concept_code", "label": _("Código Concepto"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "concept_description", "label": _("Concepto de Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"}
        ]
    else:
        return [
            {"fieldname": "tax_id", "label": _("RIF Proveedor"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "supplier", "label": _("Nombre Proveedor"), "fieldtype": "Link", "options": "Supplier", "width": "auto"},
            {"fieldname": "doc_no", "label": _("Número de Factura"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "bill_date", "label": _("Fecha Factura"), "fieldtype": "Date", "width": "auto"},
            {"fieldname": "concept_code", "label": _("Código Concepto"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "concept_description", "label": _("Concepto de Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "posting_date", "label": _("Fecha Emisión"), "fieldtype": "Date", "width": "auto"},
            {"fieldname": "voucher_no", "label": _("Nro. Retención"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "purchase_invoice", "label": _("Factura de Compra"), "fieldtype": "Link", "options": "Purchase Invoice", "width": "auto"},
            {"fieldname": "bill_control", "label": _("No. Control"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"},
            {"fieldname": "parent", "label": _("Documento Retención"), "fieldtype": "Link", "options": "ISLR Withholding Voucher", "width": "auto"},
            {"fieldname": "status", "label": _("Estado del Documento"), "fieldtype": "Data", "width": "auto"},
            {"fieldname": "declared_status", "label": _("Estado del Comprobante"), "fieldtype": "Data", "width": "auto"}
        ]

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

    group_by = filters.get("group_by") or "Detalle"

    if group_by == "Por Proveedor":
        query = f"""
            SELECT
                supp.tax_id,
                parent.supplier,
                SUM(child.islr_base_amount) as islr_base_amount,
                SUM(child.islr_amount) as islr_amount
            FROM
                `tabISLR Withholding Voucher Item` child
            INNER JOIN
                `tabISLR Withholding Voucher` parent ON child.parent = parent.name
            INNER JOIN
                `tabSupplier` supp ON parent.supplier = supp.name
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                {conditions}
            GROUP BY
                parent.supplier, supp.tax_id
            ORDER BY
                supp.tax_id ASC
        """
    elif group_by == "Por Concepto":
        query = f"""
            SELECT
                child.code as concept_code,
                COALESCE(tab_islr.descripcion, child.code) as concept_description,
                SUM(child.islr_base_amount) as islr_base_amount,
                SUM(child.islr_amount) as islr_amount
            FROM
                `tabISLR Withholding Voucher Item` child
            INNER JOIN
                `tabISLR Withholding Voucher` parent ON child.parent = parent.name
            LEFT JOIN
                `tabTabulator ISLR` tab_islr ON child.code = tab_islr.codigo
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                {conditions}
            GROUP BY
                child.code, tab_islr.descripcion
            ORDER BY
                child.code ASC
        """
    else:
        query = f"""
            SELECT
                supp.tax_id,
                parent.supplier,
                child.doc_no,
                child.posting_date as bill_date,
                child.code as concept_code,
                COALESCE(tab_islr.descripcion, child.code) as concept_description,
                child.posting_date as posting_date,
                parent.name as voucher_no,
                child.purchase_invoice,
                child.bill_control,
                child.islr_base_amount,
                child.islr_amount,
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
            LEFT JOIN
                `tabTabulator ISLR` tab_islr ON child.code = tab_islr.codigo
            WHERE
                parent.posting_date BETWEEN %(from_date)s AND %(to_date)s
                {conditions}
            ORDER BY
                child.posting_date DESC, child.idx ASC
        """
    
    return frappe.db.sql(query, query_params, as_dict=True)