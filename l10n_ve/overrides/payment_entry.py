import frappe
from frappe import _
from erpnext.accounts.doctype.payment_entry.payment_entry import PaymentEntry, validate_taxes_and_charges, validate_inclusive_tax


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
                if tax.charge_type == "ISLR"
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
    def set_islr_concept(self, islr_concepts: list) -> None:

        if self.party_type == 'Supplier':
            party_type = 'Supplier'
            party = self.party
            account_field = 'purchase_islr_account'

        else: # Ventas
            party_type = 'Company'
            party = self.company
            account_field = 'sales_islr_account'

        type_of_person: str = frappe.db.get_value(party_type,
                                                  party,
                                                  "type_of_person")

        account_head: str = frappe.db.get_value("Company",
                                                self.company,
                                                account_field)
        # para evitar duplicados del ISLR
        self.taxes = [
            tax for tax in self.taxes or []
            if tax.get('charge_type') != "ISLR"
        ]

        islr_amounts = {}

        for concept in islr_concepts:
            if concept['concept_islr'] not in islr_amounts:
                islr_amounts[concept['concept_islr']] = 0

            islr_amounts[concept['concept_islr']] += concept['base_amount']

        for tabulator_name, base_amount in islr_amounts.items():
            tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

            for aliquot in tabulator.aliquot:


                if type_of_person == aliquot.types_of_person \
                        and aliquot.aliquot > 0:

                    tax_base = (base_amount * aliquot.percentage_base) / 100
                    tax_amount = ((tax_base * aliquot.aliquot) / 100) - aliquot.subtracting

                    self.append("taxes", {
                        "charge_type": "ISLR",
                        "rate": aliquot.aliquot,
                        "tax_amount": tax_amount,
                        "code": tabulator.codigo,
                        "add_deduct_tax": "Deduct",
                        "account_head": account_head,
                        "is_tax_withholding_account": True,
                        "subtracting": aliquot.subtracting,
                        "description": tabulator.descripcion,
                        "percentage_base": aliquot.percentage_base,
                    })

                    break

        for tax in self.taxes:
            if tax.charge_type == "ISLR":
                print(tax.tax_amount, 'viendop la cagada esta')

        self.save()
        return self.name

    def get_current_tax_amount(self, tax) -> float:

        return tax.tax_amount
