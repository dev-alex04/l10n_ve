import frappe
from frappe import _, _dict
from frappe.utils import flt, cint, getdate

from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from l10n_ve.overrides.company import CustomCompany
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomSalesInvoice(SalesInvoice):

    def calculate_taxes_and_totals(self) -> None:
        self.set_vat_withholding()

        taxes_and_totals_calculator = TaxesAndTotals(self)

        self.calculate_commission()
        self.calculate_contribution()

        taxes_and_totals_calculator.calculate_total_exempt()

    def before_submit(self) -> None:
        """
        Llamado antes de que el documento sea enviado.
        Asigna números de control
        y de factura si no existen.
        """
        super().before_submit()
        self.set_control_and_invoice_number()
        self.set_title_field()

    def validate(self):

        self.validate_number()
        self.set_control_and_invoice_number()
        self.set_affected_invoice_number()
        super().validate()
        self.validate_item_iva()
        self.validate_same_month_for_return()
        self.calculate_total_withholding()
        # validación de numero de control, debito, credito y de factura
        self._validate_bill_no(raise_throw=True)
        self._validate_bill_control(raise_throw=True)
        self._validate_debit_note_no(raise_throw=True)
        self._validate_credit_note_no(raise_throw=True)

    def set_control_and_invoice_number(self) -> None:

        if self.bill_no or self.credit_note_no or self.debit_note_no:
            return

        company = frappe.get_doc('Company', self.company)

        if self.is_return:
            self.credit_note_no = company.get_credit_note_number()
            self.bill_no = None
            self.debit_note_no = None
            company.increment_credit_note_number()

            self.bill_control = company.get_control_number()
            company.increment_control_number()

        elif self.is_debit_note:
            self.debit_note_no = company.get_debit_note_number()
            self.bill_no = None
            self.credit_note_no = None
            company.increment_debit_note_number()

            self.bill_control = company.get_control_number()
            company.increment_control_number()

        else:
            self.bill_no = company.get_invoice_number()
            self.credit_note_no = None
            self.debit_note_no = None
            company.increment_invoice_number()

            self.bill_control = company.get_control_number()
            company.increment_control_number()


    def set_affected_invoice_number(self):
        # Esta función se ejecutará solo para notas de crédito o débito
        if self.is_return or self.is_debit_note:

            if self.return_against:

                original_invoice_number = frappe.db.get_value(
                    "Sales Invoice",
                    self.return_against,
                    "bill_no"
                )

                self.affected_invoice_number = original_invoice_number
            else:
                self.affected_invoice_number = None

    def validate_same_month_for_return(self):
        """
        Valida que una Nota de Crédito o Débito se cree en el mismo mes
        que la factura original a la que hace referencia.
        """
        if not (self.is_return or self.is_debit_note) or not self.return_against:
            return

        current_posting_date = getdate(self.posting_date)
        origin_invoice_date = frappe.db.get_value(
            "Sales Invoice", self.return_against, "posting_date"
        )

        origin_posting_date = getdate(origin_invoice_date)

        if (current_posting_date.month == origin_posting_date.month and
            current_posting_date.year == origin_posting_date.year):
            return

        document_type = _("Nota de Crédito") if self.is_return else _("Nota de Débito")
        frappe.throw(_("La {0} debe ser creada en el mismo mes que la factura original.").format(document_type))

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
            'bill_control': bill_control_to_validate,
        }
        )
        if is_duplicated:
            if self.is_return:
                message = ("El número de control ya está asignado a otra Nota de Crédito.")
            else:
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
                'bill_no': bill_no_to_validate,
                'is_return': self.is_return
            }
        )

        if is_duplicated:
            if self.is_return:
                message = ("El número de factura ya está asignado a otra Nota de Crédito.")
            else:
                message = ("El número de factura ya está asignado a otra factura.")

            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False

        return True

    def _validate_credit_note_no(self, credit_note_no: str = None, raise_throw: bool = True) -> bool:
        """
        Valida que el número de Nota de Crédito no esté ya asignado.
        """
        credit_note_to_validate = credit_note_no or self.credit_note_no
        if not credit_note_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'credit_note_no': credit_note_to_validate
            }
        )

        if is_duplicated:
            message = ("El número de Nota de Crédito ya está "
            "asignado a otra Nota de Crédito.")
            if raise_throw:
                frappe.throw(message, title="Advertencia de Duplicado")
            return False

        return True

    def _validate_debit_note_no(self, debit_note_no: str = None,
                                raise_throw: bool = True) -> bool:
        """
        Valida que el número de Nota de Débito no esté ya asignado.
        """
        debit_note_to_validate = debit_note_no or self.debit_note_no
        if not debit_note_to_validate:
            return True

        is_duplicated = frappe.db.exists(
            "Sales Invoice",
            {
                'docstatus': 1,
                'company': self.company,
                'name': ['!=', self.name],
                'debit_note_no': debit_note_to_validate
            }
        )

        if is_duplicated:
            message = ("El número de Nota de Débito ya está asignado a otra Nota de Débito.")
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

        # La retención de IVA solo aplica si el cliente es Contribuyente Especial.
        is_special_taxpayer = frappe.db.get_value("Customer",
                                                  self.customer,
                                                  "is_special_taxpayer")
        if not is_special_taxpayer:
            return
        # Obtener la categoría de retención directamente del cliente
        withholding_category_name = frappe.db.get_value("Customer",
                                                        self.customer,
                                                        "tax_withholding_category")
        if not withholding_category_name:
            return

        # Cargar el documento de la categoría de retención
        withholding_category = frappe.get_doc("Tax Withholding Category",
                                              withholding_category_name)
        if not withholding_category:
            return

        # Acceder a la cuenta contable desde la tabla hija 'accounts'
        # del documento de la categoría
        account_details_for_company = None
        for acc_details in withholding_category.accounts:
            if acc_details.company == self.company:
                account_details_for_company = acc_details
                break

        if not account_details_for_company:
            frappe.throw(_("No se encontró una cuenta de retención "
            "de ventas para la compañía {0} en la categoría '{1}'.").format(
                self.company, withholding_category_name
            ))

        rate = withholding_category.rates[0].tax_withholding_rate \
                if withholding_category.rates \
                and len(withholding_category.rates) > 0 else 0

        withholding_account = account_details_for_company.sales_account
        withholding_description = withholding_category.category_name or withholding_category.name

        self.taxes = [
            row for row
            in self.taxes
            if row.account_head != withholding_account
        ]

        if self.get_iva_tax_row() and rate > 0:

            self.append("taxes", {
                "rate": rate,
                "charge_type": "VAT Withholding",
                "add_deduct_tax": "Deduct",
                "is_tax_withholding_account": True,
                "account_head": withholding_account,
                "description": withholding_description,
            })

    def set_tax_withholding(self):
        """
        Sobrescribe el método estándar para evitar que se aplique la lógica
        de retención de compras (TDS) en una factura de venta cuando ya se
        ha gestionado la retención de IVA (TCS).
        """

        is_special_taxpayer = frappe.db.get_value("Customer", self.customer, "is_special_taxpayer")
        if not is_special_taxpayer:
            return

        has_vat_withholding = any(tax.charge_type == "VAT Withholding"
                                  for tax in self.get("taxes", []))

        if has_vat_withholding:
            return

    @frappe.whitelist()
    def set_islr_concept(self, tabulator_name: str) -> None:

        tabulator = frappe.get_doc("Tabulator ISLR", tabulator_name)

        type_of_person: str = frappe.db.get_value("Customer",
                                                    self.customer,
                                                    "type_of_person")

        account_head: str = frappe.db.get_value("Company",
                                                    self.company,
                                                    "sales_islr_account")

        for aliquot in tabulator.aliquot:
            if type_of_person == aliquot.types_of_person:

                self.append("taxes", {
                    "category": "Total",
                    "charge_type": "ISLR",
                    "add_deduct_tax": "Deduct",
                    "rate": aliquot.aliquot,
                    "code": tabulator.codigo,
                    "account_head": account_head,
                    "is_tax_withholding_account": True,
                    "subtracting": aliquot.subtracting,
                    "description": tabulator.descripcion,
                    "percentage_base": aliquot.percentage_base,
                })
                break
        self.save()
        return self.name


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
        return

        has_taxable_items = any(not item.vat_exempt for item in self.items)

        if not has_taxable_items and self.taxes_and_charges:
            self.taxes_and_charges = None
            self.set("taxes", [])

            self.apply_tds = 0

        has_vat_charge = any(tax.charge_type == 'VAT' for tax in self.taxes)

        if not has_vat_charge and self.apply_tds == 1:
            self.set("taxes", [])
            self.apply_tds = 0

    def validate_number(self):
        if self.vat_withholding_voucher_number:

            if not self.vat_withholding_voucher_number.isdigit():
                frappe.throw("El número de comprobante de retención "
                "de IVA debe contener solo números.")

            if len(self.vat_withholding_voucher_number) != 14:
                frappe.throw("El número de comprobante de retención "
                "de IVA debe tener exactamente 14 caracteres.")

    def set_title_field(self):
        super().set_title_field()
        if self.docstatus == 0:
            return
        if self.is_return:
            self.title = self.credit_note_no

        elif self.is_debit_note:
            self.title = self.debit_note_no

        else:
            self.title = self.bill_no

