
import frappe
from frappe import _
import erpnext.accounts.report.trial_balance_for_party.trial_balance_for_party as tbfp

original_execute = tbfp.execute


def custom_execute(filters=None):
    columns, data = original_execute(filters)

    party_type = (filters or {}).get("party_type", "")

    for col in columns:
        if col.get("fieldname") == "party_name":
            col["label"] = _("Nombre")

    if party_type not in ("Customer", "Supplier"):
        return columns, data

    tax_ids = frappe._dict(
        frappe.get_all(party_type, fields=["name", "tax_id"], as_list=True)
    )


    rif_col = {
        "fieldname": "tax_id",
        "label": _("RIF"),
        "fieldtype": "Data",
        "width": 140,
    }

    insert_after = (
        "party_name"
        if any(c.get("fieldname") == "party_name" for c in columns)
        else "party"
    )

    for i, col in enumerate(columns):
        if col.get("fieldname") == insert_after:
            columns.insert(i + 1, rif_col)
            break


    insert_bal = len(columns)
    for i, col in enumerate(columns):
        if col.get("fieldname") == "closing_credit":
            insert_bal = i + 1
            break
            
    columns.insert(insert_bal, {
        "fieldname": "net_balance",
        "label": _("Saldo"),
        "fieldtype": "Currency",
        "options": "currency",
        "width": 130
    })

    total_marker = "'" + _("Totals") + "'"
    for row in data:
        if isinstance(row, dict):
            party_name = row.get("party", "")
            if party_name != total_marker:
                row["tax_id"] = tax_ids.get(party_name, "")
                
            closing_dr = row.get("closing_debit", 0.0)
            closing_cr = row.get("closing_credit", 0.0)
            
            if party_type == "Supplier":
                row["net_balance"] = closing_cr - closing_dr
            else:
                row["net_balance"] = closing_dr - closing_cr

    return columns, data


tbfp.execute = custom_execute
