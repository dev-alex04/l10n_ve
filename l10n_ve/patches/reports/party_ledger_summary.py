import frappe
from frappe import _
from erpnext.accounts.report.customer_ledger_summary.customer_ledger_summary import PartyLedgerSummaryReport

original_get_columns = PartyLedgerSummaryReport.get_columns
original_get_data = PartyLedgerSummaryReport.get_data

def custom_get_columns(self):
    columns = original_get_columns(self)
    rif_col = {
        "label": _("RIF"),
        "fieldname": "tax_id",
        "fieldtype": "Data",
        "width": 120
    }
    if len(columns) > 1 and columns[1].get("fieldname") == "party_name":
        columns.insert(2, rif_col)
    else:
        columns.insert(1, rif_col)
    return columns

def custom_get_data(self):
    data = original_get_data(self)
    if not data:
        return data

    party_ids = [row.get("party") for row in data if row.get("party")]
    if not party_ids:
        return data

    tax_ids = frappe.get_all(self.filters.party_type, 
                             filters={"name": ["in", party_ids]}, 
                             fields=["name", "tax_id"])
    tax_map = {d.name: d.tax_id for d in tax_ids}

    for row in data:
        row["tax_id"] = tax_map.get(row.get("party"))
    
    return data

PartyLedgerSummaryReport.get_columns = custom_get_columns
PartyLedgerSummaryReport.get_data = custom_get_data
def custom_get_return_invoices(self):
    from frappe import scrub
    if not self.parties:
        self.return_invoices = []
        return
        

    doctype = "Sales Invoice" if self.filters.party_type == "Customer" else "Purchase Invoice"
    filters = {
        "is_return": 1,
        "docstatus": 1,
        "posting_date": ["between", [self.filters.from_date, self.filters.to_date]],
        scrub(self.filters.party_type): ["in", self.parties],
    }
    self.return_invoices = frappe.get_all(doctype, filters=filters, pluck="name") or []

    # Incluir DocTypes específicos de la localización venezolana
    if self.filters.party_type == "Customer":
        ve_cns = frappe.get_all("VE Sales Credit Note", filters={
            "docstatus": 1,
            "posting_date": ["between", [self.filters.from_date, self.filters.to_date]],
            "customer": ["in", self.parties]
        }, pluck="name")
        if ve_cns:
            self.return_invoices.extend(ve_cns)
    elif self.filters.party_type == "Supplier":
        ve_dns = frappe.get_all("VE Purchase Debit Note", filters={
            "docstatus": 1,
            "posting_date": ["between", [self.filters.from_date, self.filters.to_date]],
            "supplier": ["in", self.parties]
        }, pluck="name")
        if ve_dns:
            self.return_invoices.extend(ve_dns)

PartyLedgerSummaryReport.get_return_invoices = custom_get_return_invoices
