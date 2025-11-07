from collections import defaultdict

import frappe
from frappe import _, _dict
from frappe.utils import flt

from erpnext.accounts.doctype.payment_entry.payment_entry import (
    PaymentEntry,
    get_payment_entry,
    validate_inclusive_tax,

)

from erpnext.controllers.accounts_controller import validate_taxes_and_charges

from erpnext.accounts.general_ledger import (
    process_gl_map,
    make_gl_entries,
)

from erpnext.accounts.utils import (
    cancel_exchange_gain_loss_journal,
    get_account_currency,
)


class CustomPaymentEntry(PaymentEntry):

    def validate(self) -> None:
        super().validate()

        self.validate_reference_no()

    def on_submit(self) -> None:
        self.custom_clear_unallocated_reference_document_rows()

        super().on_submit()

        if flt(self.unallocated_amount) > 0:
            frappe.msgprint(
                _("Se ha generado un anticipo a su favor por un monto de {0}.").format(
                    frappe.utils.fmt_money(self.unallocated_amount, currency=self.paid_from_account_currency
                                           or self.paid_to_account_currency)
                )
            )

        self.set_igtf_on_invoices()

    def on_cancel(self) -> None:
        super().on_cancel()

        self.set_igtf_on_invoices(is_cancelled=True)

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

        if self.party_type != 'Supplier':
            return

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

            if total_tax_amount <= 0:
                continue

            self.append("taxes", {
                "charge_type": "ISLR",
                "code": tabulator.codigo,
                "add_deduct_tax": "Deduct",
                "rate": aliquot_info.aliquot,
                "account_head": account_head,
                "tax_amount": total_tax_amount,
                "is_tax_withholding_account": True,
                "description": tabulator.descripcion,
                "subtracting": aliquot_info.subtracting,
            })

            for concept_detail in concepts_in_group:
                reference_doc = references_map.get(concept_detail['reference_name'])
                if not reference_doc:
                    continue

                individual_base = concept_detail['base_amount']
                individual_tax_base = (individual_base * aliquot_info.percentage_base) / 100
                individual_tax_amount = ((individual_tax_base * aliquot_info.aliquot) / 100) - aliquot_info.subtracting

                if individual_tax_amount <= 0:
                    continue

                reference_doc.islr_amount = individual_tax_amount
                reference_doc.islr_base_amount = individual_base
                reference_doc.islr_concept = tabulator_name

        self.save()
        return self.name

    # ------------------------- CALCULO DE IMPUESTOS ------------------------- #

    def calculate_taxes(self) -> None:
        self.total_taxes_and_charges = 0.0
        self.base_total_taxes_and_charges = 0.0

        actual_tax_dict = dict(
            [
                [tax.idx, flt(tax.tax_amount, tax.precision("tax_amount"))]
                for tax in self.get("taxes")
                if tax.charge_type == "Actual"
            ]
        )

        for i, tax in enumerate(self.get("taxes")):
            current_tax_amount = self.get_current_tax_amount(tax)

            if tax.charge_type == "Actual":
                actual_tax_dict[tax.idx] -= current_tax_amount
                if i == len(self.get("taxes")) - 1:
                    current_tax_amount += actual_tax_dict[tax.idx]

            tax.tax_amount = current_tax_amount
            tax.base_tax_amount = current_tax_amount

            if tax.add_deduct_tax == "Deduct":
                current_tax_amount *= -1.0
            else:
                current_tax_amount *= 1.0

            if tax.charge_type == 'IGTF':
                amount_for_total = 0 # El IGTF no debe modificar el total del pago
            else:
                amount_for_total = current_tax_amount

            if i == 0:
                tax.total = flt(self.paid_amount_after_tax + amount_for_total, self.precision("total", tax))
            else:
                tax.total = flt(
                    self.get("taxes")[i - 1].total + amount_for_total, self.precision("total", tax)
                )

            tax.base_total = tax.total

            if self.payment_type == "Pay":
                if tax.currency != self.paid_to_account_currency:
                    self.total_taxes_and_charges += flt(current_tax_amount / self.target_exchange_rate)
                else:
                    self.total_taxes_and_charges += current_tax_amount
            elif self.payment_type == "Receive":
                if tax.currency != self.paid_from_account_currency:
                    self.total_taxes_and_charges += flt(current_tax_amount / self.source_exchange_rate)
                else:
                    self.total_taxes_and_charges += current_tax_amount

            self.base_total_taxes_and_charges += tax.base_tax_amount

        if self.get("taxes"):
            self.paid_amount_after_tax = self.get("taxes")[-1].base_total

    def get_current_tax_amount(self, tax) -> float:
        return tax.tax_amount

    def set_igtf_on_invoices(self, is_cancelled=False) -> None:

        igtf = next((tax for tax in self.taxes or []
                     if tax.charge_type == 'IGTF'), None)

        if not igtf:
            return

        for reference in self.references or []:

            if not reference.allocated_amount:
                continue

            if is_cancelled:
                total_igtf = 0
                base_amount_igtf = 0
            else:
                reference_base_amount_igtf = reference.allocated_amount
                reference_total_igtf = \
                    (reference.allocated_amount * self.igtf_rate) / 100

                invoice_igtf_data: dict = frappe.db.get_value(
                    reference.reference_doctype,
                    reference.reference_name,
                    [
                        'total_igtf',
                        'base_amount_igtf'
                    ],
                    as_dict=True)

                total_igtf = invoice_igtf_data.get('total_igtf', 0) + \
                    reference_total_igtf

                base_amount_igtf = \
                    invoice_igtf_data.get('base_amount_igtf', 0) + \
                        reference_base_amount_igtf

            frappe.db.set_value(reference.reference_doctype,
                                reference.reference_name,
                                {
                                    'total_igtf': total_igtf,
                                    'base_amount_igtf': base_amount_igtf,
                                })

    def validate_reference_no(self) -> None:
        """
        Valida que el número de referencia tenga al menos 4 dígitos y sea numérico.
        """
        if not self.reference_no:
            return

        if not self.reference_no.isdigit():
            frappe.throw(_("El número de referencia solo debe contener números."))

        if len(self.reference_no) < 4:
            frappe.throw(_("El número de referencia debe tener al menos 4 dígitos."))

