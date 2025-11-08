# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate, getdate
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher
class VATWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self):
        self.validate_address()
        self.validate_fiscal_period()

    def before_insert(self):
        company_doc = frappe.get_doc("Company", self.empresa)
        correlative_format = company_doc.vat_withholding_format

        final_voucher_number, final_next_correlative_number, year, month = \
            self._get_and_format_correlatives(correlative_format, company_doc.vat_withholding_correlative)

        self.voucher_number = final_voucher_number
        self.fiscal_period = f"{month}/{year}"

        company_doc.vat_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

    def on_trash(self):
        document_date = self.issue_date
        current_date = getdate(nowdate())

        if document_date:
            document_month_year = getdate(document_date).strftime('%Y-%m')
            current_month_year = current_date.strftime('%Y-%m')
        else:
            frappe.throw("No se puede determinar la fecha del comprobante para la validación.")

        if document_month_year != current_month_year:
            frappe.throw(
                f"No se puede eliminar el comprobante. Solo se permiten eliminaciones para el periodo actual ({current_month_year})."
            )


    def validate_fiscal_period(self):
        if not self.fiscal_period:
            return

        parts = self.fiscal_period.split('/')

        is_invalid_format = len(parts) != (2
                            or not parts[0].isdigit()
                            or not parts[1].isdigit()
                            or len(parts[0]) != 2
                            or len(parts[1]) != 4
                            )

        if is_invalid_format:
            frappe.throw(_("El Periodo Fiscal debe tener el formato MM/YYYY (ej: 10/2025)."))

        is_invalid_month = not (1 <= int(parts[0]) <= 12)
        if is_invalid_month:
            frappe.throw(_("El mes en el Periodo Fiscal no es válido."))

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
    default_currency = frappe.db.get_value('Company', company, 'default_currency')

    excluded_from_withholding = frappe.get_all(
        "VAT Withholding Voucher Item",
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
            {"name": ["not in", all_excluded_invoices]},
            ["Purchase Taxes and Charges", "charge_type", "=", "VAT Withholding"]
        ],
        fields=[
            "name", "bill_no", "bill_control", "posting_date", "grand_total",
            "total_exempt", "is_return", "is_debit_note", "total",
            "taxes_and_charges_added", "conversion_rate", "currency",
            "credit_note_no", "debit_note_no", "affected_invoice_number",
            "`tabPurchase Taxes and Charges`.rate as tax_rate",
            "`tabPurchase Taxes and Charges`.tax_amount as tax_amount_vat",
        ]
    )

    if not valid_invoices:
        return []

    invoice_names = [d.name for d in valid_invoices]

    vat_data = frappe.get_all(
        "Purchase Taxes and Charges",
        filters=[
            {"parenttype": "Purchase Invoice"},
            {"parent": ["in", invoice_names]},
            {"charge_type": "VAT"}
        ],
        fields=["parent", "rate"],
    )

    vat_map = {d.parent: d for d in vat_data}

    invoices_with_taxes = []
    processed_invoices = set()
    for item in valid_invoices:
        if item.name in processed_invoices:
            continue

        vat_details = vat_map.get(item.name, {})
        conversion_rate = item.conversion_rate
        rate = 1

        if default_currency != item.currency and conversion_rate:
            rate = conversion_rate

        grand_total = (item.grand_total or 0) * rate
        total = (item.total or 0) * rate
        total_exempt = (item.total_exempt or 0) * rate
        taxes_and_charges_added = (item.taxes_and_charges_added or 0) * rate
        tax_amount_vat = (item.tax_amount_vat or 0) * rate

        invoice_data = {
            "purchase_invoice": item.name,
            "bill_no": item.bill_no,
            "bill_control": item.bill_control,
            "posting_date": item.posting_date,
            "grand_total": abs(grand_total),
            "total": abs(total),
            "total_exempt": abs(total_exempt),
            "taxes_and_charges_added": abs(taxes_and_charges_added),
            "credit_note_no": item.credit_note_no,
            "debit_note_no": item.debit_note_no,
            "affected_invoice_number": item.affected_invoice_number,
            "is_return": item.is_return,
            "is_debit_note": item.is_debit_note,
            "rate": vat_details.get("rate", 0),
            "tax_amount_vat": abs(tax_amount_vat),
        }
        invoices_with_taxes.append(invoice_data)
        processed_invoices.add(item.name)

    return invoices_with_taxes
