# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, cint
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals
from l10n_ve.utils.utils import (
    validate_return_in_same_month,
)


class VESalesDebitNote(TaxesMixin, SalesInvoice):
    """
    Nota de Débito venezolana para integración con TFHKA (HKA).
    Hereda de SalesInvoice para reutilizar GL entries, cálculo de impuestos
    y validaciones de venta.

    Diferencia clave con VE Sales Credit Note:
      - La NC niega los GL entries (revierte ingresos y reduce AR).
      - La ND NO niega los GL entries: los GL entries normales de SalesInvoice
        ya producen el efecto correcto → débito en AR (aumenta saldo del
        cliente) y crédito en Ingresos (ingreso adicional).

    Los montos se almacenan siempre en positivo.
    """

    # ------------------------------------------------------------------ #
    # Indicador del portal                                                 #
    # ------------------------------------------------------------------ #

    def set_indicator(self) -> None:
        """Sobreescribe SalesInvoice.set_indicator() para evitar 'Overdue'."""
        if flt(self.outstanding_amount) == 0:
            self.indicator_title = _("Paid")
            self.indicator_color = "green"
        else:
            self.indicator_title = _("Unpaid")
            self.indicator_color = "orange"

    # ------------------------------------------------------------------ #
    # Ciclo de vida del documento                                          #
    # ------------------------------------------------------------------ #

    def before_insert(self) -> None:
        self.is_debit_note = 1
        self.is_return = 0
        self.naming_series = "ND-.YYYY.-"
        self._init_si_defaults()
        self._inherit_branch_from_si()

    def validate(self) -> None:
        self.is_debit_note = 1
        self.is_return = 0
        self._init_si_defaults()
        self._inherit_branch_from_si()
        self._enforce_positive_amounts()
        self._validate_unique_note_per_invoice()
        # Intra-mes obligatorio (regla fiscal; para naturales además ancla
        # la coincidencia de tasa del 1° del mes con la factura afectada).
        validate_return_in_same_month(self)
        self.set_posting_time = 1
        self._run_super_validate_safely()
        self._set_base_total_with_vat()

    def on_submit(self) -> None:
        """
        SalesInvoice.on_submit() accede a atributos que no existen en el DocType
        de la ND (update_billed_amount_in_sales_order, auto_repeat, etc.).
        Se inicializan aquí antes de delegar al super para evitar AttributeError.
        """
        self.is_debit_note = 1
        self.is_return = 0
        self._init_si_defaults()
        super().on_submit()
        self._update_outstanding_amount()
        self._update_parent_invoice_status()
        self._set_pending_hka_status()

    def _set_pending_hka_status(self) -> None:
        """Marca la ND como Pendiente de emisión HKA si su sucursal tiene serie digital activa."""
        from l10n_ve.digital_invoice.tfhka_integration import has_active_digital_series

        if has_active_digital_series(self.company, self.get("branch")):
            self.db_set("hka_status", "Pendiente", update_modified=False)
            self.hka_status = "Pendiente"

    def before_cancel(self) -> None:
        """
        SalesInvoice.before_cancel() accede a self.timesheets (entre otros).
        Se inicializan los atributos faltantes antes de delegar al super.
        """
        self._block_cancel_if_sent_to_hka()
        self.is_debit_note = 1
        self.is_return = 0
        self._init_si_defaults()
        super().before_cancel()



    def _block_cancel_if_sent_to_hka(self) -> None:
        """
        Bloquea la cancelación si la ND ya fue enviada a la imprenta digital
        TFHKA (detectado por la presencia de bill_no o bill_control).

        La excepción es cuando `_hka_void_confirmed = True` está establecido
        en la instancia: indica que `void_debit_note()` ya confirmó la anulación
        con HKA y está ejecutando el cancel() de Frappe de forma controlada.
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
                    "La Nota de Débito <b>{0}</b> ya fue enviada a la imprenta "
                    "digital TFHKA (N° Documento: <b>{1}</b>, N° Control: <b>{2}</b>). "
                    "Use el botón 'Anular ND' para anularla correctamente."
                ).format(
                    self.name,
                    self.bill_no or "—",
                    self.bill_control or "—",
                ),
                title=_("Cancelación Bloqueada — Facturación Digital"),
            )

    def on_cancel(self) -> None:
        """
        SalesInvoice.on_cancel() accede a múltiples atributos que no forman
        parte del schema de la ND. Se inicializan antes de delegar al super.

        ERPNext hardcodea db_set('status', 'Cancelled') en su on_cancel().
        Si la ND está marcada como is_void, corregimos el status a 'Void' después.
        """
        self.is_debit_note = 1
        self.is_return = 0
        self._init_si_defaults()
        super().on_cancel()
        self._update_outstanding_amount()
        self._update_parent_invoice_status()

        if cint(self.is_void):
            self.db_set("status", "Void")
            self.status = "Void"

    def update_against_document_in_jv(self) -> None:
        """
        accounts_controller.update_against_document_in_jv() usa
        ``self.doctype == "Sales Invoice"`` para decidir party_type.
        La ND no cumple esa condición y cae en la rama de Purchase Invoice
        (self.supplier / self.credit_to). Se sobreescribe con la lógica
        correcta de Customer para permitir conciliación de anticipos.
        """
        from frappe.utils import flt

        from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
            get_dimensions,
        )
        from erpnext.accounts.utils import reconcile_against_document

        party_type: str = "Customer"
        party: str = self.customer
        party_account: str = self.debit_to
        dr_or_cr: str = "credit_in_account_currency"

        lst: list = []
        for d in self.get("advances") or []:
            if flt(d.allocated_amount) > 0:
                args = frappe._dict(
                    {
                        "voucher_type": d.reference_type,
                        "voucher_no": d.reference_name,
                        "voucher_detail_no": d.reference_row,
                        "against_voucher_type": self.doctype,
                        "against_voucher": self.name,
                        "account": party_account,
                        "party_type": party_type,
                        "party": party,
                        "is_advance": "Yes",
                        "dr_or_cr": dr_or_cr,
                        "unadjusted_amount": flt(d.advance_amount),
                        "allocated_amount": flt(d.allocated_amount),
                        "precision": d.precision("advance_amount"),
                        "exchange_rate": (
                            self.conversion_rate
                            if self.party_account_currency != self.company_currency
                            else 1
                        ),
                        "grand_total": (
                            self.base_grand_total
                            if self.party_account_currency == self.company_currency
                            else self.grand_total
                        ),
                        "outstanding_amount": self.outstanding_amount,
                        "difference_account": frappe.get_cached_value(
                            "Company", self.company, "exchange_gain_loss_account"
                        ),
                        "exchange_gain_loss": flt(d.get("exchange_gain_loss")),
                        "difference_posting_date": d.get("difference_posting_date"),
                    }
                )
                lst.append(args)

        if lst:
            active_dimensions = get_dimensions()[0]
            for x in lst:
                for dim in active_dimensions:
                    if self.get(dim.fieldname):
                        x.update({dim.fieldname: self.get(dim.fieldname)})
            reconcile_against_document(lst, active_dimensions=active_dimensions)

    def get_advance_entries(self, include_unallocated: bool = True) -> list:
        """
        accounts_controller.get_advance_entries() usa
        ``self.doctype in ["Sales Invoice", "POS Invoice"]`` para decidir
        party_type. La ND no cumple → cae en rama Supplier.
        Se sobreescribe con la lógica correcta de Customer.
        """
        from erpnext.accounts.party import get_party_account
        from erpnext.controllers.accounts_controller import (
            get_advance_journal_entries,
            get_advance_payment_entries_for_regional,
        )

        party_type: str = "Customer"
        party: str = self.customer
        amount_field: str = "credit_in_account_currency"
        order_field: str = "sales_order"
        order_doctype: str = "Sales Order"

        party_account: list = [self.debit_to]

        party_accounts = get_party_account(
            party_type, party=party, company=self.company, include_advance=True
        )
        default_advance_account = None
        if party_accounts:
            party_account.append(party_accounts[0])
            default_advance_account = (
                party_accounts[1] if len(party_accounts) == 2 else None
            )

        order_list = list(
            set(d.get(order_field) for d in self.get("items") if d.get(order_field))
        )

        journal_entries = get_advance_journal_entries(
            party_type, party, party_account, amount_field,
            order_doctype, order_list, include_unallocated,
        )

        payment_entries = get_advance_payment_entries_for_regional(
            party_type, party, party_account, order_doctype,
            order_list, default_advance_account, include_unallocated,
        )

        return journal_entries + payment_entries

    def validate_against_voucher_outstanding(self) -> None:
        """
        La validación nativa usa self.doctype para buscar el outstanding del
        return_against, lo que falla porque la ND es un doctype distinto a Sales Invoice.
        Se suprime intencionalmente.
        """
        return

    def make_discount_gl_entries(self, gl_entries: list) -> None:
        """
        ERPNext asigna enable_discount_accounting solo para "Sales Invoice" y
        "Purchase Invoice". VE Sales Debit Note no entra en ninguna rama →
        UnboundLocalError. Se delega temporalmente a "Sales Invoice".
        """
        self.doctype = "Sales Invoice"
        try:
            super().make_discount_gl_entries(gl_entries)
        finally:
            self.doctype = "VE Sales Debit Note"

    def _update_outstanding_amount(self) -> None:
        """
        ERPNext core (gl_entry.py:390) solo actualiza outstanding_amount para
        'Sales Invoice', 'Purchase Invoice' y 'Fees'.
        La ND no entra en esa lista, por lo que el outstanding queda en 0.
        Se calcula manualmente desde los GL Entries de la cuenta receivable.
        """
        bal = frappe.db.sql(
            """
            SELECT SUM(debit_in_account_currency) - SUM(credit_in_account_currency)
            FROM `tabGL Entry`
            WHERE against_voucher_type = %s
              AND against_voucher = %s
              AND account = %s
              AND is_cancelled = 0
            """,
            (self.doctype, self.name, self.debit_to),
        )
        outstanding: float = flt(bal[0][0]) if bal and bal[0][0] else 0.0
        self.outstanding_amount = outstanding
        self.db_set("outstanding_amount", outstanding)
        self.set_status(update=True)

    def _inherit_branch_from_si(self) -> None:
        """
        Hereda branch, debit_to y tasa de cambio de la Factura Original
        (return_against).

        - branch / debit_to: se heredan de la SI si la nota no los trae.
        - conversion_rate / plc_conversion_rate: hereda la tasa con la que
          se certificó la factura afectada (decision de gestión
          23-jul-2026). A diferencia de la NC, la ND no necesita asiento
          de ajuste: su ledger se referencia a sí misma (against_voucher =
          self.name), no a la factura afectada.
        - posting_date: la nota tiene su propia fecha de expedición
          (SENIAT); no se hereda de la factura afectada.
        - due_date: si la nota no trae uno, se alinea con su posting_date.
        """
        if not self.get("return_against"):
            return

        si_values: dict = frappe.get_cached_value(
            "Sales Invoice",
            self.return_against,
            ["branch", "debit_to", "conversion_rate", "plc_conversion_rate", "currency"],
            as_dict=True,
        ) or {}

        if si_values.get("branch") and not self.get("branch"):
            self.branch = si_values["branch"]

        if si_values.get("debit_to") and not self.get("debit_to"):
            self.debit_to = si_values["debit_to"]

        # Tasa de la factura afectada, solo en docs nuevos para respetar
        # ediciones manuales posteriores del usuario.
        if self.is_new():
            si_rate: float = flt(si_values.get("conversion_rate"))
            si_plc_rate: float = flt(si_values.get("plc_conversion_rate"))
            if si_rate:
                self.conversion_rate = si_rate
            if si_plc_rate:
                self.plc_conversion_rate = si_plc_rate
            elif si_rate:
                self.plc_conversion_rate = si_rate

        if self.is_new() and self.get("posting_date") and not self.get("due_date"):
            self.due_date = self.posting_date

    def _init_si_defaults(self) -> None:
        """
        Inicializa atributos de SalesInvoice que no existen en VE Sales Debit Note
        para evitar AttributeError en los controladores heredados de ERPNext.
        """
        scalar_defaults: dict = {
            "is_pos": 0,
            "is_consolidated": 0,
            "update_stock": 0,
            "is_internal_customer": 0,
            "loyalty_program": None,
            "loyalty_points": 0,
            "loyalty_amount": 0,
            "loyalty_redemption_account": None,
            "loyalty_redemption_cost_center": None,
            "redeem_loyalty_points": 0,
            "update_billed_amount_in_sales_order": 0,
            "update_billed_amount_in_delivery_note": 0,
            "update_outstanding_for_self": 0,
            "auto_repeat": None,
            "inter_company_invoice_reference": None,
            "campaign": None,
            "write_off_account": None,
            "write_off_cost_center": None,
            "write_off_amount": 0,
            "base_write_off_amount": 0,
            "write_off_outstanding_amount_automatically": 0,
            "paid_amount": 0,
            "base_paid_amount": 0,
            "change_amount": 0,
            "base_change_amount": 0,
            "account_for_change_amount": None,
            "allocate_advances_automatically": 0,
            "only_include_allocated_payments": 0,
            "ignore_default_payment_terms_template": 0,
            "payment_terms_template": None,
            "pos_profile": None,
            "cash_bank_account": None,
            "subscription": None,
            "total_billing_hours": 0,
            "total_billing_amount": 0,
        }
        for attr, val in scalar_defaults.items():
            if not hasattr(self, attr) or self.get(attr) is None:
                setattr(self, attr, val)

        self.is_pos = 0

        child_table_defaults: list[str] = [
            "timesheets",
            "pricing_rules",
            "packed_items",
            "advances",
            "payment_schedule",
            "payments",
            "subscriptions",
        ]
        for table in child_table_defaults:
            if not hasattr(self, table):
                setattr(self, table, [])

    def _run_super_validate_safely(self) -> None:
        """
        Parcha validate_return para que acepte VE Sales Debit Note
        sin exigir is_return=1 (ya que la ND usa is_debit_note=1).
        """
        import erpnext.controllers.accounts_controller as _acc_module

        _original_validate_return = _acc_module.validate_return

        def _validate_return_nd(doc):
            if doc.doctype != "VE Sales Debit Note":
                _original_validate_return(doc)
                return

            if not doc.return_against:
                frappe.throw(frappe._("Factura Afectada es obligatoria para la Nota de Débito"))

            if not frappe.db.exists("Sales Invoice", doc.return_against):
                frappe.throw(
                    frappe._("Factura Afectada no válida: {0}").format(doc.return_against)
                )

            si = frappe.get_cached_doc("Sales Invoice", doc.return_against)
            if si.company != doc.company:
                frappe.throw(
                    frappe._("La empresa de la ND debe coincidir con la factura original: {0}")
                    .format(si.company)
                )
            if si.customer != doc.customer:
                frappe.throw(
                    frappe._("El cliente de la ND debe coincidir con la factura original: {0}")
                    .format(si.customer)
                )

        _acc_module.validate_return = _validate_return_nd
        try:
            super().validate()
        finally:
            _acc_module.validate_return = _original_validate_return

    def calculate_taxes_and_totals(self) -> None:
        """Usa el calculador venezolano (TaxesAndTotals) para IVA, Retenciones e ISLR."""
        taxes_and_totals = TaxesAndTotals(self)
        taxes_and_totals.calculate_total_exempt()
        self.calculate_total_withholding()

    def set_taxes_and_charges(self) -> None:
        """
        Garantiza que el IVA base se cargue desde el template y luego agrega
        las retenciones venezolanas (IVA Retención e ISLR).
        """
        impuestos_base = [
            tax for tax in self.taxes or []
            if not tax.get("is_tax_withholding_account")
        ]

        if not impuestos_base and self.get("taxes_and_charges"):
            self.set("taxes", [])
            self.append_taxes_from_master("Sales Taxes and Charges Template")
        else:
            self.set("taxes", impuestos_base)

        self.set_tax_withholding_ve()
        self.set_islr_withholding_ve()

        for i, tax in enumerate(self.taxes or [], start=1):
            tax.idx = i

    def set_tax_withholding(self) -> None:
        """
        Desactiva el mecanismo TDS/TCS nativo de ERPNext.
        TaxesMixin.set_tax_withholding_ve() se encarga de las retenciones venezolanas.
        """
        return

    # ------------------------------------------------------------------ #
    # GL Entries                                                           #
    # ------------------------------------------------------------------ #

    def get_gl_entries(self, warehouse_account=None):
        """
        VE Sales Debit Note almacena montos positivos.

        A diferencia de la NC, la ND NO niega los GL entries:
          - AR queda DEBITADA → aumenta el saldo pendiente del cliente
          - Ingresos quedan ACREDITADOS → ingreso adicional reconocido
          - IVA queda ACREDITADO → impuesto adicional registrado

        Solo corrige against_voucher_type cuando apunta a la SI original.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice

        self._init_si_defaults()

        wh_from_taxes = sum(
            flt(tax.tax_amount_after_discount_amount)
            for tax in self.get("taxes")
            if cint(tax.is_tax_withholding_account)
        )
        if not flt(self.total_withholding) and wh_from_taxes:
            self.total_withholding = wh_from_taxes

        gl_entries = VESalesInvoice.get_gl_entries(self, warehouse_account)

        for entry in gl_entries:
            if (
                entry.get("against_voucher_type") == self.doctype
                and entry.get("against_voucher") == self.return_against
            ):
                entry["against_voucher_type"] = "Sales Invoice"

        return gl_entries

    def make_customer_gl_entry(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice para incluir total_withholding en el AR.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_customer_gl_entry(self, gl_entries)

    def make_tax_gl_entries(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice para omitir is_tax_withholding_account.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_tax_gl_entries(self, gl_entries)

    def make_gl_entries_for_tax_withholding(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice el manejo de retenciones venezolanas (IVA/ISLR).
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_gl_entries_for_tax_withholding(self, gl_entries)

    # ------------------------------------------------------------------ #
    # Validaciones internas                                                #
    # ------------------------------------------------------------------ #

    def _enforce_positive_amounts(self) -> None:
        """
        Garantiza que todos los montos de ítems sean positivos.
        """
        for item in self.items:
            if flt(item.qty) < 0:
                item.qty = abs(item.qty)
            if flt(item.rate) < 0:
                item.rate = abs(item.rate)

# --------------------------------------------------------------------------- #
# Búsqueda personalizada para return_against                                   #
# --------------------------------------------------------------------------- #

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def query_available_sales_invoices(
    doctype: str,
    txt: str,
    searchfield: str,
    start: int,
    page_len: int,
    filters: dict,
) -> list:
    """
    Retorna facturas de venta disponibles para aplicar una Nota de Débito:
      - Aprobadas (docstatus = 1)
      - No son NC ni ND (is_return = 0, is_debit_note = 0)
      - De la misma empresa
      - Sin NC o ND activa referenciándolas

    Exclusión mutua NC ↔ ND:
      Excluye SIs que ya tienen:
        - Una VE Sales Credit Note activa (docstatus = 1)
        - Una VE Sales Debit Note activa (docstatus = 1)
        - Una Sales Invoice de retorno (is_return = 1, docstatus = 1)
    """
    company = (filters or {}).get("company", "")

    conditions = [
        "si.docstatus = 1",
        "si.is_return = 0",
        "(si.is_debit_note = 0 OR si.is_debit_note IS NULL)",
        "(si.bill_no IS NOT NULL AND si.bill_no != '')",
        "(si.bill_control IS NOT NULL AND si.bill_control != '')",
        # Excluir SIs con NC venezolana activa
        """si.name NOT IN (
            SELECT return_against
            FROM `tabVE Sales Credit Note`
            WHERE docstatus = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
        # Excluir SIs con ND venezolana activa
        """si.name NOT IN (
            SELECT return_against
            FROM `tabVE Sales Debit Note`
            WHERE docstatus = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
        # Excluir SIs con NC/ND estándar de ERPNext activa
        """si.name NOT IN (
            SELECT return_against
            FROM `tabSales Invoice`
            WHERE docstatus = 1
              AND is_return = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
    ]
    values: dict = {}

    if company:
        conditions.append("si.company = %(company)s")
        values["company"] = company

    customer = (filters or {}).get("customer", "")
    if customer:
        conditions.append("si.customer = %(customer)s")
        values["customer"] = customer

    if txt:
        conditions.append(
            "(si.name LIKE %(txt)s"
            " OR si.customer LIKE %(txt)s"
            " OR si.customer_name LIKE %(txt)s"
            " OR si.bill_no LIKE %(txt)s"
            " OR si.bill_control LIKE %(txt)s)"
        )
        values["txt"] = f"%{txt}%"

    where = " AND ".join(conditions)
    values["start"] = int(start)
    values["page_len"] = int(page_len)

    return frappe.db.sql(
        f"""
        SELECT
            si.name,
            CONCAT(si.bill_no, ' — ', si.customer_name) AS label,
            si.posting_date,
            si.grand_total
        FROM `tabSales Invoice` si
        WHERE {where}
        ORDER BY si.posting_date DESC
        LIMIT %(start)s, %(page_len)s
        """,
        values,
    )


@frappe.whitelist()
def void_debit_note(
    docname: str,
    reason: str,
    void_date: str,
    void_time: str,
) -> dict:
    """
    Anula una Nota de Débito en TFHKA (HKA) y luego cancela el documento
    en Frappe, garantizando atomicidad entre ambos sistemas.

    La lógica de comunicación con HKA está centralizada en
    ``TFHKAClient.void_fiscal_document()``.

    Args:
        docname:   Nombre del VE Sales Debit Note.
        reason:    Motivo de anulación (texto libre).
        void_date: Fecha en formato DD/MM/YYYY (convertida por el cliente JS).
        void_time: Hora en HH:MM:SS (24h); se convierte a 12h internamente.
    """
    from l10n_ve.digital_invoice.tfhka_client import TFHKAClient

    debit_note = frappe.get_doc("VE Sales Debit Note", docname)
    frappe.has_permission("VE Sales Debit Note", ptype="cancel", doc=debit_note, throw=True)

    if debit_note.docstatus != 1:
        frappe.throw(_("Solo se pueden anular Notas de Débito aprobadas."))

    client = TFHKAClient()
    client.void_fiscal_document(
        doc=debit_note,
        reason=reason,
        void_date=void_date,
        void_time=void_time,
        tipo_documento="03",
    )

    debit_note.db_set("avoid_reason", reason, update_modified=False)
    debit_note.db_set("is_void", True, update_modified=False)
    debit_note.db_set("hka_status", "Anulada", update_modified=False)
    debit_note.is_void = True
    debit_note.hka_status = "Anulada"
    debit_note._hka_void_confirmed = True
    debit_note.cancel()

    return {
        "status": "success",
        "message": _("Nota de Débito anulada correctamente en HKA y en el sistema."),
    }
