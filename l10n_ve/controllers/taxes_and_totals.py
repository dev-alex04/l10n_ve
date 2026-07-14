import json
from typing import Optional

import frappe
import erpnext
from frappe.utils import cint, flt

from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals


TAX_FROM_TOTAL = "Desde el total de la factura"

__VE_DOCTYPES__ = [
    "Quotation",
    "Sales Order",
    "Sales Invoice",
    "Delivery Note",
    "VE Sales Credit Note",
    "VE Sales Debit Note",
    "Purchase Order",
    "Purchase Invoice",
    "Purchase Receipt",
    "VE Purchase Credit Note",
    "VE Purchase Debit Note",
]


def anchor_base_from_total(base_usd, vat_factor, rate, amount_precision=2, base_precision=2):
    """Ancla el carril Bs "Desde el total de la factura" para un monto base.

    Reconstruye el total comercial redondeado (base x (1+IVA)) a la precisión de
    la moneda, lo lleva a Bs a la ``rate`` dada y deriva la base Bs hacia atrás
    (total / (1+IVA)). Devuelve ``(base_bs, total_bs)``.

    Primitiva PURA y ÚNICA del anclaje: la comparten el motor (por ítem, a la
    tasa de la factura) y el portal de clientes (agregado, a la tasa del día)
    para que ambos calculen idéntico y no re-divergir el número.
    """
    total_usd = flt(base_usd * vat_factor, amount_precision)
    total_bs = flt(total_usd * rate, base_precision)
    base_bs = flt(total_bs / vat_factor, base_precision) if vat_factor else total_bs
    return base_bs, total_bs


def compute_bs_tax_amounts(net_total_ref, iva_factor, rate, method):
    """Deriva el carril Bs (subtotal, IVA, total) a una ``rate`` dada, según el
    Método de cálculo de Impuestos (Venezuela Account Settings).

    Pensado para consumidores que trabajan a nivel agregado (p. ej. el portal de
    clientes, que re-valora a la tasa del día): mismo criterio que el motor pero
    sin recorrer ítems.

    - ``net_total_ref``: base imponible en moneda de referencia (USD).
    - ``iva_factor``: fracción de IVA del documento (ej. 0,16).
    - "Desde el total de la factura": ancla al total (misma primitiva que el
      motor, :func:`anchor_base_from_total`) y el IVA sale por diferencia.
    - Cualquier otro valor ("Desde la base imponible" o vacío): base Bs = base
      USD x tasa; el IVA emerge (comportamiento histórico, sin cambios).

    Nota: a nivel agregado coincide con el motor por construcción cuando hay una
    sola línea gravada y difiere a lo sumo en céntimos con varias; el cobro se
    valida en USD, así que ese residuo no afecta el pago.
    """
    net_total_ref = flt(net_total_ref)
    iva_factor = flt(iva_factor)
    if method == TAX_FROM_TOTAL and iva_factor:
        subtotal_bs, gross_total_bs = anchor_base_from_total(
            net_total_ref, 1 + iva_factor, rate
        )
        iva_bs = flt(gross_total_bs - subtotal_bs, 2)
    else:
        subtotal_bs = flt(net_total_ref * rate, 2)
        iva_bs = flt(subtotal_bs * iva_factor, 2)
        gross_total_bs = flt(subtotal_bs + iva_bs, 2)
    return {
        "subtotal_bs": subtotal_bs,
        "iva_bs": iva_bs,
        "gross_total_bs": gross_total_bs,
    }


