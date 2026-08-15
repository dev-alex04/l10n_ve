from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import flt, cint, getdate, nowdate

from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice, make_regional_gl_entries

if TYPE_CHECKING:
    from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry
    from erpnext.accounts.doctype.sales_taxes_and_charges.sales_taxes_and_charges import (
        SalesTaxesandCharges,
    )

from l10n_ve.overrides.company import CustomCompany
from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.permissions import has_accounting_permission
from l10n_ve.utils.utils import validate_return_in_same_month, get_link_to_form, validate_portal_upload, delete_old_attachment, is_period_open


def closed_period_msg() -> str:
    """Mensaje único del candado de quincenas.

    Lo comparten la validación del documento y los dos endpoints del portal (IVA e
    ISLR). Es función y no constante de módulo a propósito: `_()` resuelve contra el
    idioma de la sesión, que a nivel de módulo todavía no existe.
    """
    return _(
        "La fecha del comprobante pertenece a una quincena o período anterior. "
        "Para ingresar comprobantes de quincenas pasadas, debe comunicarse con el "
        "personal de Contabilidad."
    )


class VESalesInvoice(TaxesMixin, SalesInvoice):

    def set_total_in_words(self) -> None:
        """Fuerza la generación de 'in_words' y 'base_in_words' siempre en Español ('es').

        Evita que se genere el texto en inglés ('Thirty Six Thousand... only') cuando
        la sesión o configuración del sistema es en inglés.
        """
        original_lang = getattr(frappe.local, "lang", "es")
        try:
            frappe.local.lang = "es"
            super().set_total_in_words()
        finally:
            frappe.local.lang = original_lang

        if not self.base_in_words and self.in_words:
            if self.currency == self.company_currency or "VEF" in self.in_words:
                self.base_in_words = self.in_words

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
        self._set_pending_hka_status()

    def _set_pending_hka_status(self) -> None:
        """Marca la factura como Pendiente de emisión HKA al validarla.

        Solo aplica a facturas normales (no NC/ND legacy) cuya sucursal tiene
        una serie de facturación digital activa. En before_submit el valor se
        persiste con el propio submit, sin db_set.
        """
        if self.is_return or self.get("is_debit_note"):
            return

        if self._get_active_digital_series():
            self.hka_status = "Pendiente"

    def before_cancel(self) -> None:
        self._block_cancel_if_has_active_notes()
        self._block_cancel_if_digitally_signed()
        super().before_cancel()

    def _block_cancel_if_has_active_notes(self) -> None:
        """
        Bloquea la cancelación si la factura tiene una Nota de Crédito o
        Nota de Débito venezolana activa (docstatus=1).

        Regla de negocio: para anular una factura con NC/ND, primero se
        deben anular los documentos dependientes.
        """
        active_nc: dict | None = frappe.db.get_value(
            "VE Sales Credit Note",
            {"return_against": self.name, "docstatus": 1},
            ["name", "bill_no"],
            as_dict=True,
        )
        if active_nc:
            nc_bill: str = active_nc.bill_no or active_nc.name
            nc_link: str = (
                f'<a href="/app/ve-sales-credit-note/{active_nc.name}">'
                f'{nc_bill}</a>'
            )
            frappe.throw(
                _(
                    "No se puede anular la factura <b>{0}</b> porque tiene "
                    "una Nota de Crédito activa: {1}. "
                    "Anule primero la Nota de Crédito."
                ).format(self.name, nc_link),
                title=_("Cancelación Bloqueada — NC Activa"),
            )

        active_nd: dict | None = frappe.db.get_value(
            "VE Sales Debit Note",
            {"return_against": self.name, "docstatus": 1},
            ["name", "bill_no"],
            as_dict=True,
        )
        if active_nd:
            nd_bill: str = active_nd.bill_no or active_nd.name
            nd_link: str = (
                f'<a href="/app/ve-sales-debit-note/{active_nd.name}">'
                f'{nd_bill}</a>'
            )
            frappe.throw(
                _(
                    "No se puede anular la factura <b>{0}</b> porque tiene "
                    "una Nota de Débito activa: {1}. "
                    "Anule primero la Nota de Débito."
                ).format(self.name, nd_link),
                title=_("Cancelación Bloqueada — ND Activa"),
            )

    def _block_cancel_if_digitally_signed(self) -> None:
        """
        Bloquea la cancelación si la factura ya tiene número de documento
        y/o número de control asignados por la imprenta digital (TFHKA).

        La excepción es cuando `_hka_void_confirmed = True` está establecido
        en la instancia: indica que `void_sales_invoice()` ya confirmó la
        anulación con HKA y está ejecutando el cancel() de forma controlada.

        Solo se activa cuando la facturación digital está habilitada.
        """
        if getattr(self, "_hka_void_confirmed", False):
            return

        try:
            tfhka_enabled = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "enabled"
            )
        except frappe.DoesNotExistError:
            tfhka_enabled = False

        if not tfhka_enabled:
            return

        if self.bill_no or self.bill_control:
            frappe.throw(
                _(
                    "La factura <b>{0}</b> ya tiene número de documento fiscal "
                    "<b>{1}</b> y número de control <b>{2}</b> asignados por la "
                    "imprenta digital (TFHKA). No puede ser cancelada directamente. "
                    "Use el botón <b>'Anular en HKA'</b> o emita una Nota de Crédito."
                ).format(
                    self.name,
                    self.bill_no or "—",
                    self.bill_control or "—",
                ),
                title=_("Cancelación Bloqueada — Facturación Digital"),
            )

    def validate(self) -> None:
        super().validate()

        self.validate_withholding_voucher_number()
        self.validate_withholding_date_period()
        self.set_affected_invoice_number()
        self.validate_return_in_same_month()

        # validación de numero de control, debito, credito y de factura
        self._validate_bill_no(raise_throw=True)
        self._validate_bill_control(raise_throw=True)
        self._validate_debit_note_no(raise_throw=True)
        self._validate_credit_note_no(raise_throw=True)

        self._set_base_total_with_vat()

    def validate_return_in_same_month(self) -> None:
        """
        Valida que una Nota de Crédito o Débito se cree en el mismo mes
        que la factura original a la que hace referencia.
        Llama a la función centralizada en utils.
        """
        validate_return_in_same_month(self)

    def set_control_and_invoice_number(self) -> None:
        """
        Si TFHKA está activo globalmente, los números de factura y control
        son asignados exclusivamente por HKA (ya sea en modo Interno o Tercero).
        El ERP nunca debe asignar correlativos propios mientras HKA esté habilitado.
        """
        try:
            tfhka_enabled = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "enabled"
            )
        except frappe.DoesNotExistError:
            tfhka_enabled = False

        if tfhka_enabled:
            return

        company = frappe.get_doc('Company', self.company)
        self.set_invoice_number(company)
        self.set_control_number(company)

    def _get_active_digital_series(self) -> 'frappe.Document | None':
        """
        Retorna el documento VE Digital Billing Series activo para la sucursal
        de esta factura, buscando en la tabla hija 'VE Digital Billing Series Branch'.

        Retorna None si TFHKA no está habilitado o si la sucursal no está
        configurada en ninguna serie activa (el sistema cae al flujo legacy).
        """
        try:
            tfhka_enabled = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "enabled"
            )
        except frappe.DoesNotExistError:
            return None

        if not tfhka_enabled:
            return None

        if not self.branch:
            return None

        row = frappe.db.sql("""
            SELECT child.parent AS series_name
            FROM `tabVE Digital Billing Series Branch` child
            INNER JOIN `tabVE Digital Billing Series` serie
                ON serie.name = child.parent
            WHERE child.branch  = %s
              AND serie.company = %s
              AND serie.status  = 'Active'
            LIMIT 1
        """, (self.branch, self.company), as_dict=True)

        if not row:
            return None

        return frappe.get_doc("VE Digital Billing Series", row[0]["series_name"])

    def _get_hka_cutoff_date(self) -> 'date | None':
        """
        Retorna la fecha de corte a partir de la cual se inicia la numeración HKA.
        Se usa para ignorar duplicados del sistema legacy al validar bill_no y bill_control.

        Orden de prioridad:
        1. start_operations de la VE Digital Billing Series activa para la sucursal.
        2. start_operations global de TFHKA Settings (fallback cuando branch está vacío).
        3. None si TFHKA no está activo.
        """
        try:
            tfhka_enabled = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "enabled"
            )
        except frappe.DoesNotExistError:
            return None

        if not tfhka_enabled:
            return None

        digital_series = self._get_active_digital_series()
        if digital_series and digital_series.start_operations:
            return getdate(digital_series.start_operations)

        try:
            cutoff_raw = frappe.get_cached_value(
                "TFHKA Settings", "TFHKA Settings", "start_operations"
            )
            if cutoff_raw:
                return getdate(cutoff_raw)
        except frappe.DoesNotExistError:
            pass

        return None

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

        import re
        if not re.match(r'^[A-Za-z0-9\-]+$', bill_control_to_validate):
            frappe.throw("El número de control solo debe contener letras, números y guiones.")

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

        cutoff = self._get_hka_cutoff_date()
        if cutoff:
            duplicated_docs = [
                d for d in duplicated_docs
                if not (d.posting_date and getdate(d.posting_date) < cutoff)
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

    def _get_series_branches(self) -> list[str]:
        """Retorna las branches que comparten la misma serie digital que esta factura.

        Si la factura no tiene branch o TFHKA no está activo, retorna lista vacía
        (el caller debe usar filtro por company como fallback).
        """
        series_doc = self._get_active_digital_series()
        if not series_doc:
            return []

        return [
            row.branch for row in series_doc.get("branches", [])
            if row.branch
        ]

    def _validate_bill_no(self, bill_no: str = '', raise_throw: bool = True) -> bool:
        """Valida que el número de factura no esté ya asignado dentro de la misma serie.

        La unicidad del bill_no es por serie digital (VE Digital Billing Series),
        no por empresa. Una serie puede agrupar múltiples branches.

        Si TFHKA no está activo, cae al filtro legacy por empresa.
        Si TFHKA está activo, ignora duplicados cuya posting_date sea anterior
        a la fecha start_operations de la serie digital activa.
        """

        if any([self.is_return, self.is_debit_note]):
            return True

        bill_no_to_validate = bill_no or self.bill_no
        if not bill_no_to_validate:
            return True

        if not bill_no_to_validate.isdigit():
            frappe.throw("El número de factura solo debe contener números.")

        series_branches: list[str] = self._get_series_branches()

        base_filters: dict = {
            'is_return': False,
            'is_debit_note': False,
            'name': ['!=', self.name],
            'bill_no': bill_no_to_validate,
        }

        if series_branches:
            base_filters['branch'] = ['in', series_branches]
        else:
            base_filters['company'] = self.company

        draft_submitted_filters = {
            **base_filters,
            'docstatus': ['in', [0, 1]],
        }

        void_filters = {
            **base_filters,
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

        cutoff = self._get_hka_cutoff_date()
        if cutoff:
            duplicated_docs = [
                d for d in duplicated_docs
                if not (d.posting_date and getdate(d.posting_date) < cutoff)
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

    def validate_withholding_date_period(self) -> None:
        """Impide fijar la fecha del comprobante de IVA en una quincena ya declarada.

        Solo valida cuando la fecha *cambia*. `is_period_open` compara contra hoy, no
        contra el documento, así que toda quincena termina cerrándose: sin este filtro
        una factura registrada de forma legítima quedaba imposible de guardar semanas
        después, y por cualquier edición ajena a la retención.
        """
        if not self.withholding_date:
            return

        if not self.is_new() and not self.has_value_changed("withholding_date"):
            return

        if is_period_open(self.withholding_date, "IVA"):
            return

        if not has_accounting_permission():
            frappe.throw(closed_period_msg())

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

    def set_status(self, update: bool = False, status: str | None = None, update_modified: bool = True) -> None:
        """
        ERPNext computa "Credit Note Issued" buscando un Sales Invoice con is_return=1.
        Pero la NC venezolana es VE Sales Credit Note — otro doctype — por lo que la
        consulta original no la encuentra y la SI queda como "Paid" (verde) en vez de
        "Credit Note Issued" (gris).

        Se llama al super() SIN actualizar BD, luego se corrige el status si hay una
        NC venezolana vinculada, y finalmente se hace un único db_set.
        """
        super().set_status(update=False, status=status, update_modified=update_modified)

        # Early-exit: solo buscar NC en DB cuando el status calculado por super()
        # fuera "Paid" Y la factura tiene outstanding = 0. Evita un db.exists()
        # en el 99% de los casos donde la SI está en Draft, Unpaid o Overdue.
        if (
            self.status == "Paid"
            and not cint(self.is_return)
            and flt(self.outstanding_amount) <= 0
            and frappe.db.exists(
                "VE Sales Credit Note",
                {"return_against": self.name, "docstatus": 1},
            )
        ):
            self.status = "Credit Note Issued"

        if (
            self.status not in ("Credit Note Issued",)
            and not cint(self.is_return)
            and not cint(self.is_debit_note)
            and frappe.db.exists(
                "VE Sales Debit Note",
                {"return_against": self.name, "docstatus": 1},
            )
        ):
            self.status = "Debit Note Issued"

        if cint(self.is_void):
            self.status = "Void"

        if update:
            self.db_set("status", self.status, update_modified=update_modified)

    def on_cancel(self) -> None:
        """
        ERPNext hardcodea db_set('status', 'Cancelled') en on_cancel (línea 570),
        saltándose set_status(). Corregimos el status a 'Void' después de que
        el super() termina toda su lógica de cancelación.
        """
        super().on_cancel()

        if cint(self.is_void):
            self.db_set("status", "Void")
            self.status = "Void"

    def set_indicator(self) -> None:
        """
        Sobrescribe el indicador de portal usando el status ya calculado
        por set_status(), sin consultas adicionales a la BD.
        """
        if self.status == "Credit Note Issued":
            self.indicator_title = _("Credit Note Issued")
            self.indicator_color = "gray"
        elif self.status == "Debit Note Issued":
            self.indicator_title = _("Debit Note Issued")
            self.indicator_color = "orange"
        else:
            super().set_indicator()

    def make_precision_loss_gl_entry(self, gl_entries) -> None:
        """Cancela el asiento de pérdida de precisión cuando el método VE es
        "Desde el total de la factura" o si el documento es un retorno.

        Mismo principio que en Purchase Invoice: el ancla reduce intencionalmente
        base_net_amount respecto a net_amount × conversion_rate. ERPNext detecta
        esa brecha como "precision_loss" y añade un GL extra que rompe el cuadre.
        Con el ancla activa, la diferencia ya está absorbida por base_grand_total.
        """
        from l10n_ve.controllers.taxes_and_totals import TAX_FROM_TOTAL

        # En retornos, la diferencia ya está absorbida por el reverso contable de bases heredadas
        if self.is_return:
            return

        if self._is_multicurrency_doc():
            method = frappe.get_cached_value(
                "Venezuela Account Settings", "Venezuela Account Settings",
                "tax_calculation_method",
            ) or ""
            if method == TAX_FROM_TOTAL:
                return

        super().make_precision_loss_gl_entry(gl_entries)

    def _is_multicurrency_doc(self) -> bool:
        """True si el documento usa moneda distinta a la de la compañía."""
        try:
            company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
            return bool(company_currency) and self.currency != company_currency
        except Exception:
            return False

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
            gl.bill_no = self.bill_no

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
        ) + sum(
            flt(tax.base_tax_amount_after_discount_amount)
            for tax in self.get("taxes")
            if cint(tax.is_tax_withholding_account)
        )

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

            if not flt(tax.base_tax_amount_after_discount_amount):
                continue

            account_currency = get_account_currency(tax.account_head)

            debit_or_credit = 'credit' if tax.add_deduct_tax == 'Add' else 'debit'

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

        # Mismo patrón que make_customer_gl_entry: cuando es una devolución (NC),
        # la entrada de CxC debe apuntar al voucher ORIGINAL para que
        # update_outstanding_amt lo incluya en el cálculo del SI original.
        is_return_linked = (
            self.is_return
            and self.return_against
            and not self.update_outstanding_for_self
        )
        against_voucher = self.return_against if is_return_linked else self.name
        against_voucher_type = "Sales Invoice" if is_return_linked else self.doctype

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
                            "against_voucher": against_voucher,
                            "against_voucher_type": against_voucher_type,
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
def upload_voucher_data(docname, voucher_number, withholding_date, file_url=None, registration_date=None) -> dict:
    try:
        if not withholding_date or not file_url:
            frappe.throw(_("Faltan datos obligatorios."))

        if file_url:
            validate_portal_upload(file_url, 5)

        invoice_doc = frappe.get_doc("Sales Invoice", docname)

        if not has_accounting_permission():
            if not is_period_open(withholding_date, "IVA"):
                frappe.throw(closed_period_msg())

            current_date = invoice_doc.get("withholding_date")
            if current_date and not is_period_open(current_date, "IVA"):
                frappe.throw(_("El periodo de declaración para esta retención de IVA ha finalizado. Debe comunicarse con el departamento de soporte."))

        delete_old_attachment(invoice_doc, "voucher_image", file_url)

        file_doc_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if file_doc_name:
            frappe.db.set_value("File", file_doc_name, {
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": docname
            })

        registration_date = registration_date if registration_date else nowdate()

        frappe.db.set_value("Sales Invoice", docname, {
            'vat_withholding_voucher_number': voucher_number,
            'withholding_date': withholding_date,
            'voucher_image': file_url,
            'vat_registration_date': registration_date
        }, update_modified=True)

        comment = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": "Sales Invoice",
            "reference_name": docname,
            "content": f"Comprobante de Retención de IVA cargado. Número: {voucher_number}. Fecha: {withholding_date}",
            "comment_email": frappe.session.user
        })
        comment.flags.ignore_permissions = True
        comment.insert(ignore_permissions=True)

        return {"status": "success", "msg": "Guardado exitosamente."}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error IVA Portal")
        return {"status": "error", "msg": str(e)}


