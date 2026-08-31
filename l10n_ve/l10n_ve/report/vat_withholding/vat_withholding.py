import frappe
from frappe import _

from l10n_ve.l10n_ve.report.sales_book.sales_book import branch_scope_condition

# La sucursal de la retención es la del comprobante; la de la factura solo entra
# si el comprobante no la trae. Se define una sola vez porque el WHERE y el
# SELECT tienen que decir exactamente lo mismo: si filtran distinto de lo que
# muestran, el usuario pide una sucursal y ve filas rotuladas con otra.
#
# `NULLIF` está porque Frappe guarda cadena vacía --no NULL-- en un Link sin
# cargar, y con `COALESCE` pelado el respaldo no entraría nunca.
BRANCH_EXPR = "COALESCE(NULLIF(parent.branch, ''), inv.branch)"

def execute(filters=None):
    if not filters:
        return [], []
        
    columns = get_columns()
    data = get_data(filters)
    return columns, data

def get_columns():
    return [
		{"fieldname": "tax_id", "label": _("RIF Proveedor"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "supplier_name", "label": _("Nombre del Proveedor"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_no", "label": _("Número de Factura"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "bill_control", "label": _("Número de Control"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "posting_date", "label": _("Fecha Factura"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "tax_withholding_category", "label": _("Impuesto"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "issue_date", "label": _("Fecha Emisión"), "fieldtype": "Date", "width": "auto"},
        {"fieldname": "voucher_number", "label": _("Número de Comprobante"), "fieldtype": "Data", "width": "auto"},
        {"fieldname": "total", "label": _("Base Imponible Bs"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "rate", "label": _("Alícuota IVA (%)"), "fieldtype": "Percent", "width": "auto"},
        {"fieldname": "withholding_rate", "label": _("% Retención IVA"), "fieldtype": "Percent", "width": "auto"},
        {"fieldname": "tax_amount_vat", "label": _("Monto Retención Bs"), "fieldtype": "Currency", "width": "auto"},
        {"fieldname": "branch", "label": _("Sucursal"), "fieldtype": "Link", "options": "VE Branch", "width": "auto"},
        {"fieldname": "parent", "label": _("Documento Retención"), "fieldtype": "Link", "options": "VAT Withholding Voucher", "width": "auto"},
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

    branch_condition, branch_params = branch_scope_condition(
        filters.get("branch"), BRANCH_EXPR)
    conditions += branch_condition
    query_params.update(branch_params)
    
    query = f"""
        SELECT
			supp.tax_id,
            supp.supplier_name,
            child.bill_no,
            child.posting_date,
			inv.tax_withholding_category,
			parent.voucher_number,
            child.bill_control,
			parent.issue_date,
            child.total,
            child.rate,
            child.withholding_rate,
            child.tax_amount_vat,
            {BRANCH_EXPR} AS branch,
       		child.parent,
            parent.is_declared,
            CASE 
                WHEN parent.is_declared = 1 THEN '{_("Declarado")}'
                ELSE '{_("Pendiente")}'
            END as declared_status
        FROM
            `tabVAT Withholding Voucher Item` child
        INNER JOIN
            `tabVAT Withholding Voucher` parent ON child.parent = parent.name
		INNER JOIN
            `tabSupplier` supp ON parent.supplier = supp.name
		LEFT JOIN
            `tabPurchase Invoice` inv ON child.bill_no = inv.bill_no 
            AND parent.supplier = inv.supplier
            AND inv.docstatus = 1
        WHERE
            parent.issue_date BETWEEN %(from_date)s AND %(to_date)s
            AND parent.docstatus = 1
            {conditions}
        ORDER BY
            parent.issue_date DESC, child.bill_no ASC
    """
    
    return frappe.db.sql(query, query_params, as_dict=True)