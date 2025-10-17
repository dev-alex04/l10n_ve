from collections import defaultdict

import frappe
from frappe import _, _dict

from erpnext.accounts.doctype.payment_entry.payment_entry import (
    PaymentEntry,
    get_payment_entry,
    validate_inclusive_tax,

)
from erpnext.controllers.accounts_controller import (
    validate_taxes_and_charges,
)
from l10n_ve.overrides import company


class CustomPaymentEntry(PaymentEntry):

    def apply_taxes(self) -> None:

        # Se sobreescribe esta funcion
        # Para incrustar self.set_taxes_withholding()

        self.initialize_taxes()
        self.set_taxes_withholding()
        self.determine_exclusive_rate()
        self.calculate_taxes()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_taxes_withholding  se encargara de esto
        """
        return

    def initialize_taxes(self) -> None:

        # Se sobreescribe esta funcion
        # Para avitar que el campo tax_amonunt se incialice en 0
        # ya que ese monto ya se carga desde las funciones
        # self.set_taxes_withholding() y self.set_islr_concept()

        for tax in self.get("taxes"):
            validate_taxes_and_charges(tax)
            validate_inclusive_tax(tax, self)

            tax_fields = [
                "total",
                "tax_fraction_for_current_item",
                "grand_total_fraction_for_current_item"
            ]

            for fieldname in tax_fields:
                tax.set(fieldname, 0.0)

        self.paid_amount_after_tax = self.base_paid_amount

    def set_taxes_withholding(self) -> None:

        documents_map = {}

        for reference in self.references or []:

            if reference.reference_doctype not in documents_map:
                documents_map[reference.reference_doctype] = []

            documents_map[reference.reference_doctype].append(reference.reference_name)

        # Ya que el ISLR se carga desde la funciòn set_islr_concept,
        # aquí limpiamos la tabla de impuestos, dejando sólo los impuestos
        # de ISLR

        if bool(documents_map):
            self.taxes = [
                tax for tax in self.taxes or []
                if tax.charge_type in ["ISLR", "IGTF"]
            ]

        for doctype, docnames in documents_map.items():

            doc_type = doctype.split(' ')[0]

            taxes = frappe.db.get_all(
                f'{doc_type} Taxes and Charges',
                filters={
                    'docstatus': 1,
                    'parent': ['in', docnames],
                    'is_tax_withholding_account': True,
                },
                fields=[
                    'rate',
                    'tax_amount',
                    'description',
                    'charge_type',
                    'account_head',
                    'add_deduct_tax',
                ])

            for tax in taxes:
                self.append('taxes', tax)

    @frappe.whitelist()
    def set_islr_concept(self, islr_concepts: list) -> str:

        party_type = "Supplier" if self.party_type == "Supplier" else "Company"
        party = self.party if self.party_type == "Supplier" else self.company
        account_field = "purchase_islr_account" if self.party_type == "Supplier" else "sales_islr_account"

        type_of_person = frappe.db.get_value(party_type,
                                             party,
                                             "type_of_person")

        account_head = frappe.db.get_value("Company",
                                           self.company,
                                           account_field)

        self.taxes = [tax for tax in self.taxes or []
                      if tax.charge_type != "ISLR"]

        concepts_by_tabulator = defaultdict(list)
        for concept in islr_concepts:
            concepts_by_tabulator[concept['concept_islr']].append(concept)

        references_map = {ref.reference_name: ref
                          for ref in self.references or []}

        for tabulator_name, concepts_in_group in concepts_by_tabulator.items():
            tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

            aliquot_info = next((aq for aq in tabulator.aliquot
                                 if aq.types_of_person == type_of_person
                                 and aq.aliquot > 0), None)

            if not aliquot_info:
                continue

            total_base_for_concept = sum(c['base_amount']
                                         for c in concepts_in_group)

            total_tax_base = (total_base_for_concept * aliquot_info.percentage_base) / 100
            total_tax_amount = ((total_tax_base * aliquot_info.aliquot) / 100) - aliquot_info.subtracting

            self.append("taxes", {
                "charge_type": "ISLR",
                "code": tabulator.codigo,
                "add_deduct_tax": "Deduct",
                "rate": aliquot_info.aliquot,
                "account_head": account_head,
                "tax_amount": total_tax_amount,
                "is_tax_withholding_account": True,
                "subtracting": aliquot_info.subtracting,
                "description": tabulator.descripcion,
            })

            for concept_detail in concepts_in_group:
                reference_doc = references_map.get(concept_detail['reference_name'])
                if not reference_doc:
                    continue

                individual_base = concept_detail['base_amount']
                individual_tax_base = (individual_base * aliquot_info.percentage_base) / 100
                individual_tax_amount = ((individual_tax_base * aliquot_info.aliquot) / 100) - aliquot_info.subtracting

                reference_doc.islr_amount = individual_tax_amount
                reference_doc.islr_base_amount = individual_base
                reference_doc.islr_concept = tabulator_name

        self.save()
        return self.name

    def get_current_tax_amount(self, tax) -> float:

        return tax.tax_amount

get_payment_entry_copy = get_payment_entry

@frappe.whitelist()
def get_payment_entry(
    dt,
    dn,
    party_amount=None,
    bank_account=None,
    bank_amount=None,
    party_type=None,
    payment_type=None,
    reference_date=None,
    ignore_permissions=False,
    created_from_payment_request=False,
) -> PaymentEntry:

    payment_entry: PaymentEntry = get_payment_entry_copy(
        dt,
        dn,
        party_amount=party_amount,
        bank_account=bank_account,
        bank_amount=bank_amount,
        party_type=party_type,
        payment_type=payment_type,
        reference_date=reference_date,
        ignore_permissions=ignore_permissions,
        created_from_payment_request=created_from_payment_request,
    )

    igtf_rate: float = frappe.db.get_single_value(
      "Venezuela Account Settings",
      "igtf_rate"
    )

    igtf_account_field = 'sales_igtf_account' \
        if payment_entry.party_type == "Customer" \
        else "purchase_igtf_account"

    company_data: _dict = frappe.db.get_value(
      "Company",
      payment_entry.company,
      [igtf_account_field, 'default_currency'],
      as_dict=True)

    payment_entry.paid_currency_amount = payment_entry.paid_amount

    payment_entry.igtf_rate = igtf_rate
    payment_entry.igtf_account = company_data.get(igtf_account_field)

    payment_entry.paid_on_currency = company_data.default_currency
    payment_entry.default_company_currency = company_data.default_currency

    return payment_entry
