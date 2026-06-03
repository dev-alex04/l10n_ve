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
        {"fieldname": "supplier", "label": _("Nombre del Proveedor"), "fieldtype": "Link", "options": "Supplier", "width": "auto"},
        {"fieldname": "bill_no", "label": _("Número de Factura"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_control", "label": _("Número de Control"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "posting_date", "label": _("Fecha Factura"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "tax_withholding_category", "label": _("Impuesto"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "issue_date", "label": _("Fecha Emisión"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "voucher_number", "label": _("Número de Comprobante"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "total", "label": _("Base Imponible Bs"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "tax_amount_vat", "label": _("Monto Retención Bs"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "parent", "label": _("Documento Retención"), "fieldtype": "Link", "options": "VAT Withholding Voucher", "width": "auto"},
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
    
    query = f"""
        SELECT
			supp.tax_id,
            parent.supplier,
            child.bill_no,
            child.posting_date,
			inv.tax_withholding_category,
			parent.voucher_number,
            child.bill_control,
			parent.issue_date,
            child.total,
            child.tax_amount_vat,
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
            `tabVAT Withholding Voucher Item` child
        INNER JOIN
            `tabVAT Withholding Voucher` parent ON child.parent = parent.name
		INNER JOIN
            `tabSupplier` supp ON parent.supplier = supp.name
		LEFT JOIN
            `tabPurchase Invoice` inv ON child.bill_no = inv.bill_no 
            AND parent.supplier = inv.supplier
        WHERE
            child.posting_date BETWEEN %(from_date)s AND %(to_date)s
            {conditions}
        ORDER BY
            child.posting_date DESC, child.bill_no ASC
    """
    
    return frappe.db.sql(query, query_params, as_dict=True)