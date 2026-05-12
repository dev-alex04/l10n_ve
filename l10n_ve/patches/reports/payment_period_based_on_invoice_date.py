import frappe
from frappe import _
import erpnext.accounts.report.payment_period_based_on_invoice_date.payment_period_based_on_invoice_date as pp

original_execute = pp.execute

def custom_execute(filters=None):
    columns, data = original_execute(filters)

    # Corrección: el reporte core de ERPNext agrega 'delay_in_payment' solo si
    # invoice.due_date existe, causando filas con menos elementos que columnas.
    # Esto provoca IndexError en normalize_result. Normalizamos las filas aquí.
    expected_length: int = len(columns)
    for row in data:
        if isinstance(row, list) and len(row) < expected_length:
            row.extend([None] * (expected_length - len(row)))

    party_col_idx = -1
    party_type_col_idx = -1
    doc_type_col_idx = -1

    for i, col in enumerate(columns):
        if col.get("fieldname") == "party":
            party_col_idx = i
        elif col.get("fieldname") == "party_type":
            party_type_col_idx = i
        elif col.get("fieldname") == "payment_document":
            doc_type_col_idx = i

    if party_col_idx != -1:
        rif_col = {
            "fieldname": "tax_id",
            "label": _("RIF"),
            "fieldtype": "Data",
            "width": 120,
        }
        columns.insert(party_col_idx + 1, rif_col)

        party_map = {}
        for row in data:
            if len(row) > party_type_col_idx and len(row) > party_col_idx:
                ptype = row[party_type_col_idx]
                party = row[party_col_idx]
                if ptype and party:
                    party_map.setdefault(ptype, set()).add(party)

        tax_ids = {}
        for ptype, parties in party_map.items():
            if frappe.db.has_column(ptype, "tax_id"):
                docs = frappe.get_all(ptype, filters={"name": ("in", list(parties))}, fields=["name", "tax_id"])
                for doc in docs:
                    tax_ids[(ptype, doc.name)] = doc.tax_id or ""

        for row in data:
            if isinstance(row, list):
                ptype = row[party_type_col_idx] if len(row) > party_type_col_idx else None
                party = row[party_col_idx] if len(row) > party_col_idx else None
                
                tax_id_val = tax_ids.get((ptype, party), "")
                row.insert(party_col_idx + 1, tax_id_val)
                
                if ptype:
                    row[party_type_col_idx] = _(ptype)
                
                if len(row) > doc_type_col_idx and row[doc_type_col_idx]:
                    row[doc_type_col_idx] = _(row[doc_type_col_idx])

    return columns, data

pp.execute = custom_execute
