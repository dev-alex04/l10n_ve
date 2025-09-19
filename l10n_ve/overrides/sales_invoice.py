import frappe
from frappe import _, _dict
from frappe.utils import flt, cint
from frappe.model.document import Document

from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from l10n_ve.overrides.company import CustomCompany
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomSalesInvoice(SalesInvoice):


    def calculate_taxes_and_totals(self) -> None:

        TaxesAndTotals(self)
        self.set_vat_withholding()
        self.calculate_commission()
        self.calculate_contribution()
        taxes_and_totals_calculator = TaxesAndTotals(self)
        taxes_and_totals_calculator.calculate_total_exempt()

    def before_submit(self) -> None:
        """
        Llamado antes de que el documento sea enviado.
        Asigna números de control
        y de factura si no existen.
        """
        super().before_submit()
        self.set_control_and_invoice_number()

    def validate(self):

        self.validate_number()
        super().validate()
        self.validate_item_iva()
        self.calculate_total_withholding()
        # validación de numero de control y de factura
        self._validate_bill_no(raise_throw=True)
        self._validate_bill_control(raise_throw=True)

    def set_control_and_invoice_number(self) -> None:
        """
        Asigna el número de control y de factura si no existen.
        Utiliza un bucle para asegurar la unicidad en caso de concurrencia.
        """
        if self.bill_control and self.bill_no:
            return

        while True:
            # Carga el documento Company (con su clase de override)
            company: CustomCompany = frappe.get_doc('Company', self.company)
            numbers = company.get_control_and_invoice_number()
            bill_control = numbers.get('bill_control')
            bill_no = numbers.get('bill_no')

            # Valida si los números están duplicados.
            if not self._validate_bill_control(bill_control, raise_throw=False) or not self._validate_bill_no(bill_no, raise_throw=False):
                # Si son duplicados, se revierte y el bucle continúa
                frappe.db.rollback()
                continue

            self.bill_control = bill_control
            self.bill_no = bill_no

            break

    def _validate_bill_control(self,
                               bill_control: str = '',
                               raise_throw: bool = True) -> bool:
        """
        Valida que el número de control no esté ya asignado.
        Acepta un valor opcional para validar.
        """
        bill_control_to_validate = bill_control or self.bill_control
        if not bill_control_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'bill_control': bill_control_to_validate
            }
        )
        if is_duplicated:
            message = ("El número de control ya está asignado a otra factura.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False
        return True

    def _validate_bill_no(self, bill_no: str = None, raise_throw: bool = True) -> bool:
        """
        Valida que el número de factura no esté ya asignado.
        Acepta un valor opcional para validar.
        """
        bill_no_to_validate = bill_no or self.bill_no
        if not bill_no_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'bill_no': bill_no_to_validate
            }
        )

        if is_duplicated:
            message = ("El número de factura ya está asignado a otra factura.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False

        return True

    def get_iva_tax_row(self) -> _dict | None:
        """
        Función auxiliar para encontrar y devolver la fila del impuesto de IVA de la factura.
        Se busca en la tabla de impuestos de la factura, no en la plantilla.

        Returns:
            _dict | None: La fila del impuesto de IVA si se encuentra,
            de lo contrario None.
        """

        for tax_row in self.taxes:
            if tax_row.charge_type == "VAT":
                return tax_row

    def set_vat_withholding(self) -> None:

        """
        Gestiona la lógica de retención de IVA para contribuyentes especiales.
        """

        is_special_taxpayer = frappe.db.get_value("Customer",
                                                  self.customer,
                                                  "is_special_taxpayer")
        if not is_special_taxpayer:
            return

        taxes_and_charges_template_name = self.taxes_and_charges
        if not taxes_and_charges_template_name:
            return

        taxes_and_charges_template = \
            frappe.get_doc("Sales Taxes and Charges Template",
                           taxes_and_charges_template_name)

        withholding_category_name = taxes_and_charges_template.withholding
        if not withholding_category_name:
            return

        withholding_category = frappe.get_doc("Tax Withholding Category",
                                              withholding_category_name)
        if not withholding_category:
            return

        # Acceder a la cuenta contable desde la tabla hija 'accounts'
        # del documento de la categoría
        if withholding_category.accounts:
            withholding_account = withholding_category.accounts[0].account
            withholding_description = withholding_category.accounts[0].account
        else:
            frappe.throw("No se encontró la cuenta de retención en la categoría de retención.")

        company_name = self.company
        withholding_rate = frappe.db.get_value("Company",
                                               company_name,
                                               "sales_vat_withholding_rate")
        if not withholding_rate:
            msg = f"El porcentaje de retención de IVA para ventas no está " \
                  f"configurada en el documento de la Compañía."
            frappe.throw(msg)

        self.taxes = [
            row for row
            in self.taxes
            if row.account_head != withholding_account
        ]

        vat_tax = self.get_iva_tax_row()

        if vat_tax and withholding_rate:

            self.vat_withholding_rate = withholding_rate

            self.append("taxes", {
                "rate": withholding_rate,
                "charge_type": "VAT Withholding",
                "add_deduct_tax": "Deduct",
                "is_tax_withholding_account": True,
                "account_head": withholding_account,
                "description": withholding_description,
            })

    def calculate_total_withholding(self):
        self.total_withholding  = 0.0

        if not self.get("taxes"):
            return

        for tax in self.get("taxes"):
            if not tax.is_tax_withholding_account:
                    continue

            self.total_withholding += tax.tax_amount


    def make_tax_gl_entries(self, gl_entries):

        enable_discount_accounting = cint(
            frappe.db.get_single_value("Selling Settings",
                                       "enable_discount_accounting"))

        for tax in self.get("taxes"):

            if tax.is_tax_withholding_account:
                continue

            amount, base_amount = self.get_tax_amounts(tax, enable_discount_accounting)

            if not flt(tax.base_tax_amount_after_discount_amount):
                continue

            account_currency = get_account_currency(tax.account_head)
            tax_amount_after_discount_amount = \
                tax.precision("tax_amount_after_discount_amount")

            base_tax_amount_after_discount_amount = \
                tax.precision("base_tax_amount_after_discount_amount")

            credit_in_account_currency = \
                flt(base_amount, base_tax_amount_after_discount_amount) \
                if account_currency == self.company_currency \
                else flt(amount, tax_amount_after_discount_amount)

            gl_entries.append(
                self.get_gl_dict(
                    {
                        "against": self.customer,
                        "account": tax.account_head,
                        "cost_center": tax.cost_center,
                        "credit_in_account_currency": credit_in_account_currency,
                        "credit": flt(base_amount, tax_amount_after_discount_amount),

                        "credit_in_transaction_currency": flt(
                            amount, tax_amount_after_discount_amount
                        ),
                    },
                    account_currency,
                    item=tax,
                )
            )
    def validate_item_iva(self):

        has_taxable_items = False
        for item in self.items:
            if not item.vat_exempt:
                has_taxable_items = True
                break

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])

            self.apply_tds = 0

        has_vat_charge = False
        for tax in self.taxes:
            if tax.charge_type == 'VAT':
                has_vat_charge = True
                break

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

    def validate_number(self):
        if self.vat_withholding_voucher_number:
            # 1. Verifica si el valor contiene solo dígitos.
            if not self.vat_withholding_voucher_number.isdigit():
                frappe.throw("El número de comprobante de retención de IVA debe contener solo números.")

            # 2. Verifica si la longitud es exactamente 14.
            if len(self.vat_withholding_voucher_number) != 14:
                frappe.throw("El número de comprobante de retención de IVA debe tener exactamente 14 caracteres.")

        # Llama a la validación de la clase padre para mantener las validaciones estándar de Frappe.


