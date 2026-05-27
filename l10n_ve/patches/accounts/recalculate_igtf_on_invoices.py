import frappe

def execute():
    """
    Recalcula el IGTF de todas las facturas de venta y compra que tienen pagos 
    con IGTF confirmados, y limpia cualquier valor residual en facturas sin pagos activos.
    """
    for doctype in ["Sales Invoice", "Purchase Invoice"]:
        if not frappe.db.has_column(doctype, "total_igtf"):
            continue

        frappe.db.sql(f"""
            UPDATE `tab{doctype}` inv
            LEFT JOIN (
                SELECT 
                    per.reference_name,
                    SUM(per.allocated_amount) as base_igtf,
                    SUM((per.allocated_amount * IFNULL(pe.igtf_rate, 3)) / 100) as total_igtf
                FROM `tabPayment Entry Reference` per
                JOIN `tabPayment Entry` pe ON pe.name = per.parent
                WHERE per.reference_doctype = '{doctype}'
                  AND pe.docstatus = 1
                  AND EXISTS (
                      SELECT 1 FROM `tabPayment Entry Tax` pet 
                      WHERE pet.parent = pe.name AND pet.charge_type = 'IGTF'
                  )
                GROUP BY per.reference_name
            ) as igtf_data ON inv.name = igtf_data.reference_name
            SET 
                inv.base_amount_igtf = IFNULL(igtf_data.base_igtf, 0.0),
                inv.total_igtf = IFNULL(igtf_data.total_igtf, 0.0)
            WHERE inv.docstatus = 1 
              AND (inv.total_igtf != 0 OR inv.base_amount_igtf != 0 OR igtf_data.total_igtf IS NOT NULL)
        """)