# ----------------------------- OVERRIDE METHODS ----------------------------- #

    def clear_unallocated_reference_document_rows(self) -> None:
        """
        Se desactiva esta funcion en el validate para que no se eliminen las
        lineas de referencia sin monto aplicado.
        Esto sucederá sólo en el on_submit en la funcion
        custom_clear_unallocated_reference_document_rows
        """
        return

    def custom_clear_unallocated_reference_document_rows(self) -> None:

        self.set("references",
        self.get("references", {"allocated_amount": ["not in", [0, None, ""]]}))

        frappe.db.sql(
            """delete from `tabPayment Entry Reference`
            where parent = %s and allocated_amount = 0""",
            self.name,
        )
# --------------------------- GESTIÓN DE ASIENTOS --------------------------- #

    def make_gl_entries(self, cancel=0, adv_adj=0) -> None:
        gl_entries = self.build_gl_map()
        gl_entries = process_gl_map(gl_entries, merge_entries=False)
        make_gl_entries(gl_entries, cancel=cancel, adv_adj=adv_adj)
        if cancel:
            cancel_exchange_gain_loss_journal(frappe._dict(doctype=self.doctype, name=self.name))
        else:
            self.make_exchange_gain_loss_journal()

        self.make_advance_gl_entries(cancel=cancel)

    def add_tax_gl_entries(self, gl_entries: list) -> None:

        for d in self.get("taxes"):

            if not d.tax_amount:
                continue

            account_currency = get_account_currency(d.account_head)
            if account_currency != self.company_currency:
                frappe.throw(_("Currency for {0} must be {1}"
                               ).format(d.account_head, self.company_currency))

            if self.payment_type in ("Pay", "Internal Transfer"):
                dr_or_cr = "debit" if d.add_deduct_tax == "Add" else "credit"
                rev_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"
                against = self.party or self.paid_from
            elif self.payment_type == "Receive":
                dr_or_cr = "credit" if d.add_deduct_tax == "Add" else "debit"
                rev_dr_or_cr = "credit" if dr_or_cr == "debit" else "debit"
                against = self.party or self.paid_to

            payment_account = self.get_party_account_for_taxes()
            tax_amount = d.tax_amount
            base_tax_amount = d.base_tax_amount

            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": d.account_head,
                        "against": against,
                        dr_or_cr: tax_amount,
                        dr_or_cr + "_in_account_currency": base_tax_amount
                        if account_currency == self.company_currency
                        else d.tax_amount,
                        dr_or_cr + "_in_transaction_currency": base_tax_amount
                        / self.transaction_exchange_rate,
                        "cost_center": d.cost_center,
                        "post_net_value": True,
                    },
                    account_currency,
                    item=d,
                )
            )

            if not d.included_in_paid_amount:
                if get_account_currency(payment_account) != self.company_currency:
                    if self.payment_type == "Receive":
                        exchange_rate = self.target_exchange_rate
                    elif self.payment_type in ["Pay", "Internal Transfer"]:
                        exchange_rate = self.source_exchange_rate
                    base_tax_amount = flt((tax_amount / exchange_rate), self.precision("paid_amount"))

                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": payment_account,
                            "against": against,
                            rev_dr_or_cr: tax_amount,
                            rev_dr_or_cr + "_in_account_currency": base_tax_amount
                            if account_currency == self.company_currency
                            else d.tax_amount,
                            rev_dr_or_cr + "_in_transaction_currency": base_tax_amount
                            / self.transaction_exchange_rate,
                            "cost_center": self.cost_center,
                            "post_net_value": True,
                        },
                        account_currency,
                        item=d,
                    )
                )


    def set_transaction_currency_and_rate(self) -> None:
        self.transaction_currency = self.paid_on_currency
        self.transaction_exchange_rate = self.exchange_rate


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

    doc = frappe.get_doc(dt, dn)

    payment_entry.paid_currency_amount = payment_entry.paid_amount

    payment_entry.igtf_rate = igtf_rate
    payment_entry.igtf_account = company_data.get(igtf_account_field)

    payment_entry.paid_on_currency = doc.get('currency', company_data.default_currency)
    payment_entry.default_company_currency = company_data.default_currency

    return payment_entry
