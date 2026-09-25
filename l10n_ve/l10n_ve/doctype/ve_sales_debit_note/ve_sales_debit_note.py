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
    get_ve_exchange_rate_for_customer,
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
        # No retroactiva: no puede ser anterior a la factura original
        # (permite emisión en meses posteriores según Ley IVA/Providencia 00071).
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
        Hereda branch, debit_to y la tasa de cambio por defecto de la Factura Original (return_against).

        A diferencia de la NC, en la ND la tasa de la factura afectada es un
        valor por defecto y no un invariante: el campo queda editable y el JS
        la re-deriva si el usuario cambia posting_date. La ND puede hacerlo
        sin dejar diferencial porque su ledger se referencia a sí misma
        (against_voucher = self.name), no a la factura afectada.
        """
        if not self.get("return_against"):
            return

        si_values: dict = frappe.get_cached_value(
            "Sales Invoice",
            self.return_against,
            ["branch", "debit_to", "conversion_rate", "plc_conversion_rate"],
            as_dict=True,
        ) or {}

        if si_values.get("branch") and not self.get("branch"):
            self.branch = si_values["branch"]

        if si_values.get("debit_to") and not self.get("debit_to"):
            self.debit_to = si_values["debit_to"]

        # Tasa por defecto: la de la factura afectada, solo al crear el borrador.
        if self.is_new():
            si_rate: float = flt(si_values.get("conversion_rate"))
            if si_rate:
                self.conversion_rate = si_rate
                self.plc_conversion_rate = (
                    flt(si_values.get("plc_conversion_rate")) or si_rate
                )
            elif self.get("posting_date"):
                # Factura sin tasa utilizable: cae a la tasa de la fecha propia.
                own_rate: float = flt(get_ve_exchange_rate_for_customer(
                    self.customer, str(self.posting_date)
                ))
                if own_rate:
                    self.conversion_rate = own_rate
                    self.plc_conversion_rate = own_rate

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
        self.set_municipal_withholding_ve()

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

    def make_precision_loss_gl_entry(self, gl_entries: list) -> None:
        """Misma regla que VESalesInvoice.make_precision_loss_gl_entry.

        Con el método «Desde el total de la factura», en una nota en divisa el ancla separa
        a propósito base_net_total de net_total × tasa, y el asiento de «pérdida de
        precisión» que ERPNext agrega por esa brecha descuadra la nota: una ND de 1,75 USD
        quedaba con Bs 1,07 de diferencia y no se podía aprobar («Debit and Credit not
        equal»). Con el ancla, la diferencia ya está absorbida en base_grand_total.
        """
        from l10n_ve.controllers.taxes_and_totals import TAX_FROM_TOTAL

        company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
        if company_currency and self.currency != company_currency:
            method = frappe.get_cached_value(
                "Venezuela Account Settings", "Venezuela Account Settings",
                "tax_calculation_method",
            ) or ""
            if method == TAX_FROM_TOTAL:
                return

        super().make_precision_loss_gl_entry(gl_entries)

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


@frappe.whitelist()
def upload_debit_note_voucher_data(
    docname: str,
    withholding_type: str,
    voucher_number: str | None = None,
    withholding_date: str | None = None,
    file_url: str | None = None,
    registration_date: str | None = None,
) -> dict:
    """Actualiza los metadatos del comprobante de retención en una Nota de Débito."""
    if not docname:
        frappe.throw(_("Debe especificar la Nota de Débito."))

    debit_note = frappe.get_doc("VE Sales Debit Note", docname)
    frappe.has_permission("VE Sales Debit Note", ptype="write", doc=debit_note, throw=True)

    if not withholding_date or not file_url:
        frappe.throw(_("Faltan datos obligatorios (Fecha y Archivo de Comprobante)."))

    from l10n_ve.utils.utils import validate_portal_upload, delete_old_attachment

    validate_portal_upload(file_url, 5)

    is_vat = withholding_type == "VAT"
    if is_vat and voucher_number:
        import re
        if not re.match(r"^\d{14}$", voucher_number):
            frappe.throw(_("El Número de Comprobante de IVA debe tener exactamente 14 caracteres numéricos."))

    field_file = "voucher_image" if is_vat else "voucher_image_islr"
    delete_old_attachment(debit_note, field_file, file_url)

    file_doc_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
    if file_doc_name:
        frappe.db.set_value("File", file_doc_name, {
            "attached_to_doctype": "VE Sales Debit Note",
            "attached_to_name": docname
        })

    reg_date = registration_date or withholding_date or frappe.utils.nowdate()
    update_dict = {}
    if is_vat:
        update_dict = {
            "vat_withholding_voucher_number": voucher_number,
            "withholding_date": withholding_date,
            "vat_registration_date": reg_date,
            "voucher_image": file_url,
        }
    else:
        update_dict = {
            "islr_receipt_number": voucher_number,
            "islr_date": withholding_date,
            "islr_registration_date": reg_date,
            "voucher_image_islr": file_url,
        }

    frappe.db.set_value("VE Sales Debit Note", docname, update_dict, update_modified=True)

    label = "IVA" if is_vat else "ISLR"
    comment = frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": "VE Sales Debit Note",
        "reference_name": docname,
        "content": f"Comprobante de Retención de {label} cargado. Número: {voucher_number or 'S/N'}. Fecha: {withholding_date}",
        "comment_email": frappe.session.user
    })
    comment.flags.ignore_permissions = True
    comment.insert(ignore_permissions=True)

    return {
        "status": "success",
        "msg": _("Comprobante de {0} cargado exitosamente.").format(label),
    }


@frappe.whitelist()
def apply_debit_note_withholding(
    debit_note_name: str,
    withholding_type: str,
    tax_account: str,
    voucher_number: str | None = None,
    withholding_date: str | None = None,
    file_url: str | None = None,
    rate: float = 0.0,
    registration_date: str | None = None,
) -> dict:
    """Aplica la retención de IVA o ISLR a una Nota de Débito aprobada (docstatus=1),
    inyecta la fila en Sales Taxes and Charges y genera el Asiento Contable que reduce la CxC.
    """
    if not debit_note_name:
        frappe.throw(_("Debe especificar la Nota de Débito."))

    debit_note = frappe.get_doc("VE Sales Debit Note", debit_note_name)
    frappe.has_permission("VE Sales Debit Note", ptype="write", doc=debit_note, throw=True)

    if debit_note.docstatus != 1:
        frappe.throw(_("Solo se puede aplicar retención retroactiva a Notas de Débito aprobadas."))

    if not tax_account:
        frappe.throw(_("Debe seleccionar una Cuenta de Retención."))

    is_vat = withholding_type == "VAT"
    charge_type = "VAT Withholding" if is_vat else "ISLR"
    label = "IVA" if is_vat else "ISLR"

    duplicate = any(t.charge_type == charge_type for t in (debit_note.taxes or []))
    if duplicate:
        frappe.throw(_("La Nota de Débito {0} ya tiene una retención de tipo {1}.").format(
            debit_note.name, charge_type
        ))

    if is_vat and voucher_number:
        import re
        if not re.match(r"^\d{14}$", voucher_number):
            frappe.throw(_("El Número de Comprobante de IVA debe tener exactamente 14 caracteres numéricos."))

    if file_url:
        from l10n_ve.utils.utils import validate_portal_upload
        validate_portal_upload(file_url, 5)

    company_currency = frappe.get_cached_value("Company", debit_note.company, "default_currency")
    debit_note_currency = debit_note.currency or company_currency
    conversion_rate = flt(debit_note.conversion_rate) or flt(debit_note.plc_conversion_rate)
    if not company_currency or not conversion_rate:
        frappe.throw(
            _("No se puede calcular la retención: falta la moneda de la empresa {0} o la tasa de cambio de la Nota de Débito {1}.").format(
                debit_note.company, debit_note.name
            )
        )

    if is_vat:
        vat_base_bs = sum(flt(t.base_tax_amount) for t in (debit_note.taxes or []) if t.charge_type == "VAT")
        if not vat_base_bs:
            vat_base_bs = sum(flt(t.tax_amount) for t in (debit_note.taxes or []) if t.charge_type == "VAT") * conversion_rate

        if vat_base_bs <= 0:
            frappe.throw(_("La Nota de Débito no tiene impuestos de IVA calculados."))

        withholding_rate = flt(rate)
        if not withholding_rate:
            from l10n_ve.overrides.sales_invoice import get_vat_category_rate
            cat_name = frappe.db.get_value("Customer", debit_note.customer, "tax_withholding_category")
            withholding_rate = get_vat_category_rate(cat_name, debit_note.company)

        base_amount_bs = flt(vat_base_bs * (withholding_rate / 100.0), 2)
    else:
        net_total_bs = flt(debit_note.base_net_total)
        withholding_rate = flt(rate)
        if not withholding_rate:
            customer_data = frappe.db.get_value(
                "Customer",
                debit_note.customer,
                ["type_of_person", "tabulator_islr"],
                as_dict=True
            )
            if customer_data and customer_data.tabulator_islr:
                tab_doc = frappe.get_doc("Tabulator ISLR", customer_data.tabulator_islr)
                target_row = next(
                    (r for r in (tab_doc.aliquot or []) if r.types_of_person == customer_data.type_of_person),
                    None
                )
                if not target_row and tab_doc.aliquot:
                    target_row = tab_doc.aliquot[0]
                if target_row:
                    withholding_rate = flt(target_row.aliquot)

        if not withholding_rate:
            frappe.throw(_("No se pudo determinar la alícuota de ISLR para el cliente."))

        base_amount_bs = flt(net_total_bs * (withholding_rate / 100.0), 2)

    if debit_note_currency != company_currency:
        amount_curr = flt(base_amount_bs / conversion_rate, 2)
    else:
        amount_curr = base_amount_bs

    tax_account_currency = frappe.db.get_value("Account", tax_account, "account_currency") or company_currency
    receivable_account = debit_note.debit_to
    receivable_account_currency = frappe.db.get_value("Account", receivable_account, "account_currency") or company_currency

    posting_date = withholding_date or frappe.utils.today()

    je = frappe.new_doc("Journal Entry")
    je.company = debit_note.company
    je.posting_date = posting_date
    je.user_remark = (
        f"Retención de {label} (ND {debit_note.name}, "
        f"Comprobante: {voucher_number or 'S/N'})."
    )
    je.multi_currency = 1 if (
        debit_note_currency != company_currency or
        tax_account_currency != company_currency or
        receivable_account_currency != company_currency
    ) else 0

    # Fila 1: Cuenta de Retención (DÉBITO) -> Aumenta crédito fiscal
    tax_exchange_rate = conversion_rate if (tax_account_currency != company_currency and tax_account_currency == debit_note_currency) else 1.0
    tax_row_je = {
        "account": tax_account,
        "cost_center": debit_note.cost_center,
        "debit": base_amount_bs,
        "debit_in_account_currency": amount_curr if tax_account_currency == debit_note_currency else base_amount_bs,
        "exchange_rate": tax_exchange_rate,
    }
    je.append("accounts", tax_row_je)

    # Fila 2: Cuenta por Cobrar (CRÉDITO) -> Disminuye el saldo adeudado de la Nota de Débito
    rec_exchange_rate = conversion_rate if (receivable_account_currency != company_currency and receivable_account_currency == debit_note_currency) else 1.0
    rec_row = {
        "account": receivable_account,
        "party_type": "Customer",
        "party": debit_note.customer,
        "reference_type": "VE Sales Debit Note",
        "reference_name": debit_note.name,
        "cost_center": debit_note.cost_center,
        "credit": base_amount_bs,
        "credit_in_account_currency": amount_curr if receivable_account_currency == debit_note_currency else base_amount_bs,
        "exchange_rate": rec_exchange_rate,
    }
    je.append("accounts", rec_row)

    je.flags.ignore_permissions = True
    je.insert(ignore_permissions=True)
    je.submit()

    idx = len(debit_note.taxes or []) + 1
    tax_row = frappe.new_doc("Sales Taxes and Charges")
    tax_row.parent = debit_note.name
    tax_row.parenttype = "VE Sales Debit Note"
    tax_row.parentfield = "taxes"
    tax_row.idx = idx
    tax_row.charge_type = charge_type
    tax_row.add_deduct_tax = "Deduct"
    tax_row.category = "Total"
    tax_row.account_head = tax_account
    tax_row.description = f"Retención de {label} (Ajuste) - Asiento: {je.name}"
    tax_row.rate = flt(withholding_rate)
    tax_row.tax_amount = amount_curr
    tax_row.base_tax_amount = base_amount_bs
    tax_row.tax_amount_after_discount_amount = amount_curr
    tax_row.base_tax_amount_after_discount_amount = base_amount_bs
    tax_row.is_tax_withholding_account = 1
    tax_row.dont_recompute_tax = 1
    tax_row.cost_center = debit_note.cost_center
    tax_row.db_insert()

    reg_date = registration_date or withholding_date or frappe.utils.nowdate()
    update_data = {
        "total_withholding": flt(debit_note.total_withholding) + amount_curr,
    }
    if is_vat:
        update_data.update({
            "vat_withholding_voucher_number": voucher_number,
            "withholding_date": withholding_date,
            "vat_registration_date": reg_date,
            "voucher_image": file_url,
        })
    else:
        update_data.update({
            "islr_receipt_number": voucher_number,
            "islr_date": withholding_date,
            "islr_registration_date": reg_date,
            "voucher_image_islr": file_url,
        })

    frappe.db.set_value("VE Sales Debit Note", debit_note.name, update_data, update_modified=False)

    debit_note._update_outstanding_amount()

    if file_url:
        file_doc_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
        if file_doc_name:
            frappe.db.set_value("File", file_doc_name, {
                "attached_to_doctype": "VE Sales Debit Note",
                "attached_to_name": debit_note.name
            })

    comment = frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": "VE Sales Debit Note",
        "reference_name": debit_note.name,
        "content": f"Retención de {label} aplicada exitosamente. Comprobante: {voucher_number or 'S/N'}. Fecha: {withholding_date}. Asiento contable: {je.name}",
        "comment_email": frappe.session.user
    })
    comment.flags.ignore_permissions = True
    comment.insert(ignore_permissions=True)

    return {
        "status": "success",
        "journal_entry": je.name,
        "msg": _("Retención de {0} aplicada y Asiento {1} creado con éxito.").format(label, je.name)
    }


@frappe.whitelist()
def remove_debit_note_withholding(
    debit_note_name: str,
    withholding_type: str,
) -> dict[str, Any]:
    """Quita una retención (IVA o ISLR) de una Nota de Débito aprobada.

    1. Si existen filas de impuestos aplicadas, crea el asiento contable de reverso:
       - DÉBITO: Cuenta por Cobrar del cliente referenciando la Nota de Débito (vuelve a deberlo el cliente)
       - CRÉDITO: Cuenta de Retención (se vacía el crédito fiscal)
    2. Elimina la fila correspondiente de tabSales Taxes and Charges.
    3. Limpia los metadatos del comprobante (número, fecha, archivo adjunto).
    4. Recalcula el saldo pendiente (outstanding_amount) y total_withholding.
    """
    user_roles: set[str] = set(frappe.get_roles())
    allowed_roles: set[str] = {"Accounts Manager", "Accounts User", "System Manager"}
    if not allowed_roles.intersection(user_roles):
        frappe.throw(
            _("No tiene los permisos suficientes para modificar retenciones sobre esta nota de débito."),
            frappe.PermissionError,
        )

    if withholding_type not in ("VAT", "ISLR"):
        frappe.throw(_("Tipo de retención inválido: {0}. Use 'VAT' o 'ISLR'.").format(withholding_type))

    debit_note: "VESalesDebitNote" = frappe.get_doc("VE Sales Debit Note", debit_note_name)
    frappe.has_permission("VE Sales Debit Note", ptype="write", doc=debit_note, throw=True)
    if debit_note.docstatus != 1:
        frappe.throw(_("Solo se pueden retirar retenciones de notas de débito validadas."))

    is_vat: bool = withholding_type == "VAT"
    charge_type: str = "VAT Withholding" if is_vat else "ISLR"
    label: str = "IVA" if is_vat else "ISLR"

    tax_rows: list[Any] = [
        row for row in (debit_note.taxes or [])
        if row.charge_type == charge_type and flt(row.base_tax_amount)
    ]

    voucher_field: str = "vat_withholding_voucher_number" if is_vat else "islr_receipt_number"
    has_voucher: bool = bool(debit_note.get(voucher_field))

    if not tax_rows and not has_voucher:
        frappe.throw(
            _("La Nota de Débito {0} no tiene retención ni comprobante de {1} que quitar.").format(
                debit_note.name, label
            )
        )

    company_currency: str = frappe.get_cached_value("Company", debit_note.company, "default_currency")
    debit_note_currency: str = debit_note.currency or company_currency
    conversion_rate: float = flt(debit_note.conversion_rate)
    if not company_currency or not conversion_rate:
        frappe.throw(
            _("No se puede revertir la retención: falta la moneda de la empresa {0} o la tasa de cambio de la Nota de Débito {1}.").format(
                debit_note.company, debit_note.name
            )
        )

    reversal_entries: list[str] = []

    for row in tax_rows:
        base_tax_amount: float = flt(row.base_tax_amount)
        amount_curr: float = flt(row.tax_amount) or base_tax_amount

        tax_account_currency: str = (
            frappe.db.get_value("Account", row.account_head, "account_currency") or company_currency
        )
        receivable_account: str = debit_note.debit_to
        receivable_account_currency: str = (
            frappe.db.get_value("Account", receivable_account, "account_currency") or company_currency
        )

        reversal_je = frappe.new_doc("Journal Entry")
        reversal_je.company = debit_note.company
        reversal_je.posting_date = frappe.utils.today()
        reversal_je.user_remark = f"Reverso de Retención de {label} (ND {debit_note.name})."
        reversal_je.multi_currency = 1 if (
            debit_note_currency != company_currency
            or tax_account_currency != company_currency
            or receivable_account_currency != company_currency
        ) else 0

        # Fila 1: Cuenta por Cobrar (DÉBITO) -> Vuelve a deberlo el cliente en la ND
        rec_exchange_rate = (
            conversion_rate
            if (receivable_account_currency != company_currency and receivable_account_currency == debit_note_currency)
            else 1.0
        )
        reversal_je.append("accounts", {
            "account": receivable_account,
            "party_type": "Customer",
            "party": debit_note.customer,
            "reference_type": "VE Sales Debit Note",
            "reference_name": debit_note.name,
            "cost_center": debit_note.cost_center,
            "debit": base_tax_amount,
            "debit_in_account_currency": amount_curr if receivable_account_currency == debit_note_currency else base_tax_amount,
            "exchange_rate": rec_exchange_rate,
        })

        # Fila 2: Cuenta de Retención (CRÉDITO) -> Revierte el crédito fiscal
        tax_exchange_rate = (
            conversion_rate
            if (tax_account_currency != company_currency and tax_account_currency == debit_note_currency)
            else 1.0
        )
        reversal_je.append("accounts", {
            "account": row.account_head,
            "cost_center": debit_note.cost_center,
            "credit": base_tax_amount,
            "credit_in_account_currency": amount_curr if tax_account_currency == debit_note_currency else base_tax_amount,
            "exchange_rate": tax_exchange_rate,
        })

        reversal_je.flags.ignore_permissions = True
        reversal_je.insert(ignore_permissions=True)
        reversal_je.submit()
        reversal_entries.append(reversal_je.name)

        frappe.db.delete("Sales Taxes and Charges", {"name": row.name})

    update_fields: dict[str, Any] = {}
    if is_vat:
        update_fields.update({
            "vat_withholding_voucher_number": None,
            "withholding_date": None,
            "vat_registration_date": None,
            "voucher_image": None,
        })
    else:
        update_fields.update({
            "islr_receipt_number": None,
            "islr_date": None,
            "islr_registration_date": None,
            "voucher_image_islr": None,
        })

    frappe.clear_document_cache("VE Sales Debit Note", debit_note.name)
    updated_nd = frappe.get_doc("VE Sales Debit Note", debit_note.name)
    new_total_withholding = sum(
        flt(tax.tax_amount) for tax in (updated_nd.taxes or [])
        if tax.is_tax_withholding_account
    )
    update_fields["total_withholding"] = new_total_withholding

    frappe.db.set_value("VE Sales Debit Note", debit_note.name, update_fields, update_modified=False)
    frappe.clear_document_cache("VE Sales Debit Note", debit_note.name)

    updated_nd = frappe.get_doc("VE Sales Debit Note", debit_note.name)
    updated_nd._update_outstanding_amount()

    comment_msg: str
    if reversal_entries:
        comment_msg = f"Retención de {label} retirada exitosamente. Asiento(s) de reverso: {', '.join(reversal_entries)}."
    else:
        comment_msg = f"Datos del comprobante de {label} eliminados exitosamente."

    comment = frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": "VE Sales Debit Note",
        "reference_name": debit_note.name,
        "content": comment_msg,
        "comment_email": frappe.session.user,
    })
    comment.flags.ignore_permissions = True
    comment.insert(ignore_permissions=True)

    success_msg = (
        _("Retención de {0} retirada. Asiento(s) de reverso: {1}").format(label, ", ".join(reversal_entries))
        if reversal_entries
        else _("Datos del comprobante de {0} retirados con éxito.").format(label)
    )

    return {
        "status": "success",
        "journal_entries": reversal_entries,
        "msg": success_msg,
    }


