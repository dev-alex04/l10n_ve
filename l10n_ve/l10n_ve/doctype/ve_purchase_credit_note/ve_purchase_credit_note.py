# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from l10n_ve.controllers.taxes_mixin import TaxesMixin
from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals


class VEPurchaseCreditNote(TaxesMixin, PurchaseInvoice):
    """
    Nota de Crédito de Compras venezolana.
    Hereda de PurchaseInvoice para reutilizar GL entries, cálculo de impuestos
    y validaciones de compra.

    Decisión de diseño — montos positivos:
      Los montos se almacenan siempre en positivo (visualmente natural para el admin).
      El método get_gl_entries() los niega al vuelo antes de que ERPNext los
      procese, logrando la reversión contable correcta sin exponer negativos en la UI.
    """

    # ------------------------------------------------------------------ #
    # Ciclo de vida del documento                                          #
    # ------------------------------------------------------------------ #

    def before_insert(self) -> None:
        self.is_return = 1
        self.naming_series = "NC-COMP-.YYYY.-"
        self.update_outstanding_for_self = 0
        self._init_pi_defaults()
        self._inherit_data_from_pi()

    def validate(self) -> None:
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_pi_defaults()
        self._inherit_data_from_pi()
        self._enforce_positive_amounts()
        self._validate_unique_note_per_invoice()
        self._validate_credit_note_number()
        # Impide que PurchaseInvoice.validate() resetee posting_date
        self.set_posting_time = 1
        self._validate_bill_date()
        self._run_super_validate_safely()
        self._set_base_total_with_vat()

    def on_submit(self) -> None:
        """
        PurchaseInvoice.on_submit() accede a atributos que no existen en el DocType
        de la NC. Se inicializan aquí antes de delegar al super.
        """
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_pi_defaults()
        super().on_submit()
        self._update_parent_invoice_status()

    def before_cancel(self) -> None:
        """
        PurchaseInvoice.before_cancel() accede a atributos que no existen.
        Se inicializan antes de delegar. Se valida que no esté asociada a
        comprobantes de retención vigentes.
        """
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_pi_defaults()
        self._validate_withholding_vouchers_on_cancel()

    def on_cancel(self) -> None:
        self.is_return = 1
        self.update_outstanding_for_self = 0
        self._init_pi_defaults()
        super().on_cancel()
        self._update_parent_invoice_status()

    def _update_parent_invoice_status(self) -> None:
        """Recalcula el status de la PI original tras emitir/cancelar esta NC."""
        if not self.return_against:
            return
        if not frappe.db.exists("Purchase Invoice", self.return_against):
            return

        pi = frappe.get_doc("Purchase Invoice", self.return_against)
        pi.set_status(update=True)

    def validate_against_voucher_outstanding(self) -> None:
        """
        La validación nativa usa self.doctype para buscar el outstanding del
        return_against, lo que falla porque la NC es un doctype distinto a Purchase Invoice.
        Se suprime intencionalmente.
        """
        return

    def make_discount_gl_entries(self, gl_entries: list) -> None:
        """
        ERPNext asigna enable_discount_accounting solo para "Sales Invoice" y
        "Purchase Invoice". VE Purchase Credit Note no entra en ninguna rama.
        Se delega temporalmente a "Purchase Invoice".
        """
        self.doctype = "Purchase Invoice"
        try:
            super().make_discount_gl_entries(gl_entries)
        finally:
            self.doctype = "VE Purchase Credit Note"

    def make_precision_loss_gl_entry(self, gl_entries: list) -> None:
        """ERPNext core usa `self.customer` cuando doctype != 'Purchase Invoice'.

        Redundante con `self.customer = self.supplier` en `_init_pi_defaults()`,
        pero se mantiene como cinturón de seguridad por si el MRO no resuelve
        el fallback correctamente en todas las rutas de ejecución.
        """
        self.doctype = "Purchase Invoice"
        try:
            super().make_precision_loss_gl_entry(gl_entries)
        finally:
            self.doctype = "VE Purchase Credit Note"

    def _grand_total_includes_withholding(self) -> bool:
        """El grand_total de la NC ya descuenta retenciones (es neto).

        set_cumulative_total en taxes_and_totals resta VAT Withholding e ISLR
        del total acumulado, por lo que grand_total = base + IVA - retenciones.
        No se necesita DR extra al AP.
        """
        return False

    def _validate_withholding_vouchers_on_cancel(self) -> None:
        """Bloquea la cancelación si la NC está asociada a un comprobante de retención."""
        reasons: list[str] = []

        if frappe.db.exists(
            "VAT Withholding Voucher Item",
            {"purchase_invoice": self.name}
        ):
            reasons.append("un Comprobante de retención de IVA")

        if frappe.db.exists(
            "ISLR Withholding Voucher Item",
            {"purchase_invoice": self.name}
        ):
            reasons.append("un Comprobante de retención de ISLR")

        if reasons:
            frappe.throw(
                _("No se puede cancelar esta Nota de Crédito. Está asociada a {0}.").format(
                    " y a ".join(reasons)
                ),
                frappe.ValidationError,
            )

    # ------------------------------------------------------------------ #
    # Herencia de datos desde la PI original                               #
    # ------------------------------------------------------------------ #

    def _inherit_data_from_pi(self) -> None:
        """
        Hereda credit_to, tasa de cambio y fechas de la Factura Original (return_against).
        También asigna affected_invoice_number desde el bill_no de la PI original.
        """
        if not self.get("return_against"):
            return

        pi_values: dict = frappe.get_cached_value(
            "Purchase Invoice",
            self.return_against,
            [
                "credit_to", "conversion_rate",
                "plc_conversion_rate", "posting_date", "due_date",
                "bill_no", "branch",
            ],
            as_dict=True,
        ) or {}

        # ── Cuenta AP ────────────────────────────────────────────────────────
        if pi_values.get("credit_to") and not self.get("credit_to"):
            self.credit_to = pi_values["credit_to"]

        # ── Tasa de cambio ───────────────────────────────────────────────────
        # Invariante, no valor por defecto: el campo va read_only en la UI
        # (que no cubre API/imports) y la NC descarga el CxP contra la PI
        # afectada, así que cualquier otra tasa dejaría diferencial en Bs.
        # Se re-aplica en cada validate mientras siga en borrador.
        pi_rate: float = flt(pi_values.get("conversion_rate"))
        if pi_rate:
            self.conversion_rate = pi_rate
            self.plc_conversion_rate = (
                flt(pi_values.get("plc_conversion_rate")) or pi_rate
            )

        # ── Fechas: heredar de la PI ─────────────────────────────────────────
        if self.is_new() and pi_values.get("posting_date"):
            self.posting_date = pi_values["posting_date"]
            self.set_posting_time = 1
        if self.is_new() and pi_values.get("due_date"):
            self.due_date = pi_values["due_date"]

        # ── Nro. Factura Afectada ────────────────────────────────────────────
        if pi_values.get("bill_no"):
            self.affected_invoice_number = pi_values["bill_no"]

        # ── Sucursal: heredar de la PI ────────────────────────────────────────
        if pi_values.get("branch") and not self.get("branch"):
            self.branch = pi_values["branch"]

    # ------------------------------------------------------------------ #
    # Defaults de PurchaseInvoice                                          #
    # ------------------------------------------------------------------ #

    def _init_pi_defaults(self) -> None:
        """
        Inicializa atributos de PurchaseInvoice que no existen en VE Purchase Credit Note
        para evitar AttributeError en los controladores heredados de ERPNext.
        """
        scalar_defaults: dict = {
            "is_paid": 0,
            "is_debit_note": 0,
            "is_internal_supplier": 0,
            "is_subcontracted": 0,
            "is_old_subcontracting_flow": 0,
            "update_stock": 0,
            "update_billed_amount_in_purchase_order": 0,
            "update_billed_amount_in_purchase_receipt": 0,
            "update_outstanding_for_self": 0,
            "auto_repeat": None,
            "inter_company_invoice_reference": None,
            "write_off_account": None,
            "write_off_cost_center": None,
            "write_off_amount": 0,
            "base_write_off_amount": 0,
            "paid_amount": 0,
            "base_paid_amount": 0,
            "allocate_advances_automatically": 0,
            "only_include_allocated_payments": 0,
            "ignore_default_payment_terms_template": 0,
            "payment_terms_template": None,
            "cash_bank_account": None,
            "subscription": None,
            "on_hold": 0,
            "release_date": None,
            "hold_comment": None,
            "apply_tds": 0,
            "tax_withholding_category": None,
            "due_date": None,
            "set_posting_time": 1,
        }
        for attr, val in scalar_defaults.items():
            if not hasattr(self, attr) or self.get(attr) is None:
                setattr(self, attr, val)

        # Forzar siempre estos valores críticos
        self.is_paid = 0
        self.is_debit_note = 0

        # ERPNext core usa self.customer en métodos GL cuando doctype != "Purchase Invoice"
        # (ej: make_precision_loss_gl_entry). Para la NC de compra, la contraparte es el proveedor.
        if not hasattr(self, "customer") or not self.get("customer"):
            self.customer = self.supplier

        # Tablas hijas de PurchaseInvoice eliminadas del JSON
        child_table_defaults: list[str] = [
            "pricing_rules",
            "advances",
            "payment_schedule",
            "supplied_items",
            "advance_tax",
            "tax_withheld_vouchers",
        ]
        for table in child_table_defaults:
            if not hasattr(self, table):
                setattr(self, table, [])

    # ------------------------------------------------------------------ #
    # Validaciones seguras del super()                                     #
    # ------------------------------------------------------------------ #

    def _run_super_validate_safely(self) -> None:
        """
        Parchea validate_return temporalmente para manejar el doctype
        VE Purchase Credit Note (que no es Purchase Invoice para Frappe).
        """
        import erpnext.controllers.accounts_controller as _acc_module

        _original_validate_return = _acc_module.validate_return

        def _validate_return_nc(doc):
            if doc.doctype != "VE Purchase Credit Note":
                _original_validate_return(doc)
                return

            if not doc.return_against:
                frappe.throw(
                    frappe._("Factura Afectada es obligatoria para la Nota de Crédito")
                )

            if not frappe.db.exists("Purchase Invoice", doc.return_against):
                frappe.throw(
                    frappe._("Factura Afectada no válida: {0}").format(doc.return_against)
                )

            # Validar empresa y proveedor contra la PI original
            pi = frappe.get_cached_doc("Purchase Invoice", doc.return_against)
            if pi.company != doc.company:
                frappe.throw(
                    frappe._("La empresa de la NC debe coincidir con la factura original: {0}")
                    .format(pi.company)
                )
            if pi.supplier != doc.supplier:
                frappe.throw(
                    frappe._("El proveedor de la NC debe coincidir con la factura original: {0}")
                    .format(pi.supplier)
                )

        _acc_module.validate_return = _validate_return_nc
        try:
            super().validate()
        finally:
            _acc_module.validate_return = _original_validate_return

    # ------------------------------------------------------------------ #
    # Cálculo de impuestos y totales venezolano                            #
    # ------------------------------------------------------------------ #

    def calculate_taxes_and_totals(self) -> None:
        """Usa el calculador venezolano (TaxesAndTotals) para IVA y Retenciones."""
        taxes_and_totals = TaxesAndTotals(self)
        taxes_and_totals.calculate_total_exempt()
        self.calculate_total_withholding()

    def set_taxes_and_charges(self) -> None:
        """
        Garantiza que el IVA base se cargue desde el template y luego agrega
        las retenciones venezolanas (IVA Retención e ISLR).

        Las filas ISLR se preservan porque se asignan manualmente vía diálogo.
        """
        base_tax = [
            tax for tax in self.taxes or []
            if not tax.get("is_tax_withholding_account")
        ]

        # Preservar filas ISLR existentes (asignadas manualmente)
        islr_rows = [
            tax for tax in self.taxes or []
            if tax.get("charge_type") == "ISLR"
        ]

        if not base_tax and self.get("taxes_and_charges"):
            self.set("taxes", [])
            self.append_taxes_from_master("Purchase Taxes and Charges Template")
        else:
            self.set("taxes", base_tax)

        self.set_tax_withholding_ve()
        self.set_islr_withholding_ve()

        # Re-agregar filas ISLR preservadas
        for row in islr_rows:
            self.append("taxes", row)

        for i, tax in enumerate(self.taxes or [], start=1):
            tax.idx = i

    def set_tax_withholding(self) -> None:
        """
        Desactiva el mecanismo TDS/TCS nativo de ERPNext.
        TaxesMixin.set_tax_withholding_ve() se encarga de las retenciones venezolanas.
        """
        return

    # ------------------------------------------------------------------ #
    # GL Entries — reversión contable                                      #
    # ------------------------------------------------------------------ #

    def get_gl_entries(self, warehouse_account=None):
        """
        VE Purchase Credit Note almacena montos positivos (UX).

        Usa CustomPurchaseInvoice.get_gl_entries() para el manejo correcto
        de retenciones, luego niega todos los signos para la reversión contable.
        """
        from l10n_ve.overrides.purchase_invoice import CustomPurchaseInvoice

        self._init_pi_defaults()

        gl_entries = CustomPurchaseInvoice.get_gl_entries(self, warehouse_account)

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
            # Cuando against_voucher == self.return_against (la PI original), el tipo debe ser
            # "Purchase Invoice", no "VE Purchase Credit Note".
            if (
                entry.get("against_voucher_type") == self.doctype
                and entry.get("against_voucher") == self.return_against
            ):
                entry["against_voucher_type"] = "Purchase Invoice"

        return gl_entries

    def make_supplier_gl_entry(self, gl_entries: list) -> None:
        """Delega a CustomPurchaseInvoice para incluir retenciones en el AP."""
        from l10n_ve.overrides.purchase_invoice import CustomPurchaseInvoice
        CustomPurchaseInvoice.make_supplier_gl_entry(self, gl_entries)

    def make_tax_gl_entries(self, gl_entries: list) -> None:
        """Delega a CustomPurchaseInvoice para omitir is_tax_withholding_account."""
        from l10n_ve.overrides.purchase_invoice import CustomPurchaseInvoice
        CustomPurchaseInvoice.make_tax_gl_entries(self, gl_entries)

    def make_gl_entries_for_tax_withholding(self, gl_entries: list) -> None:
        """Delega a CustomPurchaseInvoice el manejo de retenciones venezolanas."""
        from l10n_ve.overrides.purchase_invoice import CustomPurchaseInvoice
        CustomPurchaseInvoice.make_gl_entries_for_tax_withholding(self, gl_entries)

    # ------------------------------------------------------------------ #
    # Validaciones internas                                                #
    # ------------------------------------------------------------------ #

    def _enforce_positive_amounts(self) -> None:
        """Garantiza que todos los montos de ítems sean positivos y setea stock_qty."""
        for item in self.items:
            if flt(item.qty) < 0:
                item.qty = abs(item.qty)
            if flt(item.rate) < 0:
                item.rate = abs(item.rate)

            # Purchase Invoice Item tiene stock_qty como reqd=1.
            if not flt(item.conversion_factor):
                item.conversion_factor = 1.0
            item.stock_qty = flt(item.qty) * flt(item.conversion_factor)

    def _validate_unique_note_per_invoice(self) -> None:
        """Verifica que no exista otra NC activa para la misma factura original."""
        if not self.return_against:
            return

        existing: str | None = frappe.db.get_value(
            "VE Purchase Credit Note",
            {
                "return_against": self.return_against,
                "docstatus": 1,
                "name": ["!=", self.name],
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Ya existe una Nota de Crédito activa ({0}) para la factura {1}.").format(
                    existing, self.return_against
                )
            )

    def _validate_credit_note_number(self) -> None:
        """Valida que el número de NC no esté duplicado para el mismo proveedor."""
        if not self.bill_no:
            frappe.throw(
                _("El número de la Nota de Crédito es obligatorio.")
            )

        exists: str | None = frappe.db.get_value(
            "VE Purchase Credit Note",
            {
                "bill_no": self.bill_no,
                "supplier": self.supplier,
                "docstatus": ["!=", 2],
                "name": ["!=", self.name],
            },
            "name",
        )
        if exists:
            frappe.throw(
                _("Ya existe una Nota de Crédito con el número {0} para este proveedor.").format(
                    self.bill_no
                )
            )

    def _validate_bill_date(self) -> None:
        """Valida que la fecha del documento del proveedor no sea posterior a posting_date."""
        if self.bill_date and getdate(self.bill_date) > getdate(self.posting_date):
            frappe.throw(
                _("La fecha del documento del proveedor ({0}) no puede ser mayor "
                  "a la fecha de contabilización ({1}).").format(
                    frappe.format(self.bill_date, {"fieldtype": "Date"}),
                    frappe.format(self.posting_date, {"fieldtype": "Date"}),
                )
            )


