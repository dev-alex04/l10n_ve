import frappe
from frappe import _
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport

original_run = ReceivablePayableReport.run

def custom_run(self, args):
    columns, data, message, chart, report_summary, skip_total_row = original_run(self, args)
    
    has_bill_no = False
    has_bill_control = False
    has_branch = False
    idx_voucher_no = -1
    
    for i, col in enumerate(columns):
        if isinstance(col, dict):
            if col.get("fieldname") == "bill_no":
                has_bill_no = True
            if col.get("fieldname") == "bill_control":
                has_bill_control = True
            if col.get("fieldname") == "branch":
                has_branch = True
            if col.get("fieldname") == "voucher_no":
                idx_voucher_no = i
                
    if not has_bill_no:
        columns.insert(idx_voucher_no + 1, {
            "label": _("Factura No."),
            "fieldname": "bill_no",
            "fieldtype": "Data",
            "width": 110
        })
        
    if not has_bill_control:
        current_idx_bill_no = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "bill_no":
                current_idx_bill_no = i
                break
        
        insert_idx = current_idx_bill_no + 1 if current_idx_bill_no != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("No. Control"),
            "fieldname": "bill_control",
            "fieldtype": "Data",
            "width": 110
        })

    if not has_branch:
        current_idx_bill_control = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "bill_control":
                current_idx_bill_control = i
                break
        
        insert_idx = current_idx_bill_control + 1 if current_idx_bill_control != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("Sucursal"),
            "fieldname": "branch",
            "fieldtype": "Link",
            "options": "VE Branch",
            "width": 110
        })

    vouchers_by_type = {}
    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if vt and vn and vt in ("Sales Invoice", "Purchase Invoice", "Payment Entry", "VE Sales Credit Note", "VE Sales Debit Note"):
                vouchers_by_type.setdefault(vt, set()).add(vn)

    val_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            fields_to_get = ["name", "branch"]
            if vt in ("Sales Invoice", "Purchase Invoice", "VE Sales Credit Note", "VE Sales Debit Note"):
                fields_to_get.extend(["bill_no", "bill_control"])
                
            docs = frappe.get_all(vt, filters={"name": ("in", list(names))}, fields=fields_to_get)
            for d in docs:
                val_map[(vt, d.name)] = {
                    "bill_no": d.get("bill_no") or "",
                    "bill_control": d.get("bill_control") or "",
                    "branch": d.get("branch") or ""
                }
        except Exception:
            pass

    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            key = (vt, vn)
            if key in val_map:
                row["bill_no"] = val_map[key]["bill_no"]
                row["bill_control"] = val_map[key]["bill_control"]
                row["branch"] = val_map[key]["branch"]
            else:
                if not row.get("bill_no"):
                    row["bill_no"] = ""
                if not row.get("bill_control"):
                    row["bill_control"] = ""
                if not row.get("branch"):
                    row["branch"] = ""

            if row.get("party_type") and isinstance(row.get("party_type"), str):
                row["party_type"] = _(row["party_type"])
            
            if row.get("voucher_type") and isinstance(row.get("voucher_type"), str):
                row["voucher_type"] = _(row["voucher_type"])
                
            if row.get("against_voucher_type") and isinstance(row.get("against_voucher_type"), str):
                row["against_voucher_type"] = _(row["against_voucher_type"])
    
    return columns, data, message, chart, report_summary, skip_total_row

ReceivablePayableReport.run = custom_run
