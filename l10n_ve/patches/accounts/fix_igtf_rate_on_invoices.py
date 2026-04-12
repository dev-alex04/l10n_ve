"""Corrige facturas con igtf_rate = 0 que tienen IGTF cobrado.

Busca facturas pagadas con total_igtf > 0 pero igtf_rate = 0, y les asigna
la tasa IGTF vigente desde Venezuela Account Settings.
"""
import frappe
from frappe.utils import flt


def execute() -> None:
    igtf_rate: float = flt(
        frappe.db.get_single_value("Venezuela Account Settings", "igtf_rate")
    )
    if not igtf_rate:
        print("⚠ No se encontró igtf_rate en Venezuela Account Settings")
        return

    invoices: list[dict] = frappe.db.sql("""
        SELECT name
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND igtf_rate = 0
          AND total_igtf > 0
    """, as_dict=True)

    if not invoices:
        return

    count: int = 0
    for inv in invoices:
        frappe.db.set_value(
            "Sales Invoice", inv.name,
            "igtf_rate", igtf_rate,
            update_modified=False
        )
        count += 1

    frappe.db.commit()
    print(f"✔ Se actualizaron {count} facturas con igtf_rate = {igtf_rate}")
