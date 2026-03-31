import frappe
from frappe import _
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport

original_run = ReceivablePayableReport.run

def custom_run(self, args):
    columns, data, message, chart, report_summary, skip_total_row = original_run(self, args)
    
    has_bill_no = False
    has_bill_control = False
    idx_voucher_no = -1
    
    for i, col in enumerate(columns):
        if isinstance(col, dict):
            if col.get("fieldname") == "bill_no":
                has_bill_no = True
            if col.get("fieldname") == "bill_control":
                has_bill_control = True
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

    sales_invoices = set()
    purchase_invoices = set()
    
    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if vt == "Sales Invoice" and vn:
                sales_invoices.add(vn)
            elif vt == "Purchase Invoice" and vn:
                purchase_invoices.add(vn)

    val_map = {}
    if sales_invoices:
        si_docs = frappe.get_all("Sales Invoice",
                                  filters={"name": ("in", list(sales_invoices))},
                                  fields=["name", "bill_no", "bill_control"])
        for d in si_docs:
            val_map[d.name] = {"bill_no": d.bill_no or "", "bill_control": d.bill_control or ""}
            
    if purchase_invoices:
        pi_docs = frappe.get_all("Purchase Invoice",
                                  filters={"name": ("in", list(purchase_invoices))},
                                  fields=["name", "bill_no", "bill_control"])
        for d in pi_docs:
            val_map[d.name] = {"bill_no": d.bill_no or "", "bill_control": d.bill_control or ""}

    for row in data:
        if isinstance(row, dict):
            vn = row.get("voucher_no")
            if vn in val_map:
                row["bill_no"] = val_map[vn]["bill_no"]
                row["bill_control"] = val_map[vn]["bill_control"]
            else:
                if not row.get("bill_no"):
                    row["bill_no"] = ""
                if not row.get("bill_control"):
                    row["bill_control"] = ""

            if row.get("party_type") and isinstance(row.get("party_type"), str):
                row["party_type"] = _(row["party_type"])
            
            if row.get("voucher_type") and isinstance(row.get("voucher_type"), str):
                row["voucher_type"] = _(row["voucher_type"])
                
            if row.get("against_voucher_type") and isinstance(row.get("against_voucher_type"), str):
                row["against_voucher_type"] = _(row["against_voucher_type"])
    
    return columns, data, message, chart, report_summary, skip_total_row

ReceivablePayableReport.run = custom_run