# --------------------------------------------------------------------------- #
# Búsqueda personalizada para return_against                                  #
# --------------------------------------------------------------------------- #

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def query_available_purchase_invoices(
    doctype: str,
    txt: str,
    searchfield: str,
    start: int,
    page_len: int,
    filters: dict,
) -> list:
    """
    Retorna facturas de compra disponibles para aplicar una Nota de Crédito:
      - Aprobadas (docstatus = 1)
      - No son NC ni ND (is_return = 0)
      - De la misma empresa
      - Sin NC activa referenciándolas

    Exclusión mutua NC ↔ ND:
      Excluye PIs que ya tienen:
        - Una VE Purchase Credit Note activa (docstatus = 1)
        - Una Purchase Invoice de retorno (is_return = 1, docstatus = 1)
    """
    company = (filters or {}).get("company", "")

    conditions = [
        "pi.docstatus = 1",
        "pi.is_return = 0",
        "(pi.is_debit_note = 0 OR pi.is_debit_note IS NULL)",
        # Excluir PIs con NC venezolana activa
        """pi.name NOT IN (
            SELECT return_against
            FROM `tabVE Purchase Credit Note`
            WHERE docstatus = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
        # Excluir PIs con NC/ND estándar de ERPNext activa
        """pi.name NOT IN (
            SELECT return_against
            FROM `tabPurchase Invoice`
            WHERE docstatus = 1
              AND is_return = 1
              AND return_against IS NOT NULL
              AND return_against != ''
        )""",
    ]
    values: dict = {}

    if company:
        conditions.append("pi.company = %(company)s")
        values["company"] = company

    supplier = (filters or {}).get("supplier", "")
    if supplier:
        conditions.append("pi.supplier = %(supplier)s")
        values["supplier"] = supplier

    if txt:
        conditions.append(
            "(pi.name LIKE %(txt)s"
            " OR pi.supplier LIKE %(txt)s"
            " OR pi.supplier_name LIKE %(txt)s"
            " OR pi.bill_no LIKE %(txt)s"
            " OR pi.bill_control LIKE %(txt)s)"
        )
        values["txt"] = f"%{txt}%"

    where = " AND ".join(conditions)
    values["start"] = int(start)
    values["page_len"] = int(page_len)

    return frappe.db.sql(
        f"""
        SELECT
            pi.name,
            CONCAT(COALESCE(pi.bill_no, ''), ' — ', pi.supplier_name) AS label,
            pi.posting_date,
            pi.grand_total
        FROM `tabPurchase Invoice` pi
        WHERE {where}
        ORDER BY pi.posting_date DESC
        LIMIT %(start)s, %(page_len)s
        """,
        values,
    )
