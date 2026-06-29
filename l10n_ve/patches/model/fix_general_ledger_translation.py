import frappe

def execute():
    # Clean any existing translation first to avoid duplicate errors
    frappe.db.delete("Translation", {"source_text": "General Ledger", "language": "es"})

    # Create the translation doc
    doc = frappe.get_doc({
        "doctype": "Translation",
        "language": "es",
        "source_text": "General Ledger",
        "translated_text": "Libro Mayor General"
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache()
