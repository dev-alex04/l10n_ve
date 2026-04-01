import frappe
from frappe import _
from frappe.utils import flt, cint, getdate

from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice, make_regional_gl_entries

from l10n_ve.overrides.company import CustomCompany
from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.utils.utils import validate_return_in_same_month, get_link_to_form


class VESalesInvoice(TaxesMixin, SalesInvoice):

    def calculate_taxes_and_totals(self) -> None:

        taxes_and_totals_calculator = TaxesAndTotals(self)

        self.calculate_commission()
        self.calculate_contribution()

        taxes_and_totals_calculator.calculate_total_exempt()
        self.calculate_total_withholding()

    def on_trash(self) -> None:
        """
        Evita la eliminación de documentos que han sido anulados.
        """
        if self.is_void:
            frappe.throw(_("No se puede eliminar un documento que ha sido anulado."))

    def before_submit(self) -> None:
        super().before_submit()
        self.set_control_and_invoice_number()
        self.set_title_field()

    def validate(self) -> None:
        super().validate()

        self.validate_withholding_voucher_number()
        self.set_affected_invoice_number()
        self.validate_return_in_same_month()

        # validación de numero de control, debito, credito y de factura
        self._validate_bill_no(raise_throw=True)
        self._validate_bill_control(raise_throw=True)
        self._validate_debit_note_no(raise_throw=True)
        self._validate_credit_note_no(raise_throw=True)

    def validate_return_in_same_month(self) -> None:
        """
        Valida que una Nota de Crédito o Débito se cree en el mismo mes
        que la factura original a la que hace referencia.
        Llama a la función centralizada en utils.
        """
        validate_return_in_same_month(self)

    def set_control_and_invoice_number(self) -> None:
        """
        Si TFHKA está activo, la asignación de número de factura y control
        se realiza exclusivamente desde el botón de envío a HKA,
        para garantizar que los números se envíen en orden secuencial.
        """
        digital_series = self._get_active_digital_series()
        if digital_series:
            return

        company = frappe.get_doc('Company', self.company)
        self.set_invoice_number(company)
        self.set_control_number(company)

    def _get_active_digital_series(self) -> 'frappe.Document | None':
        """
        Retorna el documento VE Digital Billing Series activo para la empresa
        y sucursal de esta factura. Primero intenta con la sucursal exacta;
        si no existe, busca una serie sin sucursal asignada (aplicable a toda
        la empresa). Retorna None si TFHKA no está habilitado o no hay serie.
        """
        try:
            tfhka_enabled = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "enabled"
            )
        except Exception:
            return None

        if not tfhka_enabled:
            return None

        filters_branch = {
            "company": self.company,
            "branch": self.branch or "",
            "status": "Active",
        }
        series_name = frappe.db.get_value(
            "VE Digital Billing Series", filters_branch, "name"
        )

        if not series_name and self.branch:
            filters_global = {
                "company": self.company,
                "branch": "",
                "status": "Active",
            }
            series_name = frappe.db.get_value(
                "VE Digital Billing Series", filters_global, "name"
            )

        if not series_name:
            return None

        return frappe.get_doc("VE Digital Billing Series", series_name)

    def set_invoice_number(self, company: CustomCompany) -> None:

        if self.bill_no or self.credit_note_no or self.debit_note_no:
            return

        if self.is_return:
            while True:
                credit_note_no = company.get_credit_note_number()
                if self._validate_credit_note_no(credit_note_no, raise_throw=False):
                    self.credit_note_no = credit_note_no
                    self.bill_no = None
                    self.debit_note_no = None
                    company.increment_credit_note_number()
                    break
                company.increment_credit_note_number()
                company.sales_credit_note_number_correlative = \
                    (company.sales_credit_note_number_correlative or 1) + 1

        elif self.is_debit_note:
            while True:
                debit_note_no = company.get_debit_note_number()
                if self._validate_debit_note_no(debit_note_no, raise_throw=False):
                    self.debit_note_no = debit_note_no
                    self.bill_no = None
                    self.credit_note_no = None
                    company.increment_debit_note_number()
                    break
                company.increment_debit_note_number()
                company.sales_debit_note_number_correlative = \
                    (company.sales_debit_note_number_correlative or 1) + 1

        else:
            while True:
                bill_no = company.get_invoice_number()
                if self._validate_bill_no(bill_no, raise_throw=False):
                    self.bill_no = bill_no
                    self.credit_note_no = None
                    self.debit_note_no = None
                    company.increment_invoice_number()
                    break
                company.increment_invoice_number()
                company.sales_invoice_number_correlative = \
                    (company.sales_invoice_number_correlative or 1) + 1

    def set_control_number(self, company: CustomCompany) -> None:
        """No asigna número de control si TFHKA está activo (lo gestiona HKA)."""

        if self.bill_control:
            return

        while True:
            bill_control = company.get_control_number()
            if self._validate_bill_control(bill_control, raise_throw=False):
                self.bill_control = bill_control
                company.increment_control_number()
                break
            company.increment_control_number()
            company.sales_invoice_control_number_correlative = \
                (company.sales_invoice_control_number_correlative or 1) + 1

    def set_affected_invoice_number(self) -> None:
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

    def _validate_bill_control(self,
                               bill_control: str = '',
                               raise_throw: bool = True) -> bool:
        """
        Valida que el número de control no esté ya asignado.
        Si TFHKA está activo, ignora duplicados cuya posting_date sea anterior
        a la fecha start_operations de la serie digital activa.
        """

        bill_control_to_validate = bill_control or self.bill_control
        if not bill_control_to_validate:
            return True

        if not bill_control_to_validate.isdigit():
            frappe.throw("El número de control solo debe contener números.")

        draft_submitted_filters = {
            'company': self.company,
            'name': ['!=', self.name],
            'bill_control': bill_control_to_validate,
            'docstatus': ['in', [0, 1]],
        }

        void_filters = {
            'company': self.company,
            'name': ['!=', self.name],
            'bill_control': bill_control_to_validate,
            'docstatus': 2,
            'is_void': 1,
        }

        duplicated_docs = frappe.db.get_all('Sales Invoice',
                                            filters=draft_submitted_filters,
                                            fields=['name', 'posting_date']) or []

        duplicated_docs.extend(frappe.db.get_all('Sales Invoice',
                                                 filters=void_filters,
                                                 fields=['name', 'posting_date']) or [])

        if not duplicated_docs:
            return True

        digital_series = self._get_active_digital_series()
        if digital_series and digital_series.start_operations:
            start_ops = getdate(digital_series.start_operations)
            duplicated_docs = [
                d for d in duplicated_docs
                if not (d.posting_date and getdate(d.posting_date) < start_ops)
            ]

        if not duplicated_docs:
            return True

        if self.is_return:
            doc_type_str = "Nota de Crédito"
        elif self.is_debit_note:
            doc_type_str = "Nota de Débito"
        else:
            doc_type_str = "Factura"

        duplicated_msg = []
        for doc in duplicated_docs:
            link = get_link_to_form(self.doctype, doc.name)
            msg = (
                f"El número de control {bill_control_to_validate} "
                f"ya está siendo usado en la {doc_type_str} {link}. Corrija e intente nuevamente."
            )
            duplicated_msg.append(msg)

        if raise_throw:
            frappe.throw(duplicated_msg, title="Advertencia de Duplicado", as_list=True)
        return False

    def _validate_bill_no(self, bill_no: str = '', raise_throw: bool = True) -> bool:
        """
        Valida que el número de factura no esté ya asignado.
        Si TFHKA está activo, ignora duplicados cuya posting_date sea anterior
        a la fecha start_operations de la serie digital activa (reinicio de
        facturación autorizado por HKA).
        """

        if any([self.is_return, self.is_debit_note]):
            return True

        bill_no_to_validate = bill_no or self.bill_no
        if not bill_no_to_validate:
            return True

        if not bill_no_to_validate.isdigit():
            frappe.throw("El número de factura solo debe contener números.")

        draft_submitted_filters = {
            'is_return': False,
            'is_debit_note': False,
            'company': self.company,
            'name': ['!=', self.name],
            'bill_no': bill_no_to_validate,
            'docstatus': ['in', [0, 1]],
        }

        void_filters = {
            'is_return': False,
            'is_debit_note': False,
            'company': self.company,
            'name': ['!=', self.name],
            'bill_no': bill_no_to_validate,
            'docstatus': 2,
            'is_void': 1,
        }

        duplicated_docs = frappe.db.get_all(
            'Sales Invoice',
            filters=draft_submitted_filters,
            fields=['name', 'posting_date']
        ) or []

        duplicated_docs.extend(frappe.db.get_all(
            'Sales Invoice',
            filters=void_filters,
            fields=['name', 'posting_date']
        ) or [])

        if not duplicated_docs:
            return True

        digital_series = self._get_active_digital_series()
        if digital_series and digital_series.start_operations:
            start_ops = getdate(digital_series.start_operations)
            duplicated_docs = [
                d for d in duplicated_docs
                if not (d.posting_date and getdate(d.posting_date) < start_ops)
            ]

        if not duplicated_docs:
            return True

        duplicated_msg = []
        for doc in duplicated_docs:
            invoice_link: str = get_link_to_form(self.doctype, doc.name)
            msg = (
                f'El número de factura {bill_no_to_validate} ya está siendo '
                f'usado en otro documento {invoice_link}. '
                f'Corrija e intente nuevamente.'
            )
            duplicated_msg.append(msg)

        if raise_throw:
            frappe.throw(duplicated_msg, title="Advertencia de Duplicado", as_list=True)
        return False

    def _validate_credit_note_no(self,
                                 credit_note_no: str = '',
                                 raise_throw: bool = True) -> bool:
        """
        Valida que el número de Nota de Crédito no esté ya asignado.
        """

        credit_note_to_validate = credit_note_no or self.credit_note_no
        if not credit_note_to_validate:
            return True

        if not credit_note_to_validate.isdigit():
            frappe.throw("El número de Nota de Crédito solo debe contener números.")

        draft_submitted_filters = {
            'is_return': True,
            'company': self.company,
            'name': ['!=', self.name],
            'credit_note_no': credit_note_to_validate,
            'docstatus': ['in', [0, 1]],
        }

        void_filters = {
            'is_return': True,
            'company': self.company,
            'name': ['!=', self.name],
            'credit_note_no': credit_note_to_validate,
            'docstatus': 2,
            'is_void': 1,
        }

        duplicated_docs = frappe.db.get_all('Sales Invoice',
                                            filters=draft_submitted_filters,
                                            pluck='name') or []

        duplicated_docs.extend(frappe.db.get_all('Sales Invoice',
                                                 filters=void_filters,
                                                 pluck='name') or [])
        if duplicated_docs:
            duplicated_msg = []
            for duplicated in set(duplicated_docs):
                link = get_link_to_form(self.doctype, duplicated)
                msg = \
                f"El número de Nota de Crédito {credit_note_to_validate} " \
                f"ya está siendo usado en el documento {link}. Corrija e intente nuevamente."
                duplicated_msg.append(msg)

            if raise_throw:
                frappe.throw(duplicated_msg, title="Advertencia de Duplicado", as_list=True)
            return False

        return True

    def _validate_debit_note_no(self,
                                debit_note_no: str = '',
                                raise_throw: bool = True) -> bool:
        """
        Valida que el número de Nota de Débito no esté ya asignado.
        """

        debit_note_to_validate = debit_note_no or self.debit_note_no
        if not debit_note_to_validate:
            return True

        if not debit_note_to_validate.isdigit():
            frappe.throw("El número de Nota de Débito solo debe contener números.")

        draft_submitted_filters = {
            'is_debit_note': True,
            'company': self.company,
            'name': ['!=', self.name],
            'debit_note_no': debit_note_to_validate,
            'docstatus': ['in', [0, 1]],
        }

        void_filters = {
            'is_debit_note': True,
            'company': self.company,
            'name': ['!=', self.name],
            'debit_note_no': debit_note_to_validate,
            'docstatus': 2,
            'is_void': 1,
        }

        duplicated_docs = frappe.db.get_all('Sales Invoice',
                                            filters=draft_submitted_filters,
                                            pluck='name') or []

        duplicated_docs.extend(frappe.db.get_all('Sales Invoice',
                                                 filters=void_filters,
                                                   pluck='name') or [])
        if duplicated_docs:
            duplicated_msg = []
            for duplicated in set(duplicated_docs):
                link = get_link_to_form(self.doctype, duplicated)
                msg = \
                f"El número de Nota de Débito {debit_note_to_validate} " \
                f"ya está siendo usado en el documento {link}. Corrija e intente nuevamente."
                duplicated_msg.append(msg)

            if raise_throw:
                frappe.throw(duplicated_msg,
                             title="Advertencia de Duplicado",
                             as_list=True)
            return False

        return True

    def validate_withholding_voucher_number(self) -> None:
        if self.vat_withholding_voucher_number:

            if not self.vat_withholding_voucher_number.isdigit():
                frappe.throw("El número de comprobante de retención "
                "de IVA debe contener solo números.")

            if len(self.vat_withholding_voucher_number) != 14:
                frappe.throw("El número de comprobante de retención "
                "de IVA debe tener exactamente 14 caracteres.")

    def set_title_field(self) -> None:
        super().set_title_field()
        if self.docstatus == 0:
            return
        if self.is_return:
            self.title = self.credit_note_no

        elif self.is_debit_note:
            self.title = self.debit_note_no

        else:
            self.title = self.bill_no

    def get_gl_entries(self, warehouse_account=None):
        """
        Crea y retorna los asientos contables para la factura de venta.
        Este método sobrescribe el original para permitir un orden personalizado
        en la generación de los asientos.
        """
        gl_entries = []

        self.make_customer_gl_entry(gl_entries)
        self.make_tax_gl_entries(gl_entries)
        self.make_item_gl_entries(gl_entries)
        self.make_gl_entries_for_tax_withholding(gl_entries)
        self.make_discount_gl_entries(gl_entries)
        self.make_internal_transfer_gl_entries(gl_entries)
        gl_entries = make_regional_gl_entries(gl_entries, self)

        self.make_loyalty_point_redemption_gle(gl_entries)
        self.make_pos_gl_entries(gl_entries)
        self.make_write_off_gl_entry(gl_entries)
        self.make_gle_for_rounding_adjustment(gl_entries)
        self.make_precision_loss_gl_entry(gl_entries)
        self.set_transaction_currency_and_rate_in_gl_map(gl_entries)

        for gl in gl_entries:
            gl.bill_control = self.bill_control
            gl.bill_no = self.bill_no or self.credit_note_no or self.debit_note_no

        return gl_entries

    def make_customer_gl_entry(self, gl_entries):
        # Checked both rounding_adjustment and rounded_total
        # because rounded_total had value even before introduction of posting GLE based on rounded total
        grand_total = (
            self.rounded_total if (self.rounding_adjustment and self.rounded_total) else self.grand_total
        )
        base_grand_total = flt(
            self.base_rounded_total
            if (self.base_rounding_adjustment and self.base_rounded_total)
            else self.base_grand_total,
            self.precision("base_grand_total"),
        ) + flt(self.total_withholding * self.conversion_rate, self.precision("base_grand_total"))

        if grand_total and not self.is_internal_transfer():
            against_voucher = self.name
            if self.is_return and self.return_against and not self.update_outstanding_for_self:
                against_voucher = self.return_against

            # Did not use base_grand_total to book rounding loss gle
            gl_entries.append(
                self.get_gl_dict(
                    {
                        "account": self.debit_to,
                        "party_type": "Customer",
                        "party": self.customer,
                        "due_date": self.due_date,
                        "against": self.against_income_account,
                        "debit": base_grand_total,
                        "debit_in_account_currency": base_grand_total
                        if self.party_account_currency == self.company_currency
                        else grand_total,
                        "debit_in_transaction_currency": grand_total,
                        "against_voucher": against_voucher,
                        "against_voucher_type": self.doctype,
                        "cost_center": self.cost_center,
                        "project": self.project,
                    },
                    self.party_account_currency,
                    item=self,
                )
            )

    def make_tax_gl_entries(self, gl_entries) -> None:
        enable_discount_accounting = cint(
            frappe.db.get_single_value("Selling Settings", "enable_discount_accounting")
        )

        for tax in self.get("taxes"):
            if tax.is_tax_withholding_account:
                continue

            amount, base_amount = self.get_tax_amounts(tax, enable_discount_accounting)

            if flt(tax.base_tax_amount_after_discount_amount):
                account_currency = get_account_currency(tax.account_head)

                if tax.charge_type == 'VAT':
                    debit_or_credit = 'credit'
                else:
                    debit_or_credit = 'debit'

                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": tax.account_head,
                            "against": self.customer,
                            debit_or_credit: flt(base_amount, tax.precision("tax_amount_after_discount_amount")),
                            f"{debit_or_credit}_in_account_currency": (
                                flt(base_amount, tax.precision("base_tax_amount_after_discount_amount"))
                                if account_currency == self.company_currency
                                else flt(amount, tax.precision("tax_amount_after_discount_amount"))
                            ),
                            f"{debit_or_credit}_in_transaction_currency": flt(
                                amount, tax.precision("tax_amount_after_discount_amount")
                            ),
                            "cost_center": tax.cost_center,
                        },
                        account_currency,
                        item=tax,
                    )
                )

    def make_gl_entries_for_tax_withholding(self, gl_entries):

        enable_discount_accounting = cint(
            frappe.db.get_single_value("Selling Settings", "enable_discount_accounting")
        )

        for tax in self.get("taxes"):
            if not tax.is_tax_withholding_account:
                continue

            amount, base_amount = self.get_tax_amounts(tax, enable_discount_accounting)

            if flt(tax.base_tax_amount_after_discount_amount):

                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": self.debit_to,
                            "party_type": "Customer",
                            "party": self.customer,
                            "due_date": self.due_date,
                            "against": tax.account_head,
                            "credit": base_amount,
                            "credit_in_account_currency": base_amount,
                            "credit_in_transaction_currency": amount,
                            "against_voucher": self.name,
                            "against_voucher_type": self.doctype,
                            "cost_center": self.cost_center,
                            "project": self.project,
                        },
                        self.party_account_currency,
                        item=self,
                    )
                )
                account_currency = get_account_currency(tax.account_head)
                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account": tax.account_head,
                            "against": self.customer,
                            "debit": flt(base_amount, tax.precision("base_tax_amount_after_discount_amount")),
                            "debit_in_account_currency": (
                                flt(base_amount, tax.precision("base_tax_amount_after_discount_amount"))
                                if account_currency == self.company_currency
                                else flt(amount, tax.precision("tax_amount_after_discount_amount"))
                            ),
                            "debit_in_transaction_currency": flt(
                                amount, tax.precision("tax_amount_after_discount_amount")
                            ),
                            "cost_center": tax.cost_center,
                        },
                        account_currency,
                        item=tax,
                    )
                )