@frappe.whitelist()
def upload_voucher_data(docname, voucher_number, withholding_date, file_url=None):
    """
    Actualiza la Sales Invoice (Factura de Venta) con los datos del comprobante de retención.
    """
    try:
        doc = frappe.get_doc("Sales Invoice", docname)

        doc.db_set('vat_withholding_voucher_number', voucher_number)
        doc.db_set('withholding_date', withholding_date)
        doc.db_set('voucher_image', file_url)

        doc.add_comment(
            "Comment",
            f"Comprobante de Retención cargado. Número: {voucher_number}. Fecha: {withholding_date}.",

        )

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante."
        }

    except frappe.DoesNotExistError:
        frappe.log_error(f"Sales Invoice {docname} no encontrada.", "Error en upload_voucher_data")
        return {
            "status": "error",
            "msg": f"Factura de Venta con ID {docname} no encontrada."
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en upload_voucher_data")
        return {
            "status": "error",
            "msg": f"Error inesperado al guardar los datos: {str(e)}"
        }

@frappe.whitelist()
def upload_islr_voucher_data(docname, islr_date, islr_receipt_number=None, file_url=None):
    """
    Actualiza la Sales Invoice (Factura de Venta) con los datos del comprobante de retención de ISLR.
    """
    try:
        # Validación en el backend
        if not islr_date or not file_url:
            frappe.throw(_("La fecha y el archivo del comprobante de ISLR son obligatorios."))

        doc = frappe.get_doc("Sales Invoice", docname)

        doc.db_set('islr_receipt_number', islr_receipt_number)
        doc.db_set('islr_date', islr_date)
        doc.db_set('voucher_image_islr', file_url)

        # Construir el comentario dinámicamente
        comment_text = f"Comprobante de Retención de ISLR cargado. Fecha: {islr_date}."
        if islr_receipt_number:
            comment_text = f"Comprobante de Retención de ISLR cargado. Número: {islr_receipt_number}. Fecha: {islr_date}."
        else:
            comment_text = f"Comprobante de Retención de ISLR cargado (sin número). Fecha: {islr_date}."

        doc.add_comment(
            "Comment",
            comment_text,
        )

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante de ISLR."
        }

    except frappe.DoesNotExistError:
        frappe.log_error(f"Sales Invoice {docname} no encontrada.", "Error en upload_islr_voucher_data")
        return {"status": "error", "msg": f"Factura de Venta con ID {docname} no encontrada."}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en upload_islr_voucher_data")
        return {"status": "error", "msg": f"Error inesperado al guardar los datos: {str(e)}"}