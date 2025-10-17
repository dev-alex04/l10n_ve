# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import nowdate, getdate
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher
from l10n_ve.utils.utils import format_amounts

class ISLRWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self):
        self.validate_address()

    def before_print(self, settings):
        company_tax_id = frappe.db.get_value("Company", self.empresa, "tax_id")
        supplier_tax_id = frappe.db.get_value("Supplier", self.supplier, "tax_id")

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

        self.company_tax_id = company_tax_id or "N/A"
        self.supplier_tax_id = supplier_tax_id or "N/A"
        format_amounts(self, main_fields, child_fields, child_table_field="islr_withholding_voucher_item")

    def before_insert(self):
        company_doc = frappe.get_doc("Company", self.empresa)
        correlative_format = company_doc.islr_withholding_format

        final_voucher_number, final_next_correlative_number = \
            self._get_and_format_correlatives(correlative_format, company_doc.islr_withholding_correlative)

        self.voucher_number = final_voucher_number
        self.posting_date = nowdate()

        company_doc.islr_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

    def on_trash(self):
        document_date = self.posting_date
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

@frappe.whitelist()
def get_valid_invoices(supplier, start_date, end_date, company):
    type_of_person = frappe.db.get_value("Supplier", supplier, "type_of_person")

    if not type_of_person:
        frappe.throw(_("El Proveedor debe tener un 'Tipo de Persona' definido para procesar retenciones ISLR."))

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
            {"name": ["not in", all_excluded_invoices]},
        ],
        fields=["name", "bill_no", "bill_control", "posting_date", "grand_total",
            "total_exempt", "is_return", "is_debit_note", "total",
            "taxes_and_charges_added", "taxes_and_charges_deducted",
            "credit_note_no", "debit_note_no", "affected_invoice_number",
        ]
    )

    valid_invoices_names = [d.name for d in valid_invoices]

    approved_payment_entries = frappe.get_all(
        "Payment Entry",
        filters=[
            {"docstatus": 1},
            {"company": company},
            {"party_type": "Supplier"},
            {"party": supplier},
            ["Advance Taxes and Charges", "charge_type", "=", "ISLR"]
        ],
        fields=["name", "paid_amount"]
    )
    approved_payment_entry_names = [d.name for d in approved_payment_entries]
    paid_amount_map = {d.name: d.paid_amount or 0 for d in approved_payment_entries}

    islr_references = frappe.get_all(
        "Payment Entry Reference",
        filters={
            "reference_doctype": "Purchase Invoice",
            "reference_name": ["in", valid_invoices_names],
            "parent": ["in", approved_payment_entry_names],
            "islr_amount": [">", 0]
        },
        fields=[
            "parent", "reference_name", "islr_concept", "islr_base_amount", "islr_amount"
        ],
        order_by="creation desc"
    )

    islr_concept_names = {ref.islr_concept for ref in islr_references if ref.islr_concept}
    final_islr_data_map = {}

    concept_codes = frappe.get_all(
        "Tabulator ISLR",
        filters={"name": ["in", list(islr_concept_names)]},
        fields=["name", "codigo"]
    )
    concept_code_map = {str(d.name): d.codigo for d in concept_codes}

    islr_aliquots = frappe.get_all(
        "Tabulator ISLR Aliquots",
        filters={
            "parent": ["in", list(islr_concept_names)],
            "types_of_person": type_of_person
        },
        fields=["parent", "aliquot", "subtracting"]
    )
    aliquot_details_map = {d.parent: d for d in islr_aliquots}

    for ref in islr_references:
        invoice_name = ref.reference_name

        if ref.islr_concept and invoice_name not in final_islr_data_map:

            concept_name = ref.islr_concept
            aliquot_details = aliquot_details_map.get(concept_name, {})

            final_islr_data_map[invoice_name] = {
                "payment_entry_name": ref.parent,
                "islr_base_amount": ref.islr_base_amount or 0,
                "islr_amount": ref.islr_amount or 0,
                "code": concept_code_map.get(concept_name),
                "rate": aliquot_details.get("aliquot"),
                "subtracting": aliquot_details.get("subtracting"),
            }

    invoices_with_taxes = []

    for item in valid_invoices:
        islr_details = final_islr_data_map.get(item.name)

        if not islr_details:
            continue

        payment_entry_name = islr_details.get("payment_entry_name")
        paid_amount = paid_amount_map.get(payment_entry_name, 0)

        invoice_data = {
            "purchase_invoice": item.name,
            "doc_no": item.bill_no,
            "doc_type": "FACT",
            "bill_control": item.bill_control,
            "posting_date": item.posting_date,
            "rate": islr_details.get("rate", 0),
            "subtracting": abs(islr_details.get("subtracting", 0)),
            "islr_amount": abs(islr_details.get("islr_amount", 0)),
            "code": islr_details.get("code", ""),
            "islr_base_amount": abs(islr_details.get("islr_base_amount", 0)),
            "grand_total": abs(item.grand_total),
            "total": abs(item.total),
            "affected_invoice_number": item.affected_invoice_number,
            "paid_amount": abs(paid_amount),
            "payment_entry_name": payment_entry_name,
        }

        invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes