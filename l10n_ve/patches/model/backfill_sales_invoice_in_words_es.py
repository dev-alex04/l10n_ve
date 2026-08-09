import frappe

def execute():
    """
    Recalcula 'base_in_words' e 'in_words' en Español ('es') para todas las Facturas de Ventas
    existentes en la Base de Datos que tengan el texto guardado en Inglés o vacío.
    """
    frappe.reload_doc("accounts", "doctype", "sales_invoice")

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={"docstatus": ["<", 2]},
        fields=["name"]
    )

    if not invoices:
        return

    original_lang = getattr(frappe.local, "lang", "es")
    try:
        frappe.local.lang = "es"
        for inv in invoices:
            doc = frappe.get_doc("Sales Invoice", inv.name)
            if hasattr(doc, "set_total_in_words"):
                doc.set_total_in_words()
            else:
                from frappe.utils import money_in_words
                base_amount = abs(doc.base_grand_total if doc.is_rounded_total_disabled() else doc.base_rounded_total)
                doc.base_in_words = money_in_words(base_amount, doc.company_currency)
                amount = abs(doc.grand_total if doc.is_rounded_total_disabled() else doc.rounded_total)
                doc.in_words = money_in_words(amount, doc.currency)
                if not doc.base_in_words and doc.in_words:
                    doc.base_in_words = doc.in_words

            frappe.db.sql(
                """
                UPDATE `tabSales Invoice`
                SET base_in_words = %s, in_words = %s
                WHERE name = %s
                """,
                (doc.base_in_words, doc.in_words, doc.name)
            )
    finally:
        frappe.local.lang = original_lang

    frappe.db.commit()
