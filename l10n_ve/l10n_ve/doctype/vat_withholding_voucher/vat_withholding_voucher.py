# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate

class VATWithholdingVoucher(Document):

    def before_insert(self):
        company_doc = frappe.get_doc("Company", self.empresa)

        current_correlative_value = company_doc.vat_withholding_correlative

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

            template = company_doc.vat_withholding_format
            num_digits = len(template) - 6

        formatted_voucher_correlative = str(voucher_correlative_num).zfill(num_digits)
        formatted_next_correlative = str(next_correlative_num).zfill(num_digits)

        final_voucher_number = f"{current_year}{current_month}{formatted_voucher_correlative}"
        final_next_correlative_number = f"{current_year}{current_month}{formatted_next_correlative}"

        self.voucher_number = final_voucher_number

        company_doc.vat_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

@frappe.whitelist()
def get_vat_correlative(company_name):
    if not company_name:
        return None

    company_doc = frappe.get_doc("Company", company_name)

    correlative_value = company_doc.vat_withholding_correlative

    today = getdate(nowdate())
    current_year = str(today.year)
    current_month = f"{today.month:02d}"

    if correlative_value:
        last_correlative_part = correlative_value[6:]

        new_correlative = int(last_correlative_part)
        num_digits = len(last_correlative_part)

    else:
        new_correlative = 1
        template = company_doc.vat_withholding_format
        num_digits = len(template) - 6

    formatted_correlative = str(new_correlative).zfill(num_digits)

    final_withholding_number = f"{current_year}{current_month}{formatted_correlative}"

    return final_withholding_number

@frappe.whitelist()
def get_invoiced_purchase_invoices():
    invoices = frappe.get_list(
        "VAT Withholding Voucher Item",
        filters={"parenttype": "VAT Withholding Voucher"},
        fields=["purchase_invoice"]
    )
    return [d.purchase_invoice for d in invoices]

@frappe.whitelist()
def get_valid_invoices(supplier, start_date, end_date, company):

    excluded_from_withholding = frappe.get_all(
        "VAT Withholding Voucher Item",
        filters={"purchase_invoice": ["!=", ""]},
        fields=["purchase_invoice"]
    )
    excluded_from_withholding_list = [d.purchase_invoice for d in excluded_from_withholding]

    all_excluded_invoices = excluded_from_withholding_list

    valid_invoices = frappe.get_all(
        "Purchase Invoice",
        filters=[
            {"supplier": supplier},
            {"posting_date": ["between", [start_date, end_date]]},
            {"company": company},
            {"docstatus": 1},
            {"is_return": 0},
            {"name": ["not in", all_excluded_invoices]},
            ["Purchase Taxes and Charges", "charge_type", "=", "VAT Withholding"]
        ],
        fields=["name", "bill_no"]
    )

    valid_invoices_names = [d.name for d in valid_invoices]
    valid_invoices_bill_nos = [d.bill_no for d in valid_invoices]

    associated_credit_notes_names = []
    if valid_invoices_bill_nos:
        associated_credit_notes = frappe.get_all(
            "Purchase Invoice",
            filters={
                "is_return": 1,
                "docstatus": 1,
                "affected_invoice_number": ["in", valid_invoices_bill_nos]
            },
            fields=["name"]
        )
        associated_credit_notes_names = [d.name for d in associated_credit_notes]

    final_document_list = valid_invoices_names + associated_credit_notes_names

    invoices_with_taxes = []
    for item in final_document_list:
        invoice = frappe.get_doc("Purchase Invoice", item)
        rate = 0
        if invoice.taxes and len(invoice.taxes) > 0:
            tax_item = invoice.taxes[0]
            rate = tax_item.rate

        invoice_data = {
            "purchase_invoice": invoice.name,
            "bill_no": invoice.bill_no,
            "bill_control": invoice.bill_control,
            "posting_date": invoice.posting_date,
            "rate": rate,
            "grand_total": abs(invoice.grand_total),
            "total": abs(invoice.total),
            "total_exempt": abs(invoice.total_exempt),
            "taxes_and_charges_added": abs(invoice.taxes_and_charges_added),
            "taxes_and_charges_deducted": abs(invoice.taxes_and_charges_deducted),
            "credit_note_no": invoice.credit_note_no,
            "debit_note_no": invoice.debit_note_no,
            "affected_invoice_number": invoice.affected_invoice_number,
            "is_return": invoice.is_return,
            "taxes": invoice.get("taxes")
        }
        invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes
