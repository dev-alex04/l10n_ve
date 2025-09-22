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
    excluded_from_withholding_list = [d.purchase_invoice for d in excluded_from_withholding]

    # Consulta optimizada: obtiene los datos principales de la factura
    valid_invoices_list = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"name": ["not in", excluded_from_withholding_list]},
            {"status": "Paid"},
            ["Purchase Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=[
            "name",
            "bill_no",
            "bill_control",
            "posting_date",
            "grand_total",
            "total_exempt"
        ]
    )

    invoices_with_taxes = []
    for item in valid_invoices_list:

        tax_item = frappe.get_all(
            "Purchase Taxes and Charges",
            filters={
                "parent": item.name,
                "parenttype": "Purchase Invoice",
                "charge_type": "ISLR"
            },
            fields=["rate", "subtracting", "tax_amount", "code"],
            limit=1
        )

        payment_entry_name = frappe.get_value(
            "Payment Entry Reference",
            filters={
                "reference_doctype": "Purchase Invoice",
                "reference_name": item.name
            },
            fieldname="parent"
        )
        
        if tax_item:
            tax_data = tax_item[0]
            
            invoice_data = {
                "purchase_invoice": item.name,
                "bill_no": item.bill_no,
                "bill_control": item.bill_control,
                "posting_date": item.posting_date,
                "rate": tax_data.rate,
                "subtracting": tax_data.subtracting,
                "tax_amount": tax_data.tax_amount,
                "amount_paid": item.grand_total,
                "grand_total": item.grand_total,
                "total_exempt": item.total_exempt,
                "payment_entry_name": payment_entry_name,
                "taxes": tax_data
            }
            
            invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes