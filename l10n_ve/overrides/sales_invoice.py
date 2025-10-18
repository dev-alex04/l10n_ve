import frappe
from frappe import _, _dict
from frappe.utils import flt
from frappe.model.document import Document

from erpnext.utilities.utils import get_link_to_form
from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from l10n_ve.utils.utils import validate_return_in_same_month
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class CustomSalesInvoice(SalesInvoice):

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
        """
        Llamado antes de que el documento sea enviado.
        Asigna números de control
        y de factura si no existen.
        """
        super().before_submit()
        self.set_control_and_invoice_number()
        self.set_title_field()

    def validate(self) -> None:
        super().validate()

        self.validate_withholding_voucher_number()
        self.set_control_and_invoice_number()
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
        Valida que el número de control no esté ya asignado,
        considerando documentos Aprobados (docstatus 1) o Cancelados (docstatus 2)
        que NO hayan sido anulados (is_void 0).
        """

        bill_control_to_validate = bill_control or self.bill_control
        if not bill_control_to_validate:
            return True


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
                                            pluck='name') or []

        duplicated_docs.extend(frappe.db.get_all('Sales Invoice',
                                                 filters=void_filters,
                                                 pluck='name') or [])

        if duplicated_docs:
            duplicated_msg = []
            if self.is_return:
                doc_type_str = "Nota de Crédito"
            elif self.is_debit_note:
                doc_type_str = "Nota de Débito"
            else:
                doc_type_str = "Factura"

            for duplicated in set(duplicated_docs):
                link = get_link_to_form(self.doctype, duplicated)
                msg = \
                f"El número de control {bill_control_to_validate} " \
                f"ya está siendo usado en la {doc_type_str} {link}. Corrija e intente nuevamente."
                duplicated_msg.append(msg)

            frappe.throw(duplicated_msg, title="Advertencia de Duplicado", as_list=True)

        return True

    def _validate_bill_no(self, bill_no: str = '', raise_throw: bool = True) -> bool:
        """
        Valida que el número de factura no esté ya asignado.
        Acepta un valor opcional para validar.
        """

        if any([
            self.is_return,
            self.is_debit_note
        ]):
            return True

        bill_no_to_validate = bill_no or self.bill_no
        if not bill_no_to_validate:
            return True

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

        duplicated_docs = frappe.db.get_all('Sales Invoice',
                                            filters=draft_submitted_filters,
                                            pluck='name') or []

        duplicated_docs.extend(frappe.db.get_all('Sales Invoice',
                                                 filters=void_filters,
                                                 pluck='name') or [])

        if duplicated_docs:
            duplicated_msg = []
            for duplicated in set(duplicated_docs):
                invoice_link: str = get_link_to_form(self.doctype, duplicated)
                msg = (
                    f'El número de factura {bill_no_to_validate} ya está siendo '
                    f'usado en otro documento {invoice_link}. '
                    f'Corrija e intente nuevamente.'
                )
                duplicated_msg.append(msg)

            if raise_throw:
                frappe.throw(duplicated_msg,
                             title="Advertencia de Duplicado",
                             as_list=True)
            else:
                return False

        return True

    def _validate_credit_note_no(self,
                                 credit_note_no: str = '',
                                 raise_throw: bool = True) -> bool:
        """
        Valida que el número de Nota de Crédito no esté ya asignado.
        """

        credit_note_to_validate = credit_note_no or self.credit_note_no
        if not credit_note_to_validate:
            return True

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

    # ------------------------------ OVERRIDES ------------------------------ #

    def set_taxes_and_charges(self) -> None:
        super().set_taxes_and_charges()

        self.set_tax_withholding_ve()

    def set_tax_withholding(self) -> None:
        """
        Se inactiva la funcion nativa para obtener las retenciones.
        La funcion set_tax_withholding_ve  se encargara de esto
        """
        return

    # TODO: Refactorizar a una sola funcion para usar en ventas y compras
    def set_tax_withholding_ve(self) -> None:

        if not bool(frappe.db.get_value('Customer',
                                        self.customer,
                                        'is_special_taxpayer')):
            return

        withholding_category_name: str = frappe.db.get_value(
            "Company",
            self.company,
            "tax_withholding_category")

        if not withholding_category_name:
            return

        withholding_category: Document = frappe.get_doc(
            "Tax Withholding Category",
            withholding_category_name)

        withholding: _dict = withholding_category.get_withholding(self.company,
                                                                  self.doctype)
        if self.is_return:
            if not self.return_against:
                return

            withholding['description'] = \
                f'{withholding.description} por Nota de Crédito contra factura {self.affected_invoice_number}'

        elif self.is_debit_note:

            withholding.description = \
                f'{withholding["description"]} por Nota de Crédito contra factura {self.affected_invoice_number}'

        # Primero se limpia la tabla de impuestos
        # Dejando solo los impuestos que no sean retencion de IVA
        self.taxes = [
            tax
            for tax in self.taxes or []
            if tax.get('charge_type') != withholding.get('charge_type')
        ]

        self.append("taxes", withholding)

    def calculate_total_withholding(self) -> None:

        self.total_withholding = 0.0

        self.total_withholding = sum([
            tax.tax_amount
            for tax in self.taxes or []
            if tax.is_tax_withholding_account
        ])

    def make_tax_gl_entries(self, gl_entries) -> None:

        """
        Override para solo hacer los asientos que NO sean de retenciones
        """

        for tax in self.get("taxes"):

            if not tax.tax_amount:
                continue

            account_currency = get_account_currency(tax.account_head)

            if tax.charge_type == 'VAT':
                debit_or_credit = 'credit'
            else:
                debit_or_credit = 'debit'


            gl_entries.append(
                self.get_gl_dict(
                    {
                        "against": self.customer,
                        "account": tax.account_head,
                        "cost_center": tax.cost_center,
                        debit_or_credit: flt(tax.tax_amount),
                        f"{debit_or_credit}_in_account_currency": tax.tax_amount,
                    },
                    account_currency,
                    item=tax,
                ))

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
