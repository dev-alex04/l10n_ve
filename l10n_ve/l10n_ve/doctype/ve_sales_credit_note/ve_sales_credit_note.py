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


class VESalesCreditNote(TaxesMixin, SalesInvoice):
    """
    Nota de Crédito venezolana para integración con TFHKA (HKA).
    Hereda de SalesInvoice para reutilizar GL entries, cálculo de impuestos
    y validaciones de venta.

    Decisión de diseño — montos positivos:
      Los montos se almacenan siempre en positivo (visualmente natural para el admin).
      El método get_gl_entries() los niega al vuelo antes de que ERPNext los
      procese, logrando la reversión contable correcta sin exponer negativos en la UI.
    """

    # ------------------------------------------------------------------ #
    # Indicador del portal                                                 #
    # ------------------------------------------------------------------ #

    def set_indicator(self) -> None:
        """Sobreescribe SalesInvoice.set_indicator() para evitar 'Overdue'."""
        self.indicator_title = _("Return")
        self.indicator_color = "gray"

    # ------------------------------------------------------------------ #
    # Ciclo de vida del documento                                          #
    # ------------------------------------------------------------------ #

    def before_insert(self) -> None:
        self.is_return = 1
        self.naming_series = "NC-.YYYY.-"
        self.update_outstanding_for_self = 0
        self._init_si_defaults()
        self._inherit_branch_from_si()

    def validate(self) -> None:
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_si_defaults()
        self._inherit_branch_from_si()
        self._enforce_positive_amounts()
        self._validate_unique_note_per_invoice()
        # Intra-mes obligatorio: además de la regla fiscal, la tasa propia
        # de la nota (naturales = 1° del mes) solo coincide con la de la
        # factura afectada dentro del mismo mes.
        validate_return_in_same_month(self)
        # Impide que SalesInvoice.validate() resetee posting_date a la
        # fecha actual del servidor cuando set_posting_time es falsy.
        # El usuario puede cambiar la fecha libremente desde la UI.
        self.set_posting_time = 1
        self._run_super_validate_safely()
        self._set_base_total_with_vat()

    def on_submit(self) -> None:
        """
        SalesInvoice.on_submit() accede a atributos que no existen en el DocType
        de la NC (update_billed_amount_in_sales_order, auto_repeat, etc.).
        Se inicializan aquí antes de delegar al super para evitar AttributeError.
        """
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_si_defaults()
        super().on_submit()
        self._post_fx_truing_entry()
        self._update_parent_invoice_status()
        self._set_pending_hka_status()

    def _post_fx_truing_entry(self) -> None:
        """
        Cierra el diferencial en Bs contra la factura afectada cuando la
        tasa de la NC (fecha de emisión propia) difiere de la de la
        factura; sin este asiento quedaría saldo fantasma en el Auxiliar
        de CxC. Ver true_up_credit_note_fx.
        """
        from l10n_ve.digital_invoice.emission_rerate import true_up_credit_note_fx

        true_up_credit_note_fx(self)

    def _set_pending_hka_status(self) -> None:
        """Marca la NC como Pendiente de emisión HKA si su sucursal tiene serie digital activa."""
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
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_si_defaults()
        super().before_cancel()

    def _cancel_fx_truing_entries(self) -> None:
        """Anula los JEs de ajuste cambiario de esta NC (cancelación pre-HKA)."""
        from l10n_ve.digital_invoice.emission_rerate import cancel_credit_note_fx_truing

        cancel_credit_note_fx_truing(self)

    def _block_cancel_if_sent_to_hka(self) -> None:
        """
        Bloquea la cancelación si la NC ya fue enviada a la imprenta digital
        TFHKA (detectado por la presencia de bill_no o bill_control).

        La excepción es cuando `_hka_void_confirmed = True` está establecido
        en la instancia: indica que `anular_nc()` ya confirmó la anulación
        con HKA y está ejecutando el cancel() de Frappe de forma controlada.

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
                    "La Nota de Crédito <b>{0}</b> ya fue enviada a la imprenta "
                    "digital TFHKA (N° Documento: <b>{1}</b>, N° Control: <b>{2}</b>). "
                    "Use el botón 'Anular NC' para anularla correctamente."
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
        parte del schema de la NC. Se inicializan antes de delegar al super.

        ERPNext hardcodea db_set('status', 'Cancelled') en su on_cancel().
        Si la NC está marcada como is_void, corregimos el status a 'Void' después.

        NOTA: esta debe ser la ÚNICA definición de on_cancel en la clase
        (hubo un duplicado que dejaba muerta a la primera definición).
        """
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_si_defaults()
        super().on_cancel()

        if cint(self.is_void):
            self.db_set("status", "Void")
            self.status = "Void"

        self._cancel_fx_truing_entries()
        self._update_parent_invoice_status()

    def validate_against_voucher_outstanding(self) -> None:
        """
        La validación nativa usa self.doctype para buscar el outstanding del
        return_against, lo que falla porque la NC es un doctype distinto a Sales Invoice.
        Se suprime intencionalmente; el outstanding se gestiona vía
        update_outstanding_amt() en el GL entry con against_voucher = return_against.
        """
        return

    def make_discount_gl_entries(self, gl_entries: list) -> None:
        """
        ERPNext asigna enable_discount_accounting solo para "Sales Invoice" y
        "Purchase Invoice". VE Sales Credit Note no entra en ninguna rama →
        UnboundLocalError al leer la variable en la línea posterior.

        Se delega temporalmente a "Sales Invoice" para reutilizar la lógica correcta.
        """
        self.doctype = "Sales Invoice"
        try:
            super().make_discount_gl_entries(gl_entries)
        finally:
            self.doctype = "VE Sales Credit Note"




    def _inherit_branch_from_si(self) -> None:
        """
        Hereda branch, debit_to y la tasa de cambio de la Factura Original (return_against).

        - branch: si la SI lo tiene, se copia y queda read_only en UI (vía JS).
        - debit_to: cuenta AR de la SI original.
        - conversion_rate / plc_conversion_rate: Las NC toman siempre la tasa
          de la factura original.
        - posting_date / due_date: la nota tiene su propia fecha de expedición (SENIAT).
        """
        if not self.get("return_against"):
            return

        si_values: dict = frappe.get_cached_value(
            "Sales Invoice",
            self.return_against,
            ["branch", "debit_to", "conversion_rate", "plc_conversion_rate"],
            as_dict=True,
        ) or {}

        # ── Branch ──────────────────────────────────────────────────────────
        if si_values.get("branch") and not self.get("branch"):
            self.branch = si_values["branch"]

        # ── Cuenta AR ────────────────────────────────────────────────────────
        if si_values.get("debit_to") and not self.get("debit_to"):
            self.debit_to = si_values["debit_to"]

        # ── Tasa de la factura original ─────────────────────────────────────
        if self.is_new():
            si_rate: float = flt(si_values.get("conversion_rate"))
            if si_rate:
                self.conversion_rate = si_rate
            si_plc_rate: float = flt(si_values.get("plc_conversion_rate"))
            if si_plc_rate:
                self.plc_conversion_rate = si_plc_rate
            elif si_rate:
                self.plc_conversion_rate = si_rate

        # ── Fecha de vencimiento coherente con la fecha propia ──────────────
        if self.is_new() and self.get("posting_date") and not self.get("due_date"):
            self.due_date = self.posting_date


    def _init_si_defaults(self) -> None:

        """
        Inicializa atributos de SalesInvoice que no existen en VE Sales Credit Note
        para evitar AttributeError en los controladores heredados de ERPNext.

        SalesInvoice.validate() itera over child tables asumiendo que existen.
        Las que quitamos del JSON deben estar presentes como listas vacías en memoria.
        """
        # Atributos escalares con defaults seguros
        scalar_defaults: dict = {
            "is_pos": 0,
            "is_debit_note": 0,
            "is_consolidated": 0,
            "update_stock": 0,
            # NOTA: update_qty NO se incluye aquí — es un MÉTODO de StatusUpdater.
            # Incluirlo como int=0 shadowearía el método y causaría TypeError al llamar
            # self.update_qty() desde update_prevdoc_status().
            "is_internal_customer": 0,
            "loyalty_program": None,
            "loyalty_points": 0,
            "loyalty_amount": 0,
            "loyalty_redemption_account": None,
            "loyalty_redemption_cost_center": None,
            "redeem_loyalty_points": 0,
            # Atributos usados en SalesInvoice.on_submit()
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

        # Forzar siempre estos valores críticos
        self.is_pos = 0
        self.is_debit_note = 0

        # Tablas hijas de SalesInvoice que pueden ser iteradas en validate()
        # pero que fueron eliminadas del JSON de VE Sales Credit Note.
        # Se inicializan como listas vacías para evitar AttributeError.
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
        accounts_controller hace 'from ... import validate_return' (línea 64),
        lo que crea una referencia LOCAL al nombre en su propio namespace.
        Si parchamos _ret_module.validate_return esa copia ya no se afecta.
        Debemos parchear _acc_module.validate_return directamente.
        """
        import erpnext.controllers.accounts_controller as _acc_module

        _original_validate_return = _acc_module.validate_return

        def _validate_return_nc(doc):
            if doc.doctype != "VE Sales Credit Note":
                _original_validate_return(doc)
                return

            if not doc.return_against:
                frappe.throw(frappe._("Factura Afectada es obligatoria para la Nota de Crédito"))

            if not frappe.db.exists("Sales Invoice", doc.return_against):
                frappe.throw(
                    frappe._("Factura Afectada no válida: {0}").format(doc.return_against)
                )

            # Validar empresa y cliente contra la SI original
            si = frappe.get_cached_doc("Sales Invoice", doc.return_against)
            if si.company != doc.company:
                frappe.throw(
                    frappe._("La empresa de la NC debe coincidir con la factura original: {0}")
                    .format(si.company)
                )
            if si.customer != doc.customer:
                frappe.throw(
                    frappe._("El cliente de la NC debe coincidir con la factura original: {0}")
                    .format(si.customer)
                )

        # accounts_controller hace "from ... import validate_return" (línea 64),
        # lo que crea una referencia LOCAL al nombre — hay que parchear ESA referencia.
        _acc_module.validate_return = _validate_return_nc
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

        No depende de 'add_taxes_from_taxes_and_charges_template' de Accounts Settings.
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

    def make_precision_loss_gl_entry(self, gl_entries) -> None:
        """En notas de crédito de retorno no se debe generar pérdida de precisión contable,
        ya que la diferencia entre base_net_amount y net_amount * conversion_rate
        ya está absorbida por la base de la factura de origen heredada.
        """
        return

    def get_gl_entries(self, warehouse_account=None):
        """
        VE Sales Credit Note almacena montos positivos (requerimiento de UX).

        Aquí se hacen dos cosas antes de que ERPNext procese los GL entries:

        1. Se usa VESalesInvoice.get_gl_entries() en lugar del SalesInvoice nativo
           de ERPNext. Esto es crítico porque el nativo:
             - NO suma total_withholding al AR en make_customer_gl_entry()
             - NO separa las retenciones en make_tax_gl_entries()
           Resultado sin este fix: imbalance = IVA + IVA Withholding.

        2. Se niegan todos los campos de signo para que toggle_debit_credit_if_negative
           los invierta al lado contable correcto:
             - AR queda ACREDITADA  → reduce el saldo pendiente del cliente
             - Ingresos quedan DEBITADOS → revierte el ingreso reconocido
             - IVA queda DEBITADO   → revierte el impuesto registrado
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice

        # _init_si_defaults() solo se llama en validate/before_insert.
        # El ledger preview invoca make_gl_entries() directamente (sin pasar por
        # validate), por lo que los atributos de SalesInvoice no existen aún.
        # Se inicializa aquí para garantizar que update_stock, update_qty, etc.
        # estén disponibles para todos los métodos delegados.
        self._init_si_defaults()

        # total_withholding ahora es campo persistente en el DocType.
        # Frappe lo carga desde DB automáticamente. Solo recalculamos si:
        #   a) No hay valor en DB (doc guardado antes del bench migrate), o
        #   b) Las taxes tienen retenciones que difieren del valor guardado
        #      (ej. taxes modificadas sin guardar previo al preview)
        wh_from_taxes = sum(
            flt(tax.tax_amount_after_discount_amount)
            for tax in self.get("taxes")
            if cint(tax.is_tax_withholding_account)
        )
        if not flt(self.total_withholding) and wh_from_taxes:
            self.total_withholding = wh_from_taxes

        gl_entries = VESalesInvoice.get_gl_entries(self, warehouse_account)

        sign_fields = (
            "debit",
            "credit",
            "debit_in_account_currency",
            "credit_in_account_currency",
            "debit_in_transaction_currency",
            "credit_in_transaction_currency",
        )

        for entry in gl_entries:
            for field in sign_fields:
                value = entry.get(field)
                if value:
                    entry[field] = -1 * flt(value)

            # Corrección: against_voucher_type debe coincidir con el doctype de against_voucher.
            # Cuando against_voucher == self.return_against (la SI original), el tipo debe ser
            # "Sales Invoice", no "VE Sales Credit Note".
            # NO tocar entries donde against_voucher == self.name (esos sí son NC).
            if (
                entry.get("against_voucher_type") == self.doctype
                and entry.get("against_voucher") == self.return_against
            ):
                entry["against_voucher_type"] = "Sales Invoice"

        return gl_entries

    def make_customer_gl_entry(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice para incluir total_withholding en el AR.
        El SalesInvoice nativo de ERPNext no suma las retenciones al débito
        del cliente, causando desbalance en los GL entries de la NC.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_customer_gl_entry(self, gl_entries)

    def make_tax_gl_entries(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice para omitir is_tax_withholding_account.
        El SalesInvoice nativo acredita TODOS los impuestos incluyendo
        retenciones, lo que duplica el monto en el side crédito.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_tax_gl_entries(self, gl_entries)

    def make_gl_entries_for_tax_withholding(self, gl_entries: list) -> None:
        """
        Delega a VESalesInvoice el manejo de retenciones venezolanas (IVA/ISLR).
        Este método no existe en SalesInvoice nativo de ERPNext; sin esta
        delegación se produce AttributeError al procesar la NC.
        """
        from l10n_ve.overrides.sales_invoice import VESalesInvoice
        VESalesInvoice.make_gl_entries_for_tax_withholding(self, gl_entries)

    # ------------------------------------------------------------------ #
    # Validaciones internas                                                #
    # ------------------------------------------------------------------ #

    def _enforce_positive_amounts(self) -> None:
        """
        Garantiza que todos los montos de ítems sean positivos.
        Previene errores del usuario que cambien valores negativos
        heredados de documentos ERPNext o ingresos manuales incorrectos.
        """
        for item in self.items:
            if flt(item.qty) < 0:
                item.qty = abs(item.qty)
            if flt(item.rate) < 0:
                item.rate = abs(item.rate)



# --------------------------------------------------------------------------- #
# Búsqueda personalizada para return_against                                  #
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
    Retorna facturas de venta disponibles para aplicar una Nota de Crédito:
      - Aprobadas (docstatus = 1)
      - No son NC ni ND (is_return = 0)
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
        # Excluir SIs con NC venezolana activa (subquery — eficiente con índice)
        """si.name NOT IN (
            SELECT return_against
            FROM `tabVE Sales Credit Note`
            WHERE docstatus = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
        # Excluir SIs con ND venezolana activa (exclusión mutua NC↔ND)
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
def make_replacement_invoice(source_name: str) -> "Document":
    """
    Crea un borrador de Sales Invoice copiando la factura original
    vinculada a esta Nota de Crédito.

    - posting_date = hoy (fecha real de emisión del reemplazo)
    - conversion_rate = tasa de hoy (de tabCurrency Exchange)
    - from_date / to_date = período del servicio original (sin cambio)
    - subscription = heredado (los hooks de la app ISP actuarán al insertar)

    Esta función es agnóstica a domina_isp: trabaja únicamente con
    Sales Invoice estándar de ERPNext.
    """
    from frappe.model.mapper import get_mapped_doc
    from frappe.utils import nowdate

    nc = frappe.get_cached_doc("VE Sales Credit Note", source_name)

    if not nc.return_against:
        frappe.throw(
            frappe._("La Nota de Crédito no tiene factura original vinculada.")
        )

    def _ajustar_fecha_y_tasa(source_doc, target_doc) -> None:
        hoy: str = nowdate()
        target_doc.posting_date = hoy
        target_doc.due_date = hoy

        if source_doc.get("branch"):
            target_doc.branch = source_doc.branch

        # Tasa de hoy desde Currency Exchange (Frappe core — sin dependencia de erpnext)
        if target_doc.currency and target_doc.currency != source_doc.company_currency:
            tasa_hoy: float | None = frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": target_doc.currency, "date": hoy},
                "exchange_rate",
                order_by="modified desc",
            )
            if tasa_hoy:
                target_doc.conversion_rate = tasa_hoy

    return get_mapped_doc(
        "Sales Invoice",
        nc.return_against,
        {
            "Sales Invoice": {
                "doctype": "Sales Invoice",
                "field_no_map": [
                    "name",
                    "naming_series",
                    "amended_from",
                    "is_return",
                    "return_against",
                    "bill_no",
                    "bill_date",
                    "outstanding_amount",
                    "status",
                    "conversion_rate",
                    "plc_conversion_rate",
                    # Campos de retención específicos de Venezuela:
                    # la nueva factura tiene su propia retención
                    "custom_vat_withholding_voucher_number",
                    "custom_withholding_date",
                    "custom_voucher_image",
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
        postprocess=_ajustar_fecha_y_tasa,
        ignore_permissions=True,
    )


@frappe.whitelist()
def void_credit_note(
    docname: str,
    reason: str,
    void_date: str,
    void_time: str,
) -> dict:
    """
    Anula una Nota de Crédito en TFHKA (HKA) y luego cancela el documento
    en Frappe, garantizando atomicidad entre ambos sistemas.

    La lógica de comunicación con HKA está centralizada en
    ``TFHKAClient.void_fiscal_document()``.

    Args:
        docname:   Nombre del VE Sales Credit Note.
        reason:    Motivo de anulación (texto libre).
        void_date: Fecha en formato DD/MM/YYYY (convertida por el cliente JS).
        void_time: Hora en HH:MM:SS (24h); se convierte a 12h internamente.
    """
    from l10n_ve.digital_invoice.tfhka_client import TFHKAClient

    credit_note = frappe.get_doc("VE Sales Credit Note", docname)
    frappe.has_permission("VE Sales Credit Note", ptype="cancel", doc=credit_note, throw=True)

    if credit_note.docstatus != 1:
        frappe.throw(_("Solo se pueden anular Notas de Crédito aprobadas."))

    client = TFHKAClient()
    client.void_fiscal_document(
        doc=credit_note,
        reason=reason,
        void_date=void_date,
        void_time=void_time,
        tipo_documento="02",
    )

    # HKA confirmó la anulación → persistir motivo, marcar como anulado y cancelar en Frappe.
    # db_set antes de cancel() para que on_cancel() ya lea is_void=True y asigne status "Void".
    # update_modified=False evita TimestampMismatchError al hacer cancel() → save()
    credit_note.db_set("avoid_reason", reason, update_modified=False)
    credit_note.db_set("is_void", True, update_modified=False)
    credit_note.db_set("hka_status", "Anulada", update_modified=False)
    credit_note.is_void = True
    credit_note.hka_status = "Anulada"
    credit_note._hka_void_confirmed = True
    credit_note.cancel()

    return {
        "status": "success",
        "message": _("Nota de Crédito anulada correctamente en HKA y en el sistema."),
    }

