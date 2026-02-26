# # Copyright (c) 2026, DominaERP and contributors
# # For license information, please see license.txt

import frappe
from frappe import _

def execute(filters=None):
    if not filters:
        return [], []
        
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
        {"fieldname": "tax_id", "label": _("RIF Proveedor"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier", "label": _("Nombre Proveedor"), "fieldtype": "Link", "options": "Supplier", "width": "auto"},
        {"fieldname": "doc_no", "label": _("Número de Factura"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_date", "label": _("Fecha Factura"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "tax_description", "label": _("Impuesto"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "posting_date", "label": _("Fecha Emisión"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "voucher_no", "label": _("Nro. Retención"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "purchase_invoice", "label": _("Factura de Compra"), "fieldtype": "Link", "options": "Purchase Invoice", "width": "auto"},
        {"fieldname": "bill_control", "label": _("No. Control"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "islr_base_amount", "label": _("Monto Objeto Retención"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "islr_amount", "label": _("Impuesto Retenido"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "parent", "label": _("URL Retención"), "fieldtype": "Link", "options": "ISLR Withholding Voucher", "width": "auto"},
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
        conditions += " AND parent.proveedor = %(supplier)s"
        query_params["supplier"] = filters.get("supplier")

    query = f"""
        SELECT
            supp.tax_id,
            parent.supplier,
            child.doc_no,
            child.posting_date as bill_date,
            -- Buscamos la descripción en la tabla de impuestos del pago
            ptc.description as tax_description,
			ptc.charge_type,
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
        -- Unión con la tabla de impuestos del Pago
        LEFT JOIN
            `tabAdvance Taxes and Charges` ptc ON ptc.parent = child.payment_entry_name 
            AND ptc.charge_type = 'ISLR'
        WHERE
            child.posting_date BETWEEN '{filters.get('from_date')}' AND '{filters.get('to_date')}'
            {conditions}
        ORDER BY
            child.posting_date DESC, child.idx ASC
    """
    
    return frappe.db.sql(query, query_params, as_dict=True)