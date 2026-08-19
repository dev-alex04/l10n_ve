import frappe
from frappe import _
from frappe.utils import cint
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport

original_run = ReceivablePayableReport.run

DOC_TYPE_TRANSLATIONS = {
    "Sales Invoice": _("Factura de Venta"),
    "Journal Entry": _("Entrada de Diario"),
    "Payment Entry": _("Entrada de Pago"),
    "Purchase Invoice": _("Factura de Compra"),
    "Sales Order": _("Orden de Venta"),
    "Purchase Order": _("Orden de Compra"),
    "Delivery Note": _("Nota de Entrega"),
    "Purchase Receipt": _("Recibo de Compra"),
    "VE Sales Credit Note": _("Nota de Crédito de Ventas"),
    "VE Sales Debit Note": _("Nota de Débito de Ventas"),
    "VE Purchase Credit Note": _("Nota de Crédito de Compras"),
    "VE Purchase Debit Note": _("Nota de Débito de Compras"),
}


def custom_run(self, args):
    columns, data, message, chart, report_summary, skip_total_row = original_run(self, args)
    
    is_receivable = (
        getattr(self, "account_type", None) == "Receivable"
        or (self.filters and self.filters.get("party_type") == "Customer")
        or getattr(self, "account_type", None) != "Payable"
    )

    has_bill_no = False
    has_bill_control = False
    has_branch = False
    has_special_taxpayer = False
    has_vat_withholding = False
    has_islr_withholding = False
    
    idx_voucher_no = -1
    idx_customer_name = -1
    idx_party = -1
    
    for i, col in enumerate(columns):
        if isinstance(col, dict):
            fn = col.get("fieldname")
            if fn == "bill_no":
                has_bill_no = True
                col["fieldtype"] = "HTML"
            elif fn in ("voucher_type", "against_voucher_type", "ve_voucher_type"):
                col["fieldtype"] = "Data"
            elif fn == "bill_control":
                has_bill_control = True
            elif fn == "branch":
                has_branch = True
            elif fn == "is_special_taxpayer":
                has_special_taxpayer = True
            elif fn == "vat_withholding_voucher_number":
                has_vat_withholding = True
            elif fn == "islr_receipt_number":
                has_islr_withholding = True
            elif fn == "voucher_no":
                idx_voucher_no = i
            elif fn == "customer_name":
                idx_customer_name = i
            elif fn == "party":
                idx_party = i
                
    if is_receivable and not has_special_taxpayer:
        insert_idx = (idx_customer_name + 1) if idx_customer_name != -1 else ((idx_party + 1) if idx_party != -1 else 0)
        columns.insert(insert_idx, {
            "label": _("Contribuyente Especial"),
            "fieldname": "is_special_taxpayer",
            "fieldtype": "Data",
            "width": 110
        })

    if not has_bill_no:
        current_idx_vno = -1
        for i, col in enumerate(columns):
            if isinstance(col, dict) and col.get("fieldname") == "voucher_no":
                current_idx_vno = i
                break
        insert_idx = current_idx_vno + 1 if current_idx_vno != -1 else idx_voucher_no + 1
        columns.insert(insert_idx, {
            "label": _("Factura No."),
            "fieldname": "bill_no",
            "fieldtype": "HTML",
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

    if is_receivable:
        if not has_vat_withholding:
            idx_ref = -1
            for i, col in enumerate(columns):
                if isinstance(col, dict) and col.get("fieldname") in ("branch", "bill_control", "bill_no", "voucher_no"):
                    idx_ref = i
            insert_idx = idx_ref + 1 if idx_ref != -1 else len(columns)
            columns.insert(insert_idx, {
                "label": _("Comprobante IVA"),
                "fieldname": "vat_withholding_voucher_number",
                "fieldtype": "Data",
                "width": 130
            })

        if not has_islr_withholding:
            idx_vat = -1
            for i, col in enumerate(columns):
                if isinstance(col, dict) and col.get("fieldname") == "vat_withholding_voucher_number":
                    idx_vat = i
                    break
            insert_idx = idx_vat + 1 if idx_vat != -1 else len(columns)
            columns.insert(insert_idx, {
                "label": _("Comprobante ISLR"),
                "fieldname": "islr_receipt_number",
                "fieldtype": "Data",
                "width": 130
            })

    vouchers_by_type = {}
    parties = set()
    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            if vt and vn:
                vouchers_by_type.setdefault(vt, set()).add(vn)
            party = row.get("party") or row.get("customer")
            if party and party != "Total":
                parties.add(party)

    customer_map = {}
    if is_receivable and parties:
        parties_list = list(parties)
        for chunk_start in range(0, len(parties_list), 500):
            chunk = parties_list[chunk_start:chunk_start + 500]
            try:
                customers = frappe.get_all(
                    "Customer",
                    filters={"name": ("in", chunk)},
                    fields=["name", "is_special_taxpayer", "tabulator_islr"]
                )
                for c in customers:
                    c_name = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                    c_special = c.get("is_special_taxpayer") if isinstance(c, dict) else getattr(c, "is_special_taxpayer", 0)
                    c_tab = c.get("tabulator_islr") if isinstance(c, dict) else getattr(c, "tabulator_islr", "")
                    if c_name:
                        customer_map[c_name] = {
                            "is_special_taxpayer": cint(c_special),
                            "tabulator_islr": (c_tab or "").strip()
                        }
            except Exception:
                pass

    val_map = {}
    for vt, names in vouchers_by_type.items():
        try:
            meta = frappe.get_meta(vt)
            fields_to_get = ["name"]
            has_branch_field = meta.has_field("branch")
            has_bill_no_field = meta.has_field("bill_no")
            has_bill_control_field = meta.has_field("bill_control")
            has_vat_voucher_field = meta.has_field("vat_withholding_voucher_number")
            has_islr_voucher_field = meta.has_field("islr_receipt_number")
            has_special_taxpayer_field = meta.has_field("is_special_taxpayer")
            has_customer_field = meta.has_field("customer")
            
            if has_branch_field:
                fields_to_get.append("branch")
            if has_bill_no_field:
                fields_to_get.append("bill_no")
            if has_bill_control_field:
                fields_to_get.append("bill_control")
            if is_receivable:
                if has_vat_voucher_field:
                    fields_to_get.append("vat_withholding_voucher_number")
                if has_islr_voucher_field:
                    fields_to_get.append("islr_receipt_number")
                if has_special_taxpayer_field:
                    fields_to_get.append("is_special_taxpayer")
                if has_customer_field:
                    fields_to_get.append("customer")
                
            if len(fields_to_get) > 1:
                names_list = list(names)
                for chunk_start in range(0, len(names_list), 500):
                    chunk = names_list[chunk_start:chunk_start + 500]
                    docs = frappe.get_all(vt, filters={"name": ("in", chunk)}, fields=fields_to_get)
                    for d in docs:
                        d_name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
                        if not d_name:
                            continue
                        val_map[(vt, d_name)] = {
                            "bill_no": d.get("bill_no") or "" if has_bill_no_field else "",
                            "bill_control": d.get("bill_control") or "" if has_bill_control_field else "",
                            "branch": d.get("branch") or "" if has_branch_field else "",
                            "vat_withholding_voucher_number": d.get("vat_withholding_voucher_number") or "" if has_vat_voucher_field else "",
                            "islr_receipt_number": d.get("islr_receipt_number") or "" if has_islr_voucher_field else "",
                            "is_special_taxpayer": cint(d.get("is_special_taxpayer")) if has_special_taxpayer_field else 0,
                            "customer": d.get("customer") or "" if has_customer_field else "",
                        }
        except Exception:
            pass

    taxes_map = {}
    if is_receivable:
        inv_types = [t for t in ("Sales Invoice", "VE Sales Credit Note") if t in vouchers_by_type]
        all_inv_names = []
        for it in inv_types:
            all_inv_names.extend(vouchers_by_type[it])
        if all_inv_names:
            for chunk_start in range(0, len(all_inv_names), 500):
                chunk = all_inv_names[chunk_start:chunk_start + 500]
                try:
                    tax_rows = frappe.get_all(
                        "Sales Taxes and Charges",
                        filters={
                            "parent": ("in", chunk),
                            "parenttype": ("in", inv_types),
                            "charge_type": ("in", ["VAT Withholding", "ISLR"]),
                            "tax_amount": ("!=", 0),
                        },
                        fields=["parent", "charge_type"]
                    )
                    for tr in tax_rows:
                        p = tr.get("parent") if isinstance(tr, dict) else getattr(tr, "parent", None)
                        ct = tr.get("charge_type") if isinstance(tr, dict) else getattr(tr, "charge_type", None)
                        if p and ct:
                            taxes_map.setdefault(p, set()).add(ct)
                except Exception:
                    pass

    for row in data:
        if isinstance(row, dict):
            vt = row.get("voucher_type")
            vn = row.get("voucher_no")
            party = row.get("party") or row.get("customer")

            is_subtotal_or_total = bool(
                row.get("bold")
                or row.get("is_total_row")
                or party == "Total"
                or (not vn and not party)
            )

            key = (vt, vn)
            doc_vals = val_map.get(key, {})

            raw_bill_no = doc_vals.get("bill_no", "") if key in val_map else (row.get("bill_no") or "")
            if raw_bill_no and vt and vn and not is_subtotal_or_total:
                if str(raw_bill_no).startswith("<a "):
                    row["bill_no"] = raw_bill_no
                else:
                    doctype_slug = str(vt).lower().replace(" ", "-")
                    row["bill_no"] = f'<a href="/app/{doctype_slug}/{vn}">{raw_bill_no}</a>'
            else:
                row["bill_no"] = raw_bill_no or ""

            if key in val_map:
                row["bill_control"] = doc_vals.get("bill_control", "")
                row["branch"] = doc_vals.get("branch", "")
            else:
                if not row.get("bill_control"):
                    row["bill_control"] = ""
                if not row.get("branch"):
                    row["branch"] = ""

            if is_receivable:
                if is_subtotal_or_total:
                    row["is_special_taxpayer"] = ""
                    row["vat_withholding_voucher_number"] = ""
                    row["islr_receipt_number"] = ""
                else:
                    cust_name = party or doc_vals.get("customer")
                    cust_info = customer_map.get(cust_name, {})
                    is_special = bool(cust_info.get("is_special_taxpayer") or doc_vals.get("is_special_taxpayer"))

                    row["is_special_taxpayer"] = _("Sí") if is_special else (_("No") if cust_name else "")

                    is_invoice_doc = vt in ("Sales Invoice", "VE Sales Credit Note", "VE Sales Debit Note")

                    # Comprobante IVA
                    vat_v = (doc_vals.get("vat_withholding_voucher_number") or row.get("vat_withholding_voucher_number") or "").strip()
                    if vat_v and vat_v.lower() != "none":
                        row["vat_withholding_voucher_number"] = vat_v
                    elif is_invoice_doc and (is_special or (vn and "VAT Withholding" in taxes_map.get(vn, set()))):
                        row["vat_withholding_voucher_number"] = _("Pendiente")
                    else:
                        row["vat_withholding_voucher_number"] = _("No aplica")

                    # Comprobante ISLR
                    islr_v = (doc_vals.get("islr_receipt_number") or row.get("islr_receipt_number") or "").strip()
                    has_islr_tab = bool(cust_info.get("tabulator_islr") and cust_info.get("tabulator_islr") != "None")
                    if islr_v and islr_v.lower() != "none":
                        row["islr_receipt_number"] = islr_v
                    elif is_invoice_doc and (is_special or has_islr_tab or (vn and "ISLR" in taxes_map.get(vn, set()))):
                        row["islr_receipt_number"] = _("Pendiente")
                    else:
                        row["islr_receipt_number"] = _("No aplica")

            if not is_subtotal_or_total:
                if row.get("voucher_type"):
                    vt_raw = row["voucher_type"]
                    translated_vt = DOC_TYPE_TRANSLATIONS.get(vt_raw, _(vt_raw))
                    row["ve_voucher_type"] = translated_vt
                    row["voucher_type"] = translated_vt

                if row.get("against_voucher_type"):
                    avt_raw = row["against_voucher_type"]
                    row["against_voucher_type"] = DOC_TYPE_TRANSLATIONS.get(avt_raw, _(avt_raw))

    if is_receivable and self.filters and self.filters.get("withholding_voucher_status"):
        w_filter = self.filters.get("withholding_voucher_status")
        filtered_data = []
        pendiente_str = _("Pendiente")
        no_aplica_str = _("No aplica")

        for row in data:
            if not isinstance(row, dict):
                continue

            is_subtotal_or_total = bool(
                row.get("bold")
                or row.get("is_total_row")
                or (row.get("party") == "Total")
                or (not row.get("voucher_no") and not row.get("party"))
            )
            if is_subtotal_or_total:
                continue

            vat_val = row.get("vat_withholding_voucher_number")
            islr_val = row.get("islr_receipt_number")

            match = False
            if w_filter == "Con Comprobantes Pendientes":
                match = (vat_val == pendiente_str or islr_val == pendiente_str)
            elif w_filter == "Pendiente IVA":
                match = (vat_val == pendiente_str)
            elif w_filter == "Pendiente ISLR":
                match = (islr_val == pendiente_str)
            elif w_filter == "Con Comprobantes Registrados":
                has_vat_reg = bool(vat_val and vat_val not in (pendiente_str, no_aplica_str))
                has_islr_reg = bool(islr_val and islr_val not in (pendiente_str, no_aplica_str))
                match = has_vat_reg or has_islr_reg
            elif w_filter == "No aplica":
                match = (vat_val == no_aplica_str and islr_val == no_aplica_str)

            if match:
                filtered_data.append(row)

        data = filtered_data
    
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
                    d_name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
                    if d_name:
                        branch_map[(vt, d_name)] = d.get("branch") or ""
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