@frappe.whitelist()
def upload_islr_voucher_data(docname, islr_date, islr_receipt_number=None, file_url=None, registration_date=None) -> dict:
    try:
        if not islr_date or not file_url:
            frappe.throw(_("La fecha y el archivo del comprobante de ISLR son obligatorios."))

        if file_url:
            validate_portal_upload(file_url, 5)

        invoice_doc = frappe.get_doc("Sales Invoice", docname)

        if not has_accounting_permission():
            if not is_period_open(islr_date, "ISLR"):
                frappe.throw(closed_period_msg())

            current_date = invoice_doc.get("islr_date")
            if current_date and not is_period_open(current_date, "ISLR"):
                frappe.throw(_("El periodo de declaración para esta retención de ISLR ha finalizado. Debe comunicarse con el departamento de soporte."))

        delete_old_attachment(invoice_doc, "voucher_image_islr", file_url)

        file_doc_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if file_doc_name:
            frappe.db.set_value("File", file_doc_name, {
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": docname
            })

        registration_date = registration_date if registration_date else nowdate()

        frappe.db.set_value("Sales Invoice", docname, {
            'islr_receipt_number': islr_receipt_number,
            'islr_date': islr_date,
            'voucher_image_islr': file_url,
            'islr_registration_date': registration_date
        }, update_modified=True)

        comment_text = f"Comprobante de Retención de ISLR actualizado. Número: {islr_receipt_number or 'S/N'}. Fecha: {islr_date}."
        
        comment = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": "Sales Invoice",
            "reference_name": docname,
            "content": comment_text,
            "comment_email": frappe.session.user
        })
        comment.flags.ignore_permissions = True
        comment.insert(ignore_permissions=True)

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante de ISLR."
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error ISLR Portal")
        return {"status": "error", "msg": str(e)}


