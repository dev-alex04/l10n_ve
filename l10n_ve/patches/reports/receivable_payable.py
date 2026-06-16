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
            if vt and vn:
                vouchers_by_type.setdefault(vt, set()).add(vn)

    val_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            meta = frappe.get_meta(vt)
            fields_to_get = ["name"]
            has_branch_field = meta.has_field("branch")
            has_bill_no_field = meta.has_field("bill_no")
            has_bill_control_field = meta.has_field("bill_control")
            
            if has_branch_field:
                fields_to_get.append("branch")
            if has_bill_no_field:
                fields_to_get.append("bill_no")
            if has_bill_control_field:
                fields_to_get.append("bill_control")
                
            if len(fields_to_get) > 1:
                names_list = list(names)
                for chunk_start in range(0, len(names_list), 500):
                    chunk = names_list[chunk_start:chunk_start + 500]
                    docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=fields_to_get)
                    for d in docs:
                        val_map[(vt, d.name)] = {
                            "bill_no": d.get("bill_no") or "" if has_bill_no_field else "",
                            "bill_control": d.get("bill_control") or "" if has_bill_control_field else "",
                            "branch": d.get("branch") or "" if has_branch_field else ""
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

            # Evitamos traducir party_type, voucher_type y against_voucher_type directamente en las claves
            # del dataset para no romper el ruteo de enlaces (SlickGrid y custom HTML links en accounts_receivable.py)
            pass
    
    return columns, data, message, chart, report_summary, skip_total_row


def custom_fetch_ple_in_buffered_cursor(self):
    self.ple_entries = self.ple_query.run(as_dict=True)
    if self.filters.get("ve_branch"):
        self.ple_entries = filter_ple_by_ve_branch(self.ple_entries, self.filters.get("ve_branch"))
        
    for ple in self.ple_entries:
        self.init_voucher_balance(ple)
    for ple in self.ple_entries:
        self.update_voucher_balance(ple)
    delattr(self, "ple_entries")


def custom_fetch_ple_in_unbuffered_cursor(self):
    self.ple_entries = []
    if self.filters.get("ve_branch"):
        # Filtrar por sucursal requiere materializar los asientos para resolver
        # la sucursal de cada voucher antes de inicializar balances.
        raw_entries = []
        with frappe.db.unbuffered_cursor():
            for ple in self.ple_query.run(as_dict=True, as_iterator=True):
                raw_entries.append(ple)
        raw_entries = filter_ple_by_ve_branch(raw_entries, self.filters.get("ve_branch"))
        for ple in raw_entries:
            self.init_voucher_balance(ple)
            self.ple_entries.append(ple)
    else:
        # Sin filtro de sucursal, transmitir directamente desde el cursor sin
        # acumular en una lista intermedia (preserva el beneficio de memoria).
        with frappe.db.unbuffered_cursor():
            for ple in self.ple_query.run(as_dict=True, as_iterator=True):
                self.init_voucher_balance(ple)
                self.ple_entries.append(ple)
    for ple in self.ple_entries:
        self.update_voucher_balance(ple)
    delattr(self, "ple_entries")


def filter_ple_by_ve_branch(ple_entries, selected_branch):
    if not ple_entries:
        return []
        
    vouchers_by_type = {}
    for ple in ple_entries:
        vt = ple.get("voucher_type")
        vn = ple.get("voucher_no")
        if vt and vn:
            vouchers_by_type.setdefault(vt, set()).add(vn)
            
        avt = ple.get("against_voucher_type")
        avn = ple.get("against_voucher")
        if avt and avn:
            vouchers_by_type.setdefault(avt, set()).add(avn)

    branch_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            if not frappe.get_meta(vt).has_field("branch"):
                continue
            names_list = list(names)
            for chunk_start in range(0, len(names_list), 500):
                chunk = names_list[chunk_start:chunk_start + 500]
                docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=["name", "branch"])
                for d in docs:
                    branch_map[(vt, d.name)] = d.get("branch") or ""
        except Exception:
            pass

    filtered = []
    for ple in ple_entries:
        vt = ple.get("voucher_type")
        vn = ple.get("voucher_no")
        branch = branch_map.get((vt, vn), "")
        
        avt = ple.get("against_voucher_type")
        avn = ple.get("against_voucher")
        against_branch = branch_map.get((avt, avn), "") if avt and avn else ""
        
        if branch == selected_branch or against_branch == selected_branch:
            filtered.append(ple)
            
    return filtered


ReceivablePayableReport.run = custom_run
ReceivablePayableReport.fetch_ple_in_buffered_cursor = custom_fetch_ple_in_buffered_cursor
ReceivablePayableReport.fetch_ple_in_unbuffered_cursor = custom_fetch_ple_in_unbuffered_cursor