@frappe.whitelist()
def upload_voucher_data(docname,
                        voucher_number,
                        withholding_date,
                        file_url=None)-> dict:
    """
    Actualiza la Sales Invoice (Factura de Venta) con los datos del
    comprobante de retención.
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
        frappe.log_error(f"Sales Invoice {docname} no encontrada.",
                         "Error en upload_voucher_data")
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
def upload_islr_voucher_data(docname,
                             islr_date,
                             islr_receipt_number=None,
                             file_url=None)-> dict:
    """
    Actualiza la Sales Invoice (Factura de Venta)
    con los datos del comprobante de retención de ISLR.
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

@frappe.whitelist()
def void_document(doctype, name):
    """
    Marca el documento como anulado (is_void = 1).
    Solo se permite en documentos cancelados (docstatus = 2).
    """

    doc = frappe.get_doc(doctype, name)
    if doc.docstatus != 2:
        frappe.throw(_("Solo se pueden anular documentos que ya están cancelados."))

    def _check_for_duplicate_before_void(field_name,
                                         value_to_check,
                                         label)-> None:
        if not value_to_check:
            return

        filters = {
            field_name: value_to_check,
            "company": doc.company,
            "name": ["!=", doc.name],
        }

        # Busca en borradores (0), enviados (1) o anulados (is_void=1)
        duplicated_doc_name = (
            frappe.db.get_value(doctype, {**filters, "docstatus": ["in", [0, 1]]}, "name") or
            frappe.db.get_value(doctype, {**filters, "is_void": 1}, "name")
        )

        if duplicated_doc_name:
            link = get_link_to_form(doctype, duplicated_doc_name)
            message = _(
                "No se puede anular este documento porque el {label} '{value}' "
                "ya está siendo utilizado por el documento {link}. "
                "Este número debe ser liberado primero."
            ).format(label=label, value=frappe.bold(value_to_check), link=link)
            frappe.throw(message, title=_("Anulación Bloqueada por Duplicado"))

    if doc.is_return:
        _check_for_duplicate_before_void("credit_note_no",
                                         doc.credit_note_no,
                                         _("número de nota de crédito"))
    elif doc.is_debit_note:
        _check_for_duplicate_before_void("debit_note_no",
                                          doc.debit_note_no,
                                            _("número de nota de débito"))
    else:
        _check_for_duplicate_before_void("bill_no",
                                         doc.bill_no,
                                         _("número de factura"))

    _check_for_duplicate_before_void("bill_control",
                                     doc.bill_control,
                                       _("número de control"))

    frappe.db.set_value(doctype, name, "is_void", True)
    doc.add_comment("Comment", _("Documento marcado como Anulado."))

    frappe.clear_document_cache(doctype, name)
    doc.reload()