class TaxesAndTotals(calculate_taxes_and_totals):

    def __init__(self, doc) -> None:
        super().__init__(doc)

    def calculate(self) -> None:
        """
        ERPNext core solo llama calculate_total_advance() (que a su vez
        calcula outstanding) para 'Sales Invoice' y 'Purchase Invoice'.
        Se extiende para que los doctypes venezolanos también lo ejecuten.
        """
        self._validate_tax_method_configured()
        super().calculate()

        ve_invoice_doctypes: list = [
            "VE Sales Debit Note",
        ]
        if self.doc.doctype in ve_invoice_doctypes:
            self.calculate_total_advance()

    def _validate_tax_method_configured(self) -> None:
        """Bloquea el cálculo de documentos con impuestos sin método definido.

        El "Método de cálculo de Impuestos" (Venezuela Account Settings) no tiene
        valor por defecto a propósito: cada site debe elegirlo de forma
        consciente, porque define qué extremo del precio es el ancla (base
        imponible vs total con IVA) y con qué convención se cargan los
        precios. Sin esa decisión tomada, calcular sería adivinar.
        """
        taxes = self.doc.get("taxes") or []
        if not any(tax.charge_type in ("VAT", "On Net Total") for tax in taxes):
            return

        method = frappe.get_cached_value(
            "Venezuela Account Settings", "Venezuela Account Settings",
            "tax_calculation_method",
        )
        if not method:
            frappe.throw(
                frappe._(
                    "No está definido el <b>Método de cálculo de Impuestos</b>. "
                    "Configúrelo en <b>Venezuela Account Settings</b> "
                    "(Desde la base imponible / Desde el total de la factura) "
                    "antes de calcular documentos con impuestos."
                ),
                title=frappe._("Método de cálculo de Impuestos requerido"),
            )

    def _is_multicurrency(self) -> bool:
        """Indica si el documento usa moneda diferente a la de la compañía."""
        company_currency: str = erpnext.get_company_currency(self.doc.company)
        return self.doc.currency != company_currency

    def _get_return_parent_doc(self) -> Optional[object]:
        """Retorna el documento de la factura original asociada al retorno actual,
        registrando cualquier error en el log de Frappe.
        """
        if not (self.doc.get("return_against") and self.doc.get("is_return")):
            return None

        affected_doctype: str = "Sales Invoice" if self.doc.doctype in ("VE Sales Credit Note", "VE Sales Debit Note") else "Purchase Invoice"
        try:
            return frappe.get_cached_doc(affected_doctype, self.doc.return_against)
        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error en TaxesAndTotals al obtener return_against para {self.doc.name}"
            )
            return None

    def _get_tax_calculation_method(self) -> str:
        """Método de cálculo de impuestos elegido en Venezuela Account Settings."""
        return frappe.get_cached_value(
            "Venezuela Account Settings", "Venezuela Account Settings",
            "tax_calculation_method",
        ) or ""

    def calculate_net_total(self) -> None:
        """Re-ancla los montos base (VEF) por ítem ANTES de que el core los
        sume (base_net_total) y de que la metodología VE derive de ellos el
        IVA, los acumulados y el base_grand_total."""
        self._anchor_item_base_amounts_ve()
        super().calculate_net_total()

    def _anchor_item_base_amounts_ve(self) -> None:
        """Método "Desde el total de la factura": ancla el carril Bs al total
        comercial redondeado.

        Si es un retorno (Nota de Crédito/Débito) con factura de origen,
        se heredan y escalan proporcionalmente los montos base de los ítems
        originales para asegurar consistencia matemática absoluta.
        """
        self._ve_anchored_taxable_total_bs = None

        parent_doc = self._get_return_parent_doc()
        if parent_doc:
                parent_items = {item.name: item for item in parent_doc.items}
                parent_items_by_code: dict[str, list] = {}
                for item in parent_doc.items:
                    parent_items_by_code.setdefault(item.item_code, []).append(item)

                for item in self.doc.items:
                    ref_item = None
                    if item.get("sales_invoice_item") and item.sales_invoice_item in parent_items:
                        ref_item = parent_items[item.sales_invoice_item]
                    else:
                        code: str = item.item_code
                        if code in parent_items_by_code and parent_items_by_code[code]:
                            ref_item = parent_items_by_code[code].pop(0)

                    if ref_item:
                        qty: float = flt(item.qty)
                        amount_ratio: float = flt(item.net_amount) / flt(ref_item.net_amount) if flt(ref_item.net_amount) else 0.0
                        item.base_net_amount = flt(ref_item.base_net_amount * amount_ratio, item.precision("base_net_amount"))
                        item.base_amount = flt(ref_item.base_amount * amount_ratio, item.precision("base_amount"))
                        item.base_net_rate = flt(item.base_net_amount / qty, item.precision("base_net_rate")) if qty else 0.0
                        item.base_rate = flt(item.base_amount / qty, item.precision("base_rate")) if qty else 0.0

                        rate_ratio: float = flt(item.price_list_rate) / flt(ref_item.price_list_rate) if flt(ref_item.price_list_rate) else 0.0
                        item.base_price_list_rate = flt(ref_item.base_price_list_rate * rate_ratio, item.precision("base_price_list_rate"))
                return

        if not self._is_multicurrency():
            return

        if self._get_tax_calculation_method() != TAX_FROM_TOTAL:
            return

        conversion_rate: float = flt(self.doc.conversion_rate)
        if not conversion_rate:
            return

        # Tasa de IVA efectiva del documento (filas VAT aditivas, no retención)
        vat_rate: float = sum(
            flt(tax.rate)
            for tax in self.doc.get("taxes") or []
            if tax.charge_type == "VAT"
            and not tax.get("is_tax_withholding_account")
            and getattr(tax, "add_deduct_tax", "Add") != "Deduct"
            and getattr(tax, "category", "Total") != "Valuation"
        )
        if not vat_rate:
            return

        factor: float = 1 + (vat_rate / 100.0)
        anchored_total_bs: float = 0.0

        for item in self.doc.get("items") or []:
            if item.get("vat_exempt"):
                continue

            for src_field, base_field, base_rate_field in (
                ("amount", "base_amount", "base_rate"),
                ("net_amount", "base_net_amount", "base_net_rate"),
            ):
                amount_usd: float = flt(item.get(src_field))
                # Total comercial del ítem, redondeado a la precisión de la
                # moneda del documento (25,86 x 1,16 = 29,9976 -> 30,00) -> Bs ->
                # base derivada hacia atrás. Primitiva compartida con el portal
                # (compute_bs_tax_amounts) para no re-divergir el cálculo.
                base_value, total_bs = anchor_base_from_total(
                    amount_usd, factor, conversion_rate,
                    item.precision(src_field), item.precision(base_field),
                )
                setattr(item, base_field, base_value)
                if item.qty:
                    setattr(item, base_rate_field, flt(
                        base_value / item.qty,
                        item.precision(base_rate_field),
                    ))
                if base_field == "base_net_amount":
                    anchored_total_bs += total_bs

        self._ve_anchored_taxable_total_bs = flt(anchored_total_bs, 2)

    def calculate_total_exempt(self) -> None:

        total_exempt = 0
        base_total_exempt = 0
        for item in self.doc.items:
            if item.vat_exempt:
                total_exempt += flt(item.net_amount)
                base_total_exempt += flt(item.base_net_amount)

        self.doc.total_exempt = total_exempt
        # base_* (VEF) como fuente de verdad: se suma el base_net_amount por línea
        # (misma base y redondeo per-ítem que usa ERPNext para base_net_total), de
        # modo que base_net_total - base_total_exempt no arrastre céntimos.
        self.doc.base_total_exempt = flt(base_total_exempt, 2)

    def get_current_tax_amount(self, item, tax, item_tax_map) -> float:

        tax_rate = self._get_tax_rate(tax, item_tax_map)
        current_tax_amount = 0.0

        if tax.charge_type == "Actual":
            # distribute the tax amount proportionally to each item row
            actual = flt(tax.tax_amount, tax.precision("tax_amount"))

            if tax.get("is_tax_withholding_account") and item.meta.get_field("apply_tds"):
                if not item.get("apply_tds") or not self.doc.tax_withholding_net_total:
                    current_tax_amount = 0.0
                else:
                    current_tax_amount = item.net_amount * actual / self.doc.tax_withholding_net_total
            else:
                current_tax_amount = (
                    item.net_amount * actual / self.doc.net_total if self.doc.net_total else 0.0
                )

        elif tax.charge_type == "On Net Total":
            if item.idx == 1:
                taxable_base = 0
                for doc_item in self.doc.items:
                    if not doc_item.vat_exempt:
                        taxable_base += doc_item.net_amount
                current_tax_amount = (tax_rate / 100.0) * taxable_base
            else:
                current_tax_amount = 0

        elif tax.charge_type == "On Previous Row Amount":
            current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
                cint(tax.row_id) - 1
            ].tax_amount_for_current_item

        elif tax.charge_type == "On Previous Row Total":
            current_tax_amount = (tax_rate / 100.0) * self.doc.get("taxes")[
                cint(tax.row_id) - 1
            ].grand_total_for_current_item

        elif tax.charge_type == "On Item Quantity":
            current_tax_amount = tax_rate * item.qty

        elif tax.charge_type == "ISLR":

            if item.idx == 1:
                tax_base = (self.doc.total * flt(tax.percentage_base)) / 100
                tax_amount = ((tax_base * tax.rate) / 100) - flt(tax.subtracting)
            else:
                tax_amount = 0

            current_tax_amount = tax_amount if tax_amount > 0 else 0

        elif tax.charge_type == "VAT" and not item.vat_exempt:
            current_tax_amount = (item.net_amount * tax.rate) / 100

        elif tax.charge_type == "VAT Withholding" and not item.vat_exempt:

            for tax_row in self.doc.get("taxes") or []:

                if tax_row.charge_type == "VAT":

                    vat = (item.net_amount * tax_row.rate) / 100
                    current_tax_amount = (vat * tax.rate) / 100
                    break

        if not (self.doc.get("is_consolidated") or tax.get("dont_recompute_tax")):
            self.set_item_wise_tax(item, tax, tax_rate, current_tax_amount)

        class IterableFloat(float):
            def __iter__(self):
                val = float(self)
                yield val
                yield val

        return IterableFloat(current_tax_amount)

    # ------------------------------------------------------------------ #
    # Recálculo de montos base (VEF) — Metodología fiscal venezolana
    # ------------------------------------------------------------------ #

    def calculate_taxes(self) -> None:
        """
        Ejecuta el cálculo estándar de ERPNext y luego recalcula
        los montos base (VEF) usando la metodología fiscal venezolana:
        primero se convierte la base a moneda local y después se calcula
        el impuesto, en vez de calcular en USD y luego convertir.
        """
        super().calculate_taxes()
        self._recalculate_base_tax_amounts_ve()

    def _recalculate_base_tax_amounts_ve(self) -> None:
        """
        Recalcula base_tax_amount para cada impuesto calculando
        directamente sobre la base en moneda local (VEF), eliminando
        discrepancias de redondeo amplificadas por tasas de cambio altas.
        """
        if not self._is_multicurrency():
            return

        if not self.doc.get("taxes"):
            return

        conversion_rate: float = flt(self.doc.conversion_rate)
        if not conversion_rate:
            return

        base_taxable_vef: float = sum(
            flt(item.base_net_amount)
            for item in self.doc.items
            if not item.get("vat_exempt")
        )



        # Método "Desde el total": el IVA Bs se define por DIFERENCIA contra
        # el total gravado anclado (base + IVA == total comercial x tasa,
        # siempre). Recalcularlo como 16% de la base redondeada puede
        # desviar ±0,01 por el viaje de redondeos.
        anchored_total_bs = getattr(self, "_ve_anchored_taxable_total_bs", None)
        anchored_iva_pending = None
        anchored_vat_rows: list = []
        if anchored_total_bs is not None:
            anchored_vat_rows = [
                t for t in self.doc.get("taxes")
                if t.charge_type == "VAT" and not t.get("is_tax_withholding_account")
            ]
            if anchored_vat_rows:
                anchored_iva_pending = flt(anchored_total_bs - base_taxable_vef, 2)

        for i, tax in enumerate(self.doc.get("taxes")):

            if tax.charge_type == "VAT" and not tax.get("is_tax_withholding_account"):
                if anchored_iva_pending is not None:
                    if tax is anchored_vat_rows[-1]:
                        # la última fila absorbe el remanente del redondeo
                        share = anchored_iva_pending
                    else:
                        total_rate = sum(flt(t.rate) for t in anchored_vat_rows) or 1
                        share = flt(
                            anchored_iva_pending * flt(tax.rate) / total_rate,
                            tax.precision("base_tax_amount"),
                        )
                    anchored_iva_pending = flt(anchored_iva_pending - share, 2)
                    tax.base_tax_amount = flt(share, tax.precision("base_tax_amount"))
                else:
                    tax.base_tax_amount = flt(
                        base_taxable_vef * flt(tax.rate) / 100,
                        tax.precision("base_tax_amount")
                    )

            elif tax.charge_type == "On Net Total":
                tax.base_tax_amount = flt(
                    base_taxable_vef * flt(tax.rate) / 100,
                    tax.precision("base_tax_amount")
                )

            elif tax.charge_type == "VAT Withholding":
                total_vat_base: float = sum(
                    flt(t.base_tax_amount)
                    for t in self.doc.get("taxes")
                    if t.charge_type == "VAT"
                )
                tax.base_tax_amount = flt(
                    total_vat_base * flt(tax.rate) / 100,
                    tax.precision("base_tax_amount")
                )

            elif tax.charge_type == "ISLR":
                base_islr_base: float = flt(self.doc.base_total) * flt(tax.percentage_base) / 100
                base_islr: float = (
                    (base_islr_base * flt(tax.rate) / 100)
                    - flt(tax.subtracting)
                )
                tax.base_tax_amount = flt(
                    max(base_islr, 0),
                    tax.precision("base_tax_amount")
                )

            elif tax.charge_type == "On Previous Row Amount":
                prev_idx: int = cint(tax.row_id) - 1
                if 0 <= prev_idx < len(self.doc.get("taxes")):
                    prev_tax = self.doc.get("taxes")[prev_idx]
                    tax.base_tax_amount = flt(
                        prev_tax.base_tax_amount * flt(tax.rate) / 100,
                        tax.precision("base_tax_amount")
                    )

            elif tax.charge_type == "On Previous Row Total":
                prev_idx = cint(tax.row_id) - 1
                if 0 <= prev_idx < len(self.doc.get("taxes")):
                    prev_tax = self.doc.get("taxes")[prev_idx]
                    tax.base_tax_amount = flt(
                        prev_tax.base_total * flt(tax.rate) / 100,
                        tax.precision("base_tax_amount")
                    )

            # Actualizar monto after discount proporcionalmente
            if flt(tax.tax_amount) and flt(tax.tax_amount) != flt(tax.tax_amount_after_discount_amount):
                discount_ratio: float = (
                    flt(tax.tax_amount_after_discount_amount) / flt(tax.tax_amount)
                )
                tax.base_tax_amount_after_discount_amount = flt(
                    tax.base_tax_amount * discount_ratio,
                    tax.precision("base_tax_amount_after_discount_amount")
                )
            else:
                tax.base_tax_amount_after_discount_amount = tax.base_tax_amount

            # Recalcular base_total acumulado (misma lógica que set_cumulative_total)
            if i == 0:
                base_tax_base = flt(self.doc.base_net_total)
            else:
                base_tax_base = self.doc.get("taxes")[i - 1].base_total

            base_tax_for_total: float = tax.base_tax_amount_after_discount_amount
            base_tax_for_total = self._get_base_tax_for_cumulative_ve(
                base_tax_for_total, tax
            )

            if tax.is_tax_withholding_account:
                if tax.charge_type in ("VAT Withholding", "ISLR") \
                        and self.doc.doctype in __VE_DOCTYPES__:
                    tax.base_total = flt(
                        base_tax_base + base_tax_for_total,
                        tax.precision("base_total")
                    )
                else:
                    tax.base_total = base_tax_base
            else:
                tax.base_total = flt(
                    base_tax_base + base_tax_for_total,
                    tax.precision("base_total")
                )

            self._recalculate_item_wise_tax_detail_ve(tax, base_taxable_vef)

    def _get_base_tax_for_cumulative_ve(
        self, base_tax_amount: float, tax
    ) -> float:
        """
        Aplica la misma lógica de valuación/deducción que ERPNext
        pero sobre los montos base recalculados.
        """
        if hasattr(tax, "category") and tax.category == "Valuation":
            return 0

        if hasattr(tax, "add_deduct_tax") and tax.add_deduct_tax == "Deduct":
            return abs(base_tax_amount) * -1

        return base_tax_amount

    def _recalculate_item_wise_tax_detail_ve(
        self, tax, base_taxable_vef: float
    ) -> None:
        """Recalcula item_wise_tax_detail usando montos base VEF."""
        if isinstance(tax.item_wise_tax_detail, str):
            try:
                tax.item_wise_tax_detail = json.loads(tax.item_wise_tax_detail)
            except (json.JSONDecodeError, TypeError):
                return

        if not isinstance(tax.item_wise_tax_detail, dict):
            return

        if tax.charge_type == "VAT":
            item_base_by_key: dict[str, float] = {}
            for item in self.doc.items:
                if item.get("vat_exempt"):
                    continue
                key: str = item.item_code or item.item_name
                item_base_by_key[key] = (
                    item_base_by_key.get(key, 0) + flt(item.base_net_amount)
                )

            for key, rate_info in tax.item_wise_tax_detail.items():
                if not isinstance(rate_info, list) or len(rate_info) < 2:
                    continue
                base_amount: float = item_base_by_key.get(key, 0)
                rate_info[1] = flt(base_amount * flt(rate_info[0]) / 100)

        elif tax.charge_type == "On Net Total":
            assigned: bool = False
            for key, rate_info in tax.item_wise_tax_detail.items():
                if not isinstance(rate_info, list) or len(rate_info) < 2:
                    continue
                if not assigned:
                    rate_info[1] = flt(base_taxable_vef * flt(rate_info[0]) / 100)
                    assigned = True
                else:
                    rate_info[1] = 0

    # ------------------------------------------------------------------ #
    # calculate_totals — Recálculo de base_grand_total VE
    # ------------------------------------------------------------------ #

    def calculate_totals(self) -> None:
        """
        Override que mantiene el redirect de VE Sales Credit Note y
        VE Sales Debit Note. Luego recalcula base_grand_total usando
        los componentes VEF recalculados con la metodología fiscal venezolana.
        """
        es_doc_ve: bool = self.doc.doctype in (
            "VE Sales Credit Note", "VE Sales Debit Note"
        )
        original_doctype: str = self.doc.doctype

        if es_doc_ve:
            self.doc.doctype = "Sales Invoice"
            for tax in self.doc.get("taxes", []):
                if not hasattr(tax, "category") or not tax.category:
                    tax.category = "Total"

        try:
            super().calculate_totals()
        finally:
            if es_doc_ve:
                self.doc.doctype = original_doctype

        if not self._is_multicurrency():
            return

        if self.doc.get("taxes"):
            last_tax = self.doc.get("taxes")[-1]
            self.doc.base_grand_total = flt(
                last_tax.base_total,
                self.doc.precision("base_grand_total")
            )

        self.doc.base_total_taxes_and_charges = flt(
            self.doc.base_grand_total - self.doc.base_net_total,
            self.doc.precision("base_total_taxes_and_charges")
        )

        if self.doc.meta.get_field("rounded_total"):
            self.doc.base_rounded_total = flt(
                self.doc.base_grand_total,
                self.doc.precision("base_rounded_total")
            )
            self.doc.base_rounding_adjustment = 0

    # ------------------------------------------------------------------ #
    # set_cumulative_total — Override existente (sin cambios)
    # ------------------------------------------------------------------ #

    def set_cumulative_total(self, row_idx, tax) -> None:
        tax_amount = tax.tax_amount_after_discount_amount
        tax_amount = self.get_tax_amount_if_for_valuation_or_deduction(tax_amount, tax)

        if row_idx == 0:
            tax_base = self.doc.net_total
        else:
            tax_base = self.doc.get("taxes")[row_idx - 1].total

        if tax.is_tax_withholding_account:

            # Se resta la retención de IVA e ISLR
            if tax.charge_type in ("VAT Withholding", "ISLR") \
                    and self.doc.doctype in __VE_DOCTYPES__:

                # Se asegura que la retención siempre reste, independientemente de su signo original
                tax.total = flt(tax_base - abs(tax_amount), tax.precision("total"))

            else:
                tax.total = tax_base
        else:
            tax.total = flt(tax_base + tax_amount, tax.precision("total"))

    # ------------------------------------------------------------------ #
    # calculate_total_advance — Override para evitar errores de redondeo
    # ------------------------------------------------------------------ #

    def calculate_total_advance(self) -> None:
        """
        Sobrescribe la validación de anticipos de ERPNext.
        En escenarios multimoneda (USD/VEF), ERPNext valida que el anticipo
        no exceda grand_total * conversion_rate. Sin embargo, en VE el total
        en VEF (base_grand_total) puede ser ligeramente superior debido al
        cálculo de impuestos sobre la base convertida.
        """
        if self.doc.docstatus != 2:
            total_allocated_amount = sum(
                flt(adv.allocated_amount, adv.precision("allocated_amount"))
                for adv in self.doc.get("advances")
            )

            self.doc.total_advance = flt(
                total_allocated_amount, self.doc.precision("total_advance")
            )

            grand_total = self.doc.rounded_total or self.doc.grand_total

            if self.doc.party_account_currency == self.doc.currency:
                invoice_total = flt(
                    grand_total - flt(self.doc.write_off_amount),
                    self.doc.precision("grand_total"),
                )
            else:
                base_write_off_amount = flt(
                    flt(self.doc.write_off_amount) * self.doc.conversion_rate,
                    self.doc.precision("base_write_off_amount"),
                )

                if self.doc.base_rounded_total:
                    invoice_total = self.doc.base_rounded_total - base_write_off_amount
                elif self.doc.base_grand_total:
                    invoice_total = self.doc.base_grand_total - base_write_off_amount
                else:
                    invoice_total = (
                        flt(
                            grand_total * self.doc.conversion_rate,
                            self.doc.precision("base_grand_total"),
                        )
                        - base_write_off_amount
                    )

            if invoice_total > 0 and self.doc.total_advance > invoice_total:
                if flt(self.doc.total_advance - invoice_total) > 0.01:
                    from frappe import _
                    frappe.throw(
                        _("Advance amount cannot be greater than {0} {1}").format(
                            self.doc.party_account_currency, invoice_total
                        )
                    )

        if self.doc.get("write_off_outstanding_amount_automatically"):
            self.doc.write_off_amount = 0

        self.calculate_outstanding_amount()
        self.calculate_write_off_amount()

    def calculate_outstanding_amount(self) -> None:
        """
        ERPNext core (taxes_and_totals.py:875) solo calcula outstanding para
        'Sales Invoice' y 'Purchase Invoice'. La ND venezolana no entra.
        Se extiende la condición para incluirla.
        """
        ve_invoice_doctypes: list = [
            "VE Sales Debit Note",
        ]

        if self.doc.doctype not in ve_invoice_doctypes:
            return super().calculate_outstanding_amount()

        grand_total = self.doc.rounded_total or self.doc.grand_total
        base_grand_total = self.doc.base_rounded_total or self.doc.base_grand_total

        self.doc.round_floats_in(
            self.doc, ["grand_total", "total_advance", "write_off_amount"]
        )

        if self.doc.party_account_currency == self.doc.currency:
            total_amount_to_pay = flt(
                grand_total - flt(self.doc.total_advance),
                self.doc.precision("grand_total"),
            )
        else:
            total_amount_to_pay = flt(
                flt(base_grand_total, self.doc.precision("base_grand_total"))
                - flt(self.doc.total_advance),
                self.doc.precision("base_grand_total"),
            )

        self.doc.outstanding_amount = flt(
            total_amount_to_pay,
            self.doc.precision("outstanding_amount"),
        )