@frappe.whitelist()
def upload_municipal_voucher_data(docname, municipal_date, municipal_receipt_number=None, file_url=None, registration_date=None) -> dict:
    try:
        if not municipal_date or not file_url:
            frappe.throw(_("La fecha y el archivo del comprobante Municipal son obligatorios."))

        if file_url:
            validate_portal_upload(file_url, 5)

        invoice_doc = frappe.get_doc("Sales Invoice", docname)

        if not has_accounting_permission():
            if not is_period_open(municipal_date, "Municipal"):
                frappe.throw(closed_period_msg())

            current_date = invoice_doc.get("municipal_date")
            if current_date and not is_period_open(current_date, "Municipal"):
                frappe.throw(_("El periodo de declaración para esta retención municipal ha finalizado. Debe comunicarse con el departamento de soporte."))

        delete_old_attachment(invoice_doc, "voucher_image_municipal", file_url)

        file_doc_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if file_doc_name:
            frappe.db.set_value("File", file_doc_name, {
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": docname
            })

        registration_date = registration_date if registration_date else nowdate()

        frappe.db.set_value("Sales Invoice", docname, {
            'municipal_receipt_number': municipal_receipt_number,
            'municipal_date': municipal_date,
            'voucher_image_municipal': file_url,
            'municipal_registration_date': registration_date
        }, update_modified=True)

        comment_text = f"Comprobante de Retención Municipal actualizado. Número: {municipal_receipt_number or 'S/N'}. Fecha: {municipal_date}."
        
        comment = frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": "Sales Invoice",
            "reference_name": docname,
            "content": comment_text,
            "comment_email": frappe.session.user
        })
        comment.flags.ignore_permissions = True
        comment.insert(ignore_permissions=True)

        return {
            "status": "success",
            "msg": "Factura de Venta actualizada con los datos del comprobante Municipal."
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error Municipal Portal")
        return {"status": "error", "msg": str(e)}

def _validate_void_authorization(doc) -> None:
    """Autorización para ANULAR (fiscalmente sensible), compartida por
    void_document y void_sales_invoice (HKA):

    - Solo el Gerente de Contabilidad (rol "Accounts Manager"); only_for exime a
      Administrator. Los botones del cliente se ocultan con la misma regla, pero
      esta validación es la garantía real (los métodos son whitelisted).
    - Si el documento tiene sucursal, el usuario además debe tener acceso a esa
      VE Branch (User Permission). Sin User Permissions de VE Branch el usuario
      es global (sin restricción por sucursal).
    """
    frappe.only_for("Accounts Manager")

    branch = doc.get("branch")
    if branch and frappe.session.user != "Administrator":
        allowed_branches = frappe.get_all(
            "User Permission",
            filters={"user": frappe.session.user, "allow": "VE Branch"},
            pluck="for_value",
            ignore_permissions=True,
        )
        if allowed_branches and branch not in allowed_branches:
            frappe.throw(
                _("No tienes acceso a la sucursal {0} para anular este documento.").format(branch)
            )


@frappe.whitelist()
def void_document(doctype, name):
    """
    Marca el documento como anulado (is_void = 1).
    Solo se permite en documentos cancelados (docstatus = 2).
    """

    doc = frappe.get_doc(doctype, name)
    _validate_void_authorization(doc)
    frappe.has_permission(doctype, ptype="cancel", doc=doc, throw=True)

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
def void_sales_invoice(
    docname: str,
    reason: str,
    void_date: str,
    void_time: str,
) -> dict:
    """
    Anula una Factura de Venta en TFHKA (HKA) y luego cancela el documento
    en Frappe, garantizando atomicidad entre ambos sistemas.

    La lógica de comunicación con HKA está centralizada en
    ``TFHKAClient.void_fiscal_document()``.

    Args:
        docname:   Nombre de la Sales Invoice.
        reason:    Motivo de anulación (texto libre).
        void_date: Fecha en formato DD/MM/YYYY (convertida por el cliente JS).
        void_time: Hora en HH:MM:SS (24h); se convierte a 12h internamente.
    """
    from l10n_ve.digital_invoice.tfhka_client import TFHKAClient

    invoice: "VESalesInvoice" = frappe.get_doc("Sales Invoice", docname)
    _validate_void_authorization(invoice)
    frappe.has_permission("Sales Invoice", ptype="cancel", doc=invoice, throw=True)

    if invoice.docstatus != 1:
        frappe.throw(_("Solo se pueden anular facturas aprobadas."))

    invoice._block_cancel_if_has_active_notes()

    # Pre-validar que la factura puede ser cancelada en Frappe ANTES de
    # contactar a HKA.  Si existen documentos vinculados (Payment Entry,
    # POS Closing, etc.), el cancel() fallaría después de ya haber anulado
    # en HKA, dejando un estado inconsistente.
    #
    # ignore_linked_doctypes replica la misma lista que ERPNext establece
    # en SalesInvoice.on_cancel() — estos doctypes se eliminan/revierten
    # durante el cancel() real, por lo que NO deben bloquear la
    # pre-validación (p. ej. GL Entry, Stock Ledger Entry).
    from frappe.model.delete_doc import (
        check_if_doc_is_dynamically_linked,
        check_if_doc_is_linked,
    )
    from erpnext.accounts.doctype.sales_invoice.sales_invoice import (
        check_if_return_invoice_linked_with_payment_entry,
    )

    invoice.ignore_linked_doctypes = (
        "GL Entry",
        "Stock Ledger Entry",
        "Repost Item Valuation",
        "Repost Payment Ledger",
        "Repost Payment Ledger Items",
        "Repost Accounting Ledger",
        "Repost Accounting Ledger Items",
        "Unreconcile Payment",
        "Unreconcile Payment Entries",
        "Payment Ledger Entry",
        "Serial and Batch Bundle",
    )

    invoice.check_if_consolidated_invoice()
    check_if_doc_is_linked(invoice, method="Cancel")
    check_if_doc_is_dynamically_linked(invoice, method="Cancel")
    check_if_return_invoice_linked_with_payment_entry(invoice)

    # Catálogo 1 SENIAT: 01=Factura, 02=NotaCredito, 03=NotaDebito
    if invoice.is_return:
        tipo_documento: str = "02"
    elif invoice.is_debit_note:
        tipo_documento = "03"
    else:
        tipo_documento = "01"

    client = TFHKAClient()
    client.void_fiscal_document(
        doc=invoice,
        reason=reason,
        void_date=void_date,
        void_time=void_time,
        tipo_documento=tipo_documento,
    )

    # HKA confirmó la anulación → persistir motivo, marcar como anulado y cancelar
    # Usamos db_set con update_modified=False para no alterar el timestamp
    # y evitar TimestampMismatchError al hacer cancel() → save()
    invoice.db_set("avoid_reason", reason, update_modified=False)
    invoice.db_set("is_void", True, update_modified=False)
    invoice.db_set("hka_status", "Anulada", update_modified=False)
    invoice.is_void = True
    invoice.hka_status = "Anulada"
    invoice._hka_void_confirmed = True
    invoice.cancel()
    invoice.add_comment("Comment", _("Factura anulada ante HKA. Motivo: {0}").format(reason))

    return {
        "status": "success",
        "message": _("Factura anulada correctamente en HKA y en el sistema."),
    }


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


# --------------------------------------------------------------------------- #
# Dashboard — conexiones de Sales Invoice                                      #
# --------------------------------------------------------------------------- #

def get_sales_invoice_dashboard_data(data: dict) -> dict:
    """
    Extiende el dashboard de conexiones de Sales Invoice para incluir
    VE Sales Credit Note en el grupo 'Returns' (Devoluciones).

    Este hook es llamado por Frappe DESPUÉS de que _dashboard.py ya cargó los
    grupos estándar, por lo que podemos buscar el grupo 'Returns' y agregarnos.

    El campo de enlace es return_against (Link → Sales Invoice en VE NC),
    que es no-estándar respecto al fieldname 'sales_invoice' del dashboard,
    por lo que se registra en non_standard_fieldnames.

    Nota: se compara el label sin traducir Y con traducción al locale activo
    para garantizar que la búsqueda funcione en instalaciones ES y EN.
    """
    # Candidatos que identifican el grupo 'Returns' independientemente del locale
    returns_candidates = {_("Returns"), "Returns", _("Devoluciones"), "Devoluciones"}

    for group in data.get("transactions", []):
        if group.get("label", "") in returns_candidates:
            items = group.get("items", [])
            if "VE Sales Credit Note" not in items:
                items.append("VE Sales Credit Note")
            break
    else:
        data.setdefault("transactions", []).append({
            "label": _("Returns"),
            "items": ["VE Sales Credit Note"],
        })

    data.setdefault("non_standard_fieldnames", {})["VE Sales Credit Note"] = "return_against"

    return data


@frappe.whitelist()
def make_replacement_invoice(source_name: str) -> "Document":
    """
    Crea un borrador de Sales Invoice a partir de una factura anulada (is_void=1).

    Reglas de mapeo:
    - posting_date y due_date = hoy
    - conversion_rate = tasa de hoy (de tabCurrency Exchange, si aplica)
    - Los campos fiscales (bill_no, bill_control, bill_date) se limpian para
      que la nueva factura inicie sin número HKA asignado.
    - Los períodos de servicio (from_date, to_date) y la suscripción se heredan,
      para que los hooks de domina_isp actúen correctamente al insertar.
    """
    from frappe.model.mapper import get_mapped_doc
    from frappe.utils import nowdate

    invoice = frappe.get_cached_doc("Sales Invoice", source_name)

    # Verificar permiso de lectura sobre la factura fuente y de creación de la nueva SI
    frappe.has_permission("Sales Invoice", ptype="read", doc=invoice, throw=True)
    frappe.has_permission("Sales Invoice", ptype="create", throw=True)

    if not cint(invoice.is_void):
        frappe.throw(_(
            "Solo se puede generar una factura de reemplazo desde una factura anulada (Void)."
        ))

    def _adjust_date_and_rate(source_doc, target_doc) -> None:
        hoy: str = nowdate()
        target_doc.posting_date = hoy
        target_doc.due_date = hoy

        if source_doc.get("branch"):
            target_doc.branch = source_doc.branch

        # Cortocircuito: si ambas monedas son iguales, la tasa es 1.0
        if target_doc.currency == source_doc.company_currency:
            target_doc.conversion_rate = 1.0
            target_doc.plc_conversion_rate = 1.0
            return

        # Actualizar tasa de cambio al día de hoy si la moneda difiere de la base
        tasa_hoy: float | None = frappe.db.get_value(
            "Currency Exchange",
            {
                "from_currency": target_doc.currency,
                "to_currency": source_doc.company_currency,
                "date": hoy,
            },
            "exchange_rate",
            order_by="modified desc",
        )
        if tasa_hoy:
            target_doc.conversion_rate = tasa_hoy
            target_doc.plc_conversion_rate = tasa_hoy

    return get_mapped_doc(
        "Sales Invoice",
        source_name,
        {
            "Sales Invoice": {
                "doctype": "Sales Invoice",
                "field_no_map": [
                    "name",
                    "naming_series",
                    "amended_from",
                    "is_return",
                    "return_against",
                    # Campos fiscales: la nueva factura debe obtener su propio número HKA
                    "bill_no",
                    "bill_date",
                    "bill_control",
                    "credit_note_no",
                    "debit_note_no",
                    "outstanding_amount",
                    "status",
                    "is_void",
                    "avoid_reason",
                    "conversion_rate",
                    "plc_conversion_rate",
                    # Retenciones: la nueva factura gestiona las propias
                    "vat_withholding_voucher_number",
                    "withholding_date",
                    "voucher_image",
                    "islr_receipt_number",
                    "islr_date",
                    "voucher_image_islr",
                ],
            },
            "Sales Invoice Item": {
                "doctype": "Sales Invoice Item",
                "field_no_map": ["name"],
            },
            "Sales Taxes and Charges": {
                "doctype": "Sales Taxes and Charges",
                "field_no_map": ["name"],
            },
        },
        postprocess=_adjust_date_and_rate,
        ignore_permissions=True,
    )


@frappe.whitelist()
def get_withholding_types(invoice_names: str) -> dict:
    """Retorna los tipos de retención activos para un lote de facturas.

    Consulta la tabla hija Sales Taxes and Charges para identificar
    qué retenciones (VAT Withholding / ISLR) tiene cada factura.

    Args:
        invoice_names: Lista JSON de nombres de Sales Invoice.

    Returns:
        dict con clave = nombre de factura, valor = {has_vat, has_islr}
    """
    import json

    names: list[str] = json.loads(invoice_names)
    if not names:
        return {}

    for name in names:
        frappe.has_permission("Sales Invoice", ptype="read", doc=name, throw=True)

    rows: list[dict] = frappe.db.sql(
        """
        SELECT parent, charge_type
        FROM `tabSales Taxes and Charges`
        WHERE parent IN %(names)s
          AND charge_type IN ('VAT Withholding', 'ISLR')
          AND tax_amount != 0
        """,
        {"names": names},
        as_dict=True,
    )

    result: dict = {}
    for row in rows:
        entry = result.setdefault(row.parent, {"has_vat": False, "has_islr": False})
        if row.charge_type == "VAT Withholding":
            entry["has_vat"] = True
        elif row.charge_type == "ISLR":
            entry["has_islr"] = True

    return result


@frappe.whitelist()
def fix_missing_withholding(
    invoice_name: str,
    withholding_type: str,
    tax_account: str,
    company: str,
    voucher_number: str = None,
    withholding_date: str = None,
    file_url: str = None,
    rate: float = 0.0,
    overwrite: int = 0,
    only_line: int = 0,
    registration_date: str = None
) -> dict:
    """Retroactively injects VAT/ISLR withholdings and their corresponding accounting entry into a submitted invoice.
    Handles rounding differences, fully paid invoices, and voucher replacement validations.
    """

    _require_withholding_permissions()

    invoice = get_verified_invoice(invoice_name, company)

    validate_withholding_tax_account(invoice, withholding_type, tax_account)

    is_overwrite = True if overwrite in [1, "1", True, "true", "True"] else False
    is_only_line = True if only_line in [1, "1", True, "true", "True"] else False
    charge_type = "VAT Withholding" if withholding_type == "VAT" else "ISLR"

    metadata_status = handle_voucher_metadata(
        invoice, withholding_type, voucher_number, withholding_date, file_url, is_overwrite, is_only_line, registration_date
    )
    if metadata_status.get("status") == "ask_overwrite":
        return metadata_status

    duplicate = any(t.charge_type == charge_type and t.account_head == tax_account for t in invoice.taxes)
    if duplicate:
        frappe.throw(_("La factura {0} ya tiene una retención de tipo {1} con la cuenta {2}.").format(invoice.name, charge_type, tax_account))

    company_currency = frappe.get_cached_value("Company", invoice.company, "default_currency") or "VEF"
    invoice_currency = invoice.currency or "USD"

    base_amount = calculate_withholding_base_amount(invoice, withholding_type)

    if invoice_currency != company_currency:
        conversion_rate = flt(invoice.conversion_rate) or flt(invoice.plc_conversion_rate)
        if not conversion_rate:
            frappe.throw(_("La factura {0} está en moneda extranjera ({1}) pero no tiene una tasa de cambio de conversión válida configurada.").format(invoice.name, invoice_currency))
        
        amount = flt(base_amount / conversion_rate, invoice.precision("tax_amount", "taxes") or 2)
    else:
        conversion_rate = 1.0
        amount = base_amount

    tax_row = create_sales_taxes_row(
        invoice, charge_type, tax_account, withholding_type, amount, base_amount, rate
    )

    je = create_withholding_journal_entry(
        invoice, withholding_type, tax_account, amount, base_amount, conversion_rate, 
        withholding_date, company_currency, invoice_currency
    )

    frappe.db.set_value(
        "Sales Taxes and Charges",
        tax_row.name,
        "description",
        f"Retención de {withholding_label(withholding_type)} (Ajuste) - Asiento: {je.name}"
    )

    invoice.reload()

    # La fila de retención acaba de nacer: si su comprobante no está registrado, la
    # factura tiene que quedar avisada. El reload() de arriba es lo que hace que
    # `invoice.taxes` ya la incluya.
    refresh_missing_withholding_voucher(invoice)

    sync_isp_payment_amounts_if_installed(invoice)

    return {"status": "success", "msg": f"Retención aplicada y Asiento {je.name} creado con éxito."}


def get_verified_invoice(invoice_name: str, company: str) -> "SalesInvoice":
    """Resolves the real invoice name (considering bill_no fallback) and returns the validated Sales Invoice document."""
    real_invoice_name = None
    
    if invoice_name:
        if frappe.db.exists("Sales Invoice", {"name": invoice_name, "company": company, "docstatus": 1}):
            real_invoice_name = invoice_name
        else:
            real_invoice_name = frappe.db.get_value("Sales Invoice", {"bill_no": invoice_name, "company": company, "docstatus": 1}, "name")

    if not real_invoice_name:
        frappe.throw(_("No se encontró ninguna factura aprobada (Submitted) con el identificador o número de control '{0}' para la empresa {1}.").format(invoice_name, company))

    invoice = frappe.get_doc("Sales Invoice", real_invoice_name)

    return invoice


def handle_voucher_metadata(
    invoice: "SalesInvoice",
    withholding_type: str,
    voucher_number: str,
    withholding_date: str,
    file_url: str,
    is_overwrite: bool,
    is_only_line: bool,
    registration_date: str
) -> dict:
    """Validates data completeness, handles overwrite warnings, and delegates
    the database updates to existing legacy functions to preserve business logic.
    """
    is_vat = withholding_type == "VAT"
    has_any = bool(voucher_number or withholding_date or file_url)
    has_all = bool(voucher_number and withholding_date and file_url)
    
    if has_any and not has_all:
        msg = _("Debe completar todos los campos del formulario para el comprobante de IVA (Número, Fecha y Archivo).") if is_vat else \
            _("Debe completar todos los campos del formulario para el comprobante de ISLR (Número, Fecha y Archivo).")
        frappe.throw(msg)
    
    if is_vat:
        has_existing = bool(invoice.vat_withholding_voucher_number or invoice.voucher_image)
        if has_all:
            if has_existing and not is_overwrite and not is_only_line:
                return {
                    "status": "ask_overwrite",
                    "message": _("La factura {0} ya tiene un comprobante de IVA registrado ({1}). ¿Desea reemplazarlo con la nueva información?").format(
                        invoice.name, invoice.vat_withholding_voucher_number or "Imagen cargada"
                    )
                }

            if is_overwrite or not has_existing:
                res = upload_voucher_data(
                    docname=invoice.name, 
                    voucher_number=voucher_number, 
                    withholding_date=withholding_date, 
                    file_url=file_url,
                    registration_date=registration_date
                )
                if res.get("status") == "error":
                    frappe.throw(_("Error procesando comprobante de IVA: {0}").format(res.get("msg")))
                
    else:  # ISLR
        has_existing = bool(invoice.islr_receipt_number or invoice.voucher_image_islr)
        if has_all:
            if has_existing and not is_overwrite and not is_only_line:
                return {
                    "status": "ask_overwrite",
                    "message": _("La factura {0} ya tiene un comprobante de ISLR registrado ({1}). ¿Desea reemplazarlo con la nueva información?").format(
                        invoice.name, invoice.islr_receipt_number or "Imagen cargada"
                    )
                }

            if is_overwrite or not has_existing:
                res = upload_islr_voucher_data(
                    docname=invoice.name, 
                    islr_date=withholding_date, 
                    islr_receipt_number=voucher_number, 
                    file_url=file_url,
                    registration_date=registration_date
                )
                if res.get("status") == "error":
                    frappe.throw(_("Error procesando comprobante de ISLR: {0}").format(res.get("msg")))
                
    return {"status": "proceed"}


def update_invoice_metadata(invoice: "SalesInvoice", data: dict) -> None:
    """Updates invoice metadata fields bypassing docstatus validation using db_set."""
    frappe.db.set_value("Sales Invoice", invoice.name, data, update_modified=False)
    for field, value in data.items():
        setattr(invoice, field, value)
    refresh_missing_withholding_voucher(invoice)


#: Campo donde vive el número del comprobante de cada tipo de retención.
#:
#: La clave es el `charge_type` de Sales Taxes and Charges, que es el único lugar
#: donde consta que la retención está contabilizada.
WITHHOLDING_VOUCHER_FIELD: dict = {
    "VAT Withholding": "vat_withholding_voucher_number",
    "ISLR": "islr_receipt_number",
}


def missing_withholding_voucher(invoice: "SalesInvoice") -> bool:
    """Hay una retención contabilizada cuyo número de comprobante no está registrado.

    Se evalúa **por tipo**: una factura con retención de IVA y de ISLR donde sólo falta
    el número del ISLR cuenta como faltante, aunque el de IVA esté cargado. Y una que
    sólo tiene retención de IVA no reclama el número de ISLR, que no le corresponde.

    Medido sobre la copia de producción (facturas de julio en adelante): de 392 con
    retención contabilizada, 358 tienen los dos tipos, 23 sólo ISLR y 11 sólo IVA. Ese
    8,7% de un solo tipo es lo que hace que la regla tenga que mirar el `charge_type` y
    no pueda asumir que siempre vienen en par.
    """
    for fila in invoice.get("taxes") or []:
        campo: str = WITHHOLDING_VOUCHER_FIELD.get(fila.charge_type or "")
        if not campo or not flt(fila.tax_amount):
            continue
        if not str(invoice.get(campo) or "").strip():
            return True
    return False


def refresh_missing_withholding_voucher(invoice: "SalesInvoice") -> None:
    """Persiste el aviso de comprobante faltante para que lo lea la vista de lista.

    La vista de lista sólo puede leer campos del padre --no ve la tabla de impuestos--
    así que la condición se calcula acá y se guarda. Antes la lista la aproximaba con
    `total_withholding != 0 && !nro_iva && !nro_islr`, y esa heurística fallaba de dos
    maneras medidas sobre la copia de producción: 66 facturas con la fila de retención
    tienen `total_withholding` en 0 --nadie lo recalcula en Sales Invoice-- y quedaban
    invisibles; y el `&&` exigía que faltaran los DOS números, así que 21 facturas a
    las que sólo les faltaba uno figuraban como completas.

    Se escribe con `update_modified=False`: es un dato derivado, no una edición del
    usuario, y no tiene por qué mover el `modified` de la factura ni su versión.
    """
    if not invoice.get("name"):
        return

    # Un documento cargado siempre trae `taxes`, aunque sea vacía. Que falte la clave
    # significa que no es un documento completo --un dict parcial, una fila de una
    # consulta-- y ahí la regla no daría False porque no haya retención, sino porque no
    # puede verla. Apagar el aviso en ese caso es peor que no tocarlo.
    if invoice.get("taxes") is None:
        return
    valor: int = 1 if missing_withholding_voucher(invoice) else 0
    if cint(invoice.get("missing_withholding_voucher")) == valor:
        return
    invoice.missing_withholding_voucher = valor
    frappe.db.set_value(
        "Sales Invoice", invoice.name,
        "missing_withholding_voucher", valor,
        update_modified=False,
    )


def set_missing_withholding_voucher(doc: "SalesInvoice", method: str = None) -> None:
    """Entrada del hook `validate`: deja el campo listo antes de que Frappe lo guarde.

    Acá no se escribe en la base --el propio save lo persiste-- para no hacer dos
    escrituras de lo mismo.
    """
    doc.missing_withholding_voucher = 1 if missing_withholding_voucher(doc) else 0


#: Nombre en español de cada tipo de retención, para lo que lee un humano.
#:
#: El tipo interno es el `charge_type` de Sales Taxes and Charges ("VAT"/"ISLR"), y en
#: la factura y en el asiento se venía escribiendo tal cual: "Retención de VAT". En
#: Venezuela ese impuesto se llama IVA en todos lados --el comprobante del cliente, el
#: Libro de Ventas, la declaración-- así que el documento contradecía a su propio
#: respaldo. ISLR ya coincide y queda igual.
WITHHOLDING_LABEL: dict = {"VAT": "IVA", "ISLR": "ISLR"}


def withholding_label(withholding_type: str) -> str:
    """Nombre en español del tipo de retención; devuelve el tipo si no lo conoce."""
    return WITHHOLDING_LABEL.get(withholding_type, withholding_type)


def create_sales_taxes_row(
    invoice: "SalesInvoice",
    charge_type: str,
    tax_account: str,
    withholding_type: str,
    amount: float,
    base_amount: float,
    rate: float
) -> "SalesTaxesandCharges":
    """Appends and inserts a new row in Sales Taxes and Charges."""
    idx = len(invoice.taxes) + 1
    tax_row = frappe.new_doc("Sales Taxes and Charges")
    tax_row.parent = invoice.name
    tax_row.parenttype = "Sales Invoice"
    tax_row.parentfield = "taxes"
    tax_row.idx = idx
    tax_row.charge_type = charge_type
    tax_row.add_deduct_tax = "Deduct"
    tax_row.category = "Total"
    tax_row.account_head = tax_account
    tax_row.description = f"Retención de {withholding_label(withholding_type)} (Ajuste)"
    tax_row.rate = flt(rate)
    tax_row.tax_amount = amount
    tax_row.base_tax_amount = base_amount
    tax_row.tax_amount_after_discount_amount = amount
    tax_row.base_tax_amount_after_discount_amount = base_amount
    tax_row.is_tax_withholding_account = 1
    tax_row.dont_recompute_tax = 1
    tax_row.cost_center = invoice.cost_center
    tax_row.db_insert()
    return tax_row


def create_withholding_journal_entry(
    invoice: "SalesInvoice",
    withholding_type: str,
    tax_account: str,
    amount: float,
    base_amount: float,
    conversion_rate: float,
    withholding_date: str,
    company_currency: str,
    invoice_currency: str
) -> "JournalEntry":
    """Builds and submits the multi-currency Journal Entry for the withholding, splitting overpayments if necessary."""
    tax_account_currency = frappe.db.get_value("Account", tax_account, "account_currency") or company_currency
    receivable_account_currency = frappe.db.get_value("Account", invoice.debit_to, "account_currency") or company_currency

    posting_date = frappe.utils.today()

    outstanding_bs = flt(invoice.outstanding_amount)
    if receivable_account_currency != company_currency:
        outstanding_bs = flt(invoice.outstanding_amount * conversion_rate)
    
    total_credit_bs = base_amount

    je = frappe.new_doc("Journal Entry")
    je.company = invoice.company
    je.posting_date = posting_date
    je.user_remark = (
        f"Retención de {withholding_label(withholding_type)} registrada "
        f"para la factura {invoice.name}."
    )
    
    je.multi_currency = 1 if (
        invoice_currency != company_currency or 
        tax_account_currency != company_currency or 
        receivable_account_currency != company_currency
    ) else 0

    tax_je_row = {
        "account": tax_account,
        "cost_center": invoice.cost_center,
    }
    if tax_account_currency != company_currency:
        tax_je_row.update({
            "account_currency": tax_account_currency,
            "exchange_rate": conversion_rate if tax_account_currency == invoice_currency else 1.0,
            "debit_in_account_currency": amount if tax_account_currency == invoice_currency else base_amount,
            "debit": base_amount
        })
    else:
        tax_je_row.update({
            "debit_in_account_currency": base_amount,
            "debit": base_amount,
            "exchange_rate": 1.0
        })
    je.append("accounts", tax_je_row)

    is_invoice_fully_paid = outstanding_bs <= 0
    if is_invoice_fully_paid:
        credit_invoice_bs = 0.0
        credit_advance_bs = total_credit_bs
    else:
        has_overpayment = total_credit_bs > outstanding_bs
        if has_overpayment:
            credit_invoice_bs = outstanding_bs
            credit_advance_bs = flt(total_credit_bs - outstanding_bs, 2)
        else:
            credit_invoice_bs = total_credit_bs
            credit_advance_bs = 0.0

    rec_exchange_rate = conversion_rate if (receivable_account_currency != company_currency and receivable_account_currency == invoice_currency) else 1.0

    if credit_invoice_bs > 0:
        rec_je_row_invoice = {
            "account": invoice.debit_to,
            "party_type": "Customer",
            "party": invoice.customer,
            "reference_type": "Sales Invoice",
            "reference_name": invoice.name,
            "cost_center": invoice.cost_center,
        }
        if receivable_account_currency != company_currency:
            proportional_amount_usd = flt(credit_invoice_bs / rec_exchange_rate, 2) if rec_exchange_rate else 0.0
            rec_je_row_invoice.update({
                "account_currency": receivable_account_currency,
                "exchange_rate": rec_exchange_rate,
                "credit_in_account_currency": proportional_amount_usd,
                "credit": credit_invoice_bs
            })
        else:
            rec_je_row_invoice.update({
                "credit_in_account_currency": credit_invoice_bs,
                "credit": credit_invoice_bs,
                "exchange_rate": 1.0
            })
        je.append("accounts", rec_je_row_invoice)

    if credit_advance_bs > 0:
        rec_je_row_advance = {
            "account": invoice.debit_to,
            "party_type": "Customer",
            "party": invoice.customer,
            "cost_center": invoice.cost_center,
            "is_advance": "Yes"
        }
        if receivable_account_currency != company_currency:
            overpayment_amount_usd = flt(credit_advance_bs / rec_exchange_rate, 2) if rec_exchange_rate else 0.0
            rec_je_row_advance.update({
                "account_currency": receivable_account_currency,
                "exchange_rate": rec_exchange_rate,
                "credit_in_account_currency": overpayment_amount_usd,
                "credit": credit_advance_bs
            })
        else:
            rec_je_row_advance.update({
                "credit_in_account_currency": credit_advance_bs,
                "credit": credit_advance_bs,
                "exchange_rate": 1.0
            })
        je.append("accounts", rec_je_row_advance)

    try:
        je.insert(ignore_permissions=True)
        je.submit()
    except ClosedAccountingPeriod:
        frappe.throw(
            _("No se pudo publicar el asiento contable de la retención: El período contable para la fecha {0} se encuentra cerrado. Comuníquese con el departamento de administración/contabilidad.")
            .format(je.posting_date)
        )
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error Contabilizando Retención")
        frappe.throw(_("Error al intentar contabilizar la retención: {0}").format(str(e)))    

    return je


def calculate_withholding_base_amount(invoice: "SalesInvoice", withholding_type: str) -> float:
    """Calculates and returns the withholding amount in local currency (Bs) 
    strictly using the invoice values stored in the database.
    """
    base_amount = 0.0

    if withholding_type == "VAT":
        tax_withholding_category = frappe.db.get_value("Customer", invoice.customer, "tax_withholding_category")
        vat_rate = get_vat_category_rate(tax_withholding_category, invoice.company)

        vat_base_bs = sum(flt(t.base_tax_amount) for t in invoice.taxes if t.charge_type == "VAT")
        base_amount = flt(vat_base_bs * (vat_rate / 100.0), 2)

    elif withholding_type == "ISLR":
        customer_data = frappe.db.get_value(
            "Customer", 
            invoice.customer, 
            ["type_of_person", "tabulator_islr"], 
            as_dict=True
        )
        
        if not customer_data or not customer_data.tabulator_islr:
            frappe.throw(_("El cliente {0} no tiene configurado un Tabulador de ISLR.").format(invoice.customer))
        
        tab_doc = frappe.get_doc("Tabulator ISLR", customer_data.tabulator_islr)
        client_person_type = customer_data.type_of_person
        
        target_row = None
        if tab_doc.aliquot:
            if client_person_type:
                target_row = next((row for row in tab_doc.aliquot if row.types_of_person == client_person_type), None)
            if not target_row:
                target_row = tab_doc.aliquot[0]
        
        if not target_row:
            frappe.throw(_("No se encontró una alícuota válida en el Tabulador de ISLR para el cliente."))

        subtrahend = flt(target_row.subtracting)
        percentage_base = flt(target_row.percentage_base) or 100.0
        
        net_total_bs = flt(invoice.base_net_total)
        calculated_base_bs = flt(net_total_bs * (percentage_base / 100.0))

        islr_rate = flt(target_row.aliquot)
        
        base_amount = flt((calculated_base_bs * (islr_rate / 100.0)) - subtrahend, 2)
        if base_amount < 0:
            base_amount = 0.0

    if base_amount <= 0:
        frappe.throw(_("El monto de la retención recalculado en el servidor ({0} Bs) debe ser mayor a cero.").format(base_amount))

    return base_amount


def validate_withholding_tax_account(invoice: "SalesInvoice", withholding_type: str, tax_account: str) -> None:
    """Validates that the selected tax account exists, belongs to the correct company,
    is not a group account, and matches the configured company-wide withholding account.
    """
    if not tax_account:
        frappe.throw(_("Debe especificar una cuenta de retención contable."))

    account_data = frappe.db.get_value(
        "Account", 
        tax_account, 
        ["company", "is_group"], 
        as_dict=True
    )

    if not account_data:
        frappe.throw(_("La cuenta contable {0} no existe.").format(tax_account))

    if account_data.company != invoice.company:
        frappe.throw(
            _("La cuenta contable {0} pertenece a la compañía {1}, pero la factura es de la compañía {2}.")
            .format(tax_account, account_data.company, invoice.company)
        )

    if account_data.is_group:
        frappe.throw(_("La cuenta contable {0} es de tipo Grupo y no puede recibir asientos directos.").format(tax_account))

    company_fields = ["sales_vat_withholding_account", "sales_islr_account"]
    company_config = frappe.db.get_value("Company", invoice.company, company_fields, as_dict=True)

    if not company_config:
        frappe.throw(_("No se encontró la configuración de la compañía {0}.").format(invoice.company))

    if withholding_type == "VAT":
        official_account = company_config.sales_vat_withholding_account
        error_msg = _("La cuenta contable {0} no coincide con la cuenta de Retención de IVA oficial de la compañía ({1}).")
    else:
        official_account = company_config.sales_islr_account
        error_msg = _("La cuenta contable {0} no coincide con la cuenta de Retención de ISLR oficial de la compañía ({1}).")

    if official_account and tax_account != official_account:
        frappe.throw(error_msg.format(tax_account, official_account))


def _require_withholding_permissions() -> None:
    """Verifies that the current user has permission to submit/update Sales Invoices
    or belongs to core accounting roles. Avoids hardcoded ISP roles.
    """
    user_roles = frappe.get_roles()
    allowed_roles = {"Accounts Manager", "Accounts User", "System Manager"}
    if allowed_roles.intersection(user_roles):
        return

    frappe.throw(
        _("No tiene los permisos suficientes para aplicar retenciones sobre esta factura."),
        frappe.PermissionError
    )

def sync_isp_payment_amounts_if_installed(invoice: "SalesInvoice") -> None:
    """Detects if 'domina_isp' is installed and triggers its payment entry 
    amount synchronization to keep accounts aligned.
    """
    if "domina_isp" not in frappe.get_installed_apps():
        return

    try:
        from domina_isp.domina_isp.doctype.isp_payment_entry.isp_payment_entry import sync_isp_payment_entry_amounts
        sync_isp_payment_entry_amounts(invoice)
    except (ImportError, AttributeError):
        frappe.log_error(
            title="Error sync ISP Payment Entry",
            message=f"Error syncing ISP Payment Entry para la factura {invoice.name}:\n\n{frappe.get_traceback()}"
        )

def get_vat_category_rate(category_name: str, company: str) -> float:
    """Replica la lógica de la función JS para resolver la tasa de retención 
    de IVA desde el backend de forma segura.
    """
    if not category_name:
        frappe.throw(_("El cliente no tiene asignada una categoría de retención de impuestos."))

    category_doc = frappe.get_doc("Tax Withholding Category", category_name)
    rate = None

    if category_doc.get("accounts"):
        has_company_account = any(a.company == company for a in category_doc.accounts)

        if has_company_account and category_doc.get("rates") and len(category_doc.rates) > 0:
            rate = flt(category_doc.rates[0].tax_withholding_rate)

    if rate is None or rate == 0:
        rate = flt(category_doc.get("default_rate")) or flt(category_doc.get("rate")) or None

    if rate is None or rate == 0:
        frappe.throw(_("No se encontró ninguna tasa (Rate) válida o configurada para la categoría de retención {0}.").format(category_name))

    return rate


@frappe.whitelist()
def get_company_government_withholding_account(company: str) -> str:
    """Cuenta contable de retenciones gubernamentales configurada en la empresa."""
    if not company:
        frappe.throw(_("Debe especificar una empresa."))

    gov_account = frappe.db.get_value("Company", company, "government_withholding_account")
    if not gov_account:
        frappe.throw(
            _(
                "La empresa {0} no tiene configurada la Cuenta de Retenciones Gubernamentales en su configuración."
            ).format(company)
        )
    return gov_account


def _outstanding_in_company_currency(invoice) -> float:
    """Saldo pendiente de la factura expresado en la moneda de la empresa (Bs).

    `Sales Invoice.outstanding_amount` está en `party_account_currency`, que no
    siempre es la de la empresa. Se convierte con la tasa de la propia factura
    cuando la cuenta por cobrar va en la moneda de la factura.

    NO se deduce la moneda comparando importes (`outstanding <= grand_total`):
    esos dos campos pueden estar en monedas distintas, así que la comparación no
    dice nada, y equivocarse hacia arriba deja pasar una retención por encima de
    lo que la factura debe. Si la combinación no se puede resolver, se corta.
    """
    company_currency = frappe.get_cached_value("Company", invoice.company, "default_currency")
    party_currency = invoice.get("party_account_currency") or company_currency
    outstanding = flt(invoice.outstanding_amount)

    if party_currency == company_currency:
        return flt(outstanding, 2)

    if party_currency == invoice.currency:
        rate = flt(invoice.conversion_rate)
        if rate <= 0:
            frappe.throw(
                _("La factura {0} no tiene una tasa de cambio válida para convertir el saldo pendiente.").format(invoice.name)
            )
        return flt(outstanding * rate, 2)

    frappe.throw(
        _(
            "No se puede determinar el saldo pendiente en {0}: la cuenta por cobrar está en {1} "
            "y la factura en {2}. Revise la configuración de la cuenta del cliente."
        ).format(company_currency, party_currency, invoice.currency)
    )


@frappe.whitelist()
def get_government_withholding_context(docname: str) -> dict:
    """Datos que necesita el modal: saldo pendiente en la moneda de la empresa.

    Vive en el servidor a propósito. `outstanding_amount` está en la moneda de la
    cuenta por cobrar, y repetir esa conversión en el cliente es la forma segura
    de que el modal muestre un número y el asiento postee otro.
    """
    _require_withholding_permissions()

    invoice = frappe.get_doc("Sales Invoice", docname)
    return {
        "outstanding": _outstanding_in_company_currency(invoice),
        "currency": frappe.get_cached_value("Company", invoice.company, "default_currency"),
    }


@frappe.whitelist()
def create_government_withholding_journal_entry(
    docname: str,
    amount: float,
    description: str = None,
    voucher_number: str = None,
    voucher_date: str = None,
    voucher_file: str = None,
) -> dict:
    """Crea y somete un Asiento Contable de Retención Gubernamental para una Factura de Venta.

    El monto se recibe SIEMPRE en la moneda de la empresa (Bs).

    Asiento: Debe cuenta de Retenciones Gubernamentales / Haber Cuenta por Cobrar
    del cliente, referenciada a la factura. Misma forma contable que la vía de
    Payment Entry que reemplaza (gasto contra CxC), según la directiva del 21-jul.

    Se admiten VARIAS retenciones sobre la misma factura y el comprobante es
    opcional. Lo que impide pasarse es el tope contra el saldo pendiente: como
    cada asiento referencia la factura, ERPNext baja su `outstanding_amount`, así
    que la siguiente retención sólo puede tomar lo que quede. El `for_update`
    serializa dos clics simultáneos, que si no leerían el mismo saldo.
    """
    _require_withholding_permissions()

    if not docname:
        frappe.throw(_("Debe especificar el número o ID de la Factura de Venta."))

    amount = flt(amount, 2)
    if amount <= 0:
        frappe.throw(_("El monto de la retención debe ser mayor a cero."))

    # Bloquea la fila de la factura hasta el fin de la transacción: sin esto, dos
    # operadores simultáneos leen el mismo pendiente y ambos pasan el tope.
    frappe.db.get_value("Sales Invoice", docname, "outstanding_amount", for_update=True)

    invoice = frappe.get_doc("Sales Invoice", docname)

    if invoice.docstatus != 1:
        frappe.throw(
            _(
                "La Factura de Venta {0} debe estar en estado Sometida (Validada) para aplicar una Retención Gubernamental."
            ).format(docname)
        )

    gov_account = get_company_government_withholding_account(invoice.company)

    company_currency = frappe.get_cached_value("Company", invoice.company, "default_currency")

    # El asiento se arma en la moneda de la empresa. Una cuenta de retenciones en
    # otra moneda obligaría a una tasa que no tenemos por qué inventar acá.
    gov_account_currency = get_account_currency(gov_account) or company_currency
    if gov_account_currency != company_currency:
        frappe.throw(
            _(
                "La Cuenta de Retenciones Gubernamentales ({0}) está en {1} y debe estar en la moneda de la empresa ({2})."
            ).format(gov_account, gov_account_currency, company_currency)
        )

    base_outstanding = _outstanding_in_company_currency(invoice)

    if amount > base_outstanding:
        frappe.throw(
            _(
                "El monto de la retención ({0}) no puede ser mayor que el saldo pendiente de la factura ({1})."
            ).format(
                f"{amount:,.2f} {company_currency}",
                f"{base_outstanding:,.2f} {company_currency}",
            )
        )

    receivable_currency = get_account_currency(invoice.debit_to) or company_currency
    cost_center = invoice.cost_center or frappe.get_cached_value("Company", invoice.company, "cost_center")

    remark_parts = []
    if voucher_number and str(voucher_number).strip():
        remark_parts.append(f"Comprobante N°: {str(voucher_number).strip()}")
    if voucher_date and str(voucher_date).strip():
        remark_parts.append(f"Fecha: {str(voucher_date).strip()}")
    if description and description.strip():
        remark_parts.append(description.strip())
    else:
        remark_parts.append(
            _("Retención Gubernamental aplicada a la Factura de Venta {0}").format(invoice.name)
        )

    je = frappe.new_doc("Journal Entry")
    je.company = invoice.company
    je.voucher_type = "Journal Entry"
    je.posting_date = nowdate()
    je.user_remark = " - ".join(remark_parts)
    je.multi_currency = 1 if receivable_currency != company_currency else 0

    je.append("accounts", {
        "account": gov_account,
        "cost_center": cost_center,
        "account_currency": company_currency,
        "exchange_rate": 1.0,
        "debit_in_account_currency": amount,
        "debit": amount,
    })

    rec_row = {
        "account": invoice.debit_to,
        "party_type": "Customer",
        "party": invoice.customer,
        "reference_type": "Sales Invoice",
        "reference_name": invoice.name,
        "cost_center": cost_center,
        "credit": amount,
    }
    if receivable_currency != company_currency:
        rate = flt(invoice.conversion_rate)
        if rate <= 0:
            frappe.throw(
                _("La factura {0} no tiene una tasa de cambio válida para armar el asiento.").format(invoice.name)
            )
        rec_row.update({
            "account_currency": receivable_currency,
            "exchange_rate": rate,
            "credit_in_account_currency": flt(amount / rate, 2),
        })
    else:
        rec_row.update({
            "account_currency": company_currency,
            "exchange_rate": 1.0,
            "credit_in_account_currency": amount,
        })
    je.append("accounts", rec_row)

    je.insert(ignore_permissions=True)
    je.submit()

    if voucher_number and str(voucher_number).strip() and invoice.meta.has_field("municipal_receipt_number"):
        invoice.db_set("municipal_receipt_number", str(voucher_number).strip(), update_modified=False)

    if voucher_date and str(voucher_date).strip() and invoice.meta.has_field("municipal_date"):
        invoice.db_set("municipal_date", str(voucher_date).strip(), update_modified=False)

    if voucher_file and str(voucher_file).strip():
        file_url = str(voucher_file).strip()
        if invoice.meta.has_field("voucher_image_municipal"):
            invoice.db_set("voucher_image_municipal", file_url, update_modified=False)
        try:
            frappe.get_doc({
                "doctype": "File",
                "file_url": file_url,
                "attached_to_doctype": "Journal Entry",
                "attached_to_name": je.name,
                "is_private": 0,
            }).insert(ignore_permissions=True)

            frappe.get_doc({
                "doctype": "File",
                "file_url": file_url,
                "attached_to_doctype": "Sales Invoice",
                "attached_to_name": invoice.name,
                "is_private": 0,
            }).insert(ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Error adjuntando comprobante gubernamental: {e}")

    return {
        "status": "success",
        "journal_entry": je.name,
        "message": _("Asiento Contable de Retención Gubernamental {0} creado y sometido exitosamente.").format(
            get_link_to_form("Journal Entry", je.name)
        ),
    }
