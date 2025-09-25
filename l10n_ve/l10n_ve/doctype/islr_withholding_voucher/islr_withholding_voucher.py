# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate
from l10n_ve.utils.utils import format_amounts

class ISLRWithholdingVoucher(Document):

    def before_print(self, settings):
        main_fields = [
            "totals_total_exempt",
            "totals_tax_amount",
        ]

        child_fields = [
            "grand_total",
            "total_exempt",
            "subtracting",
            "tax_amount"
        ]

        format_amounts(self, main_fields, child_fields, child_table_field="islr_withholding_voucher_item")
    
    def before_insert(self):
        company_doc = frappe.get_doc("Company", self.empresa)

        current_correlative_value = company_doc.islr_withholding_correlative

        today = getdate(nowdate())
        current_year = str(today.year)
        current_month = f"{today.month:02d}"

        if current_correlative_value:
            last_correlative_part = current_correlative_value[6:]
            voucher_correlative_num = int(last_correlative_part)

            next_correlative_num = int(last_correlative_part) + 1
            num_digits = len(last_correlative_part)
        else:
            voucher_correlative_num = 1
            next_correlative_num = 2
            
            template = company_doc.islr_withholding_format
            num_digits = len(template) - 6

        formatted_voucher_correlative = str(voucher_correlative_num).zfill(num_digits)
        formatted_next_correlative = str(next_correlative_num).zfill(num_digits)

        final_voucher_number = f"{current_year}{current_month}{formatted_voucher_correlative}"
        final_next_correlative_number = f"{current_year}{current_month}{formatted_next_correlative}"

        self.voucher_number = final_voucher_number

        company_doc.islr_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_vat_correlative(company_name):
    if not company_name:
        return
    
    company_doc = frappe.get_doc("Company", company_name)
    
    correlative_value = company_doc.islr_withholding_correlative
    
    today = getdate(nowdate())
    current_year = str(today.year)
    current_month = f"{today.month:02d}"

    if correlative_value:
        last_correlative_part = correlative_value[6:]
        
        new_correlative = int(last_correlative_part)
        num_digits = len(last_correlative_part)
            
    else:
        new_correlative = 1
        template = company_doc.islr_withholding_format
        num_digits = len(template) - 6
    
    formatted_correlative = str(new_correlative).zfill(num_digits)
    
    final_withholding_number = f"{current_year}{current_month}{formatted_correlative}"
    
    return final_withholding_number

@frappe.whitelist()
def get_valid_invoices(supplier, start_date, end_date, company):
    excluded_from_withholding = frappe.get_all(
        "ISLR Withholding Voucher Item",
        filters={"purchase_invoice": ["!=", ""]},
        fields=["purchase_invoice"]
    )
    all_excluded_invoices = [d.purchase_invoice for d in excluded_from_withholding]

    valid_invoices = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"is_return": 0}, 
            {"is_debit_note": 0},
            {"status": "Paid"},
            {"name": ["not in", all_excluded_invoices]},
            ["Purchase Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=["name", "bill_no"]
    )

    valid_invoices_names = [d.name for d in valid_invoices]
    valid_invoices_bill_nos = [d.bill_no for d in valid_invoices]

    associated_credit_notes_names = []
    
    associated_credit_notes = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"is_return": 1},
            {"is_debit_note": 0},
            {"name": ["not in", all_excluded_invoices]},
            ["Purchase Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=["name"]
    )
    associated_credit_notes_names = [d.name for d in associated_credit_notes]

    associated_debit_notes_names = []
    
    associated_debit_notes = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"is_return": 0},
            {"is_debit_note": 1},
            {"name": ["not in", all_excluded_invoices]},
            ["Purchase Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=["name"]
    )
    associated_debit_notes_names = [d.name for d in associated_debit_notes]

    final_document_list = valid_invoices_names + associated_credit_notes_names + associated_debit_notes_names
    
    if not final_document_list:
        return []

    all_tax_items = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parent": ["in", final_document_list],
            "parenttype": "Purchase Invoice",
            "charge_type": "ISLR"
        },
        fields=["parent", "rate", "subtracting", "tax_amount", "code"]
    )
    tax_items_map = {item.pop("parent"): item for item in all_tax_items}

    all_payment_entries = frappe.get_all(
        "Payment Entry Reference",
        filters={
            "reference_doctype": "Purchase Invoice",
            "reference_name": ["in", final_document_list]
        },
        fields=["reference_name", "parent"],
        order_by="creation desc"
    )
    
    payment_entries_map = {}
    for pe in all_payment_entries:
        if pe.reference_name not in payment_entries_map:
            payment_entries_map[pe.reference_name] = pe.parent
    
    all_invoices_data = frappe.get_all(
        "Purchase Invoice",
        filters={"name": ["in", final_document_list]},
        fields=[
            "name", "bill_no", "bill_control", "posting_date", "grand_total",
            "total_exempt", "is_return", "is_debit_note", "total", 
            "taxes_and_charges_added", "taxes_and_charges_deducted", 
            "credit_note_no", "debit_note_no", "affected_invoice_number"
        ]
    )

    invoices_with_taxes = []
    
    for item in all_invoices_data:
        tax_data = tax_items_map.get(item.name)
        
        if tax_data:

            doc_no = (
                (item.credit_note_no or "") if item.is_return else
                (item.debit_note_no or "") if item.is_debit_note else
                (item.bill_no or "")
            )

            doc_type = (
                "NC" if item.is_return else
                "ND" if item.is_debit_note else
                "FACT"
            )
            
            invoice_data = {
                "purchase_invoice": item.name,
                "doc_no": doc_no,
                "doc_type": doc_type,
                "bill_control": item.bill_control,
                "posting_date": item.posting_date,
                "rate": tax_data.rate,
                "subtracting": tax_data.subtracting,
                "tax_amount": tax_data.tax_amount,
                "grand_total": abs(item.grand_total),
                "total": abs(item.total),
                "total_exempt": abs(item.total_exempt),
                "taxes_and_charges_added": abs(item.taxes_and_charges_added),
                "taxes_and_charges_deducted": abs(item.taxes_and_charges_deducted),
                "is_return": item.is_return,
                "is_debit_note": item.is_debit_note,
                "credit_note_no": item.credit_note_no,
                "debit_note_no": item.debit_note_no,
                "affected_invoice_number": item.affected_invoice_number,
                "amount_paid": abs(item.grand_total),
                "payment_entry_name": payment_entries_map.get(item.name),
                "taxes": tax_data
            }
            
            invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes