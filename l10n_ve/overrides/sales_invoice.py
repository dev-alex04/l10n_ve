import frappe
from frappe import _
from frappe.utils import flt, cint, getdate

from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice, make_regional_gl_entries

from l10n_ve.overrides.company import CustomCompany
from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.utils.utils import validate_return_in_same_month, get_link_to_form, validate_portal_upload, delete_old_attachment, is_period_open


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
def upload_voucher_data(docname, voucher_number, withholding_date, file_url=None) -> dict:
    try:
        if not withholding_date or not file_url:
            frappe.throw(_("Faltan datos obligatorios."))

        if file_url:
            validate_portal_upload(file_url, 5)

        invoice_doc = frappe.get_doc("Sales Invoice", docname)

        user_roles = frappe.get_roles()

        if frappe.session.user != "Administrator" and "ISP Finance" not in user_roles:
            if not is_period_open(withholding_date, "IVA"):
                frappe.throw(_("La fecha del comprobante cae en un período de declaración cerrado."))

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

        frappe.db.set_value("Sales Invoice", docname, {
            'vat_withholding_voucher_number': voucher_number,
            'withholding_date': withholding_date,
            'voucher_image': file_url
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
def upload_islr_voucher_data(docname, islr_date, islr_receipt_number=None, file_url=None) -> dict:
    try:
        if not islr_date or not file_url:
            frappe.throw(_("La fecha y el archivo del comprobante de ISLR son obligatorios."))

        if file_url:
            validate_portal_upload(file_url, 5)

        invoice_doc = frappe.get_doc("Sales Invoice", docname)

        user_roles = frappe.get_roles()
        if frappe.session.user != "Administrator" and "ISP Finance" not in user_roles:
            if not is_period_open(islr_date, "ISLR"):
                frappe.throw(_("La fecha del comprobante cae en un período de declaración cerrado."))

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

        frappe.db.set_value("Sales Invoice", docname, {
            'islr_receipt_number': islr_receipt_number,
            'islr_date': islr_date,
            'voucher_image_islr': file_url
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