@frappe.whitelist()
def create_exchange_difference_entry(docname: str, account: str = None) -> dict:
    """
    Crea un Journal Entry para liquidar el diferencial cambiario
    de una factura de venta con saldo pendiente en moneda base.
    """
    sales_invoice = frappe.get_doc("Sales Invoice", docname)

    if sales_invoice.docstatus != 1:
        frappe.throw("La factura debe estar enviada para registrar diferencial cambiario")

    outstanding = flt(sales_invoice.outstanding_amount, 2)

    if outstanding == 0:
        frappe.throw("La factura no tiene saldo pendiente")

    # Si se pasa un cuenta, se usa esa. Si no, se busca la predeterminada.
    exchange_gain_loss_account = account

    if not exchange_gain_loss_account:
        accounts = frappe.get_cached_value(
            "Company",
            sales_invoice.company,
            [
                "unrealized_profit_loss_account",
                "unrealized_exchange_gain_loss_account",
                "exchange_gain_loss_account",
            ],
            as_dict=True,
        )

        primary_account = (
            accounts.unrealized_profit_loss_account
            if outstanding > 0
            else accounts.unrealized_exchange_gain_loss_account
        )

        exchange_gain_loss_account = primary_account or accounts.exchange_gain_loss_account

    if not exchange_gain_loss_account:
        frappe.throw(
            f"Configure la cuenta de Ganancia/Pérdida por Diferencial Cambiario "
            f"en la Compañía {sales_invoice.company}"
        )

    journal_entry = frappe.new_doc("Journal Entry")
    journal_entry.voucher_type = "Exchange Gain Or Loss"
    journal_entry.posting_date = sales_invoice.posting_date
    journal_entry.company = sales_invoice.company

    journal_entry.append("accounts", {
        "account": exchange_gain_loss_account,
        "debit_in_account_currency": outstanding if outstanding > 0 else 0,
        "credit_in_account_currency": abs(outstanding) if outstanding < 0 else 0,
        "cost_center": sales_invoice.cost_center,
    })

    journal_entry.append("accounts", {
        "account": sales_invoice.debit_to,
        "party_type": "Customer",
        "party": sales_invoice.customer,
        "credit_in_account_currency": outstanding if outstanding > 0 else 0,
        "debit_in_account_currency": abs(outstanding) if outstanding < 0 else 0,
        "reference_type": "Sales Invoice",
        "reference_name": sales_invoice.name,
        "cost_center": sales_invoice.cost_center,
    })

    journal_entry.remark = (
        f"Diferencial cambiario por factura {sales_invoice.name}"
    )
    journal_entry.insert(ignore_permissions=True)
    journal_entry.submit()

    return {
        "status": "success",
        "journal_entry": journal_entry.name,
        "amount": outstanding,
    }
