"""
Parche de migración: poblar supplier_name en comprobantes de retención históricos.

Se agregó el campo supplier_name (fetch_from=supplier.supplier_name, in_list_view)
a ISLR Withholding Voucher y VAT Withholding Voucher para que la columna
"Proveedor" de la vista de lista muestre la razón social y no el ID del
proveedor (opaco cuando el naming de Supplier pase a serie). fetch_from solo
puebla al guardar, así que las vouchers ya emitidas quedarían con supplier_name
vacío. Este patch lo rellena desde tabSupplier.

Idempotente: escribe un solo campo vía UPDATE ... JOIN, solo donde supplier_name
está vacío, sin disparar hooks (no toca contabilidad ni el estado del
comprobante). Seguro re-ejecutar.
"""

import frappe


def execute() -> None:
    for doctype in ("ISLR Withholding Voucher", "VAT Withholding Voucher"):
        table = f"tab{doctype}"
        frappe.db.sql(
            f"""
            UPDATE `{table}` v
            JOIN `tabSupplier` s ON s.name = v.supplier
            SET v.supplier_name = s.supplier_name
            WHERE COALESCE(v.supplier_name, '') = ''
              AND COALESCE(s.supplier_name, '') != ''
            """
        )
