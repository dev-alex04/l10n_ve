# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher


class VATWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self):
        self.validate_address()
        self.validate_fiscal_period()
        self.validate_unique_voucher_number()
        if self.is_new() and self.amended_from:
            self._populate_withholding_rate()
        self.validate_withholding_amount()

    def validate_unique_voucher_number(self) -> None:
        """Valida que el número de comprobante no esté duplicado."""
        if not self.voucher_number:
            return

        duplicate: str | None = frappe.db.get_value(
            "VAT Withholding Voucher",
            {
                "voucher_number": self.voucher_number,
                "name": ["!=", self.name],
                "docstatus": ["!=", 2],
            },
        )
        if duplicate:
            frappe.throw(
                _("Ya existe un comprobante de retención IVA con el número {0}: {1}").format(
                    frappe.bold(self.voucher_number), frappe.bold(duplicate)
                )
            )

    def _populate_withholding_rate(self) -> None:
        """Pobla withholding_rate desde la factura de compra si está vacío.

        Solo se ejecuta en documentos enmendados para corregir datos
        copiados del comprobante original.
        """
        items_to_fix: list = [
            item for item in self.get("vat_withholding_voucher_item", [])
            if item.purchase_invoice and not flt(item.withholding_rate)
        ]
        if not items_to_fix:
            return

        invoice_names: list[str] = list({item.purchase_invoice for item in items_to_fix})
        rates: list[dict] = frappe.get_all(
            "Purchase Taxes and Charges",
            filters={
                "parenttype": "Purchase Invoice",
                "parent": ["in", invoice_names],
                "charge_type": "VAT Withholding",
            },
            fields=["parent", "rate"],
        )
        rate_map: dict[str, float] = {r.parent: abs(r.rate) for r in rates}

        for item in items_to_fix:
            rate_value: float = rate_map.get(item.purchase_invoice, 0)
            if rate_value:
                item.withholding_rate = rate_value

    def before_cancel(self) -> None:
        """Bloquea la cancelación si el comprobante ya fue emitido a HKA.

        Excepción: permite cancelar si la anulación en HKA ya fue confirmada
        (flag frappe.flags.hka_void_confirmed establecido por void_retention_voucher).
        """
        if frappe.flags.get("hka_void_confirmed"):
            return

        if self.digital_invoice_status == "Sent":
            frappe.throw(
                _("No se puede cancelar el comprobante {0} porque ya fue emitido "
                  "a la imprenta fiscal digital (TFHKA). Use el botón "
                  "\"Anular Comprobante\" para anularlo primero en HKA.").format(self.name)
            )


    def before_insert(self):
        company_doc = frappe.get_cached_doc("Company", self.empresa)
        correlative_format = company_doc.vat_withholding_format

        final_voucher_number, final_next_correlative_number, year, month = \
            self._get_and_format_correlatives(correlative_format, company_doc.vat_withholding_correlative)

        self.voucher_number = final_voucher_number
        self.fiscal_period = f"{month}/{year}"

        company_doc.vat_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

    def on_trash(self):
        document_date = self.issue_date
        current_date = getdate(nowdate())

        if document_date:
            document_month_year = getdate(document_date).strftime('%Y-%m')
            current_month_year = current_date.strftime('%Y-%m')
        else:
            frappe.throw(
                _("No se puede determinar la fecha del comprobante para la validación.")
            )

        if document_month_year != current_month_year:
            frappe.throw(
                _("No se puede eliminar el comprobante. Solo se permiten "
                  "eliminaciones para el periodo actual ({0}).").format(current_month_year)
            )


    def validate_fiscal_period(self) -> None:
        if not self.fiscal_period:
            return

        parts: list[str] = self.fiscal_period.split('/')

        is_invalid_format: bool = (
            len(parts) != 2
            or not parts[0].isdigit()
            or not parts[1].isdigit()
            or len(parts[0]) != 2
            or len(parts[1]) != 4
        )

        if is_invalid_format:
            frappe.throw(_("El Periodo Fiscal debe tener el formato MM/YYYY (ej: 10/2025)."))

        if not (1 <= int(parts[0]) <= 12):
            frappe.throw(_("El mes en el Periodo Fiscal no es válido."))

    def validate_withholding_amount(self) -> None:
        """Impide aprobar un comprobante cuando no hay IVA a retener."""

        total_vat: float = flt(self.totals_tax_amount_vat)
        if not total_vat:
            frappe.throw(
                _("No se puede procesar este comprobante porque el monto total de IVA retenido es 0. "
                  "Verifique que las facturas incluidas tengan IVA gravable.")
            )

@frappe.whitelist()
def get_valid_invoices(supplier: str, start_date: str, end_date: str, company: str) -> list[dict]:
    """Obtiene facturas de compra válidas para incluir en un comprobante de retención de IVA.

    Criterios de inclusión:
    - Factura aprobada (docstatus=1) del proveedor y rango de fechas indicado
    - Que tenga una fila de impuesto tipo 'VAT Withholding' con monto > 0
    - Que no esté ya incluida en otro comprobante (no cancelado)
    """

    # Fase 1: Obtener facturas ya asignadas a comprobantes vigentes
    excluded_from_withholding: list[dict] = frappe.db.sql("""
        SELECT
            child.purchase_invoice
        FROM
            `tabVAT Withholding Voucher Item` child
        INNER JOIN
            `tabVAT Withholding Voucher` parent ON child.parent = parent.name
        WHERE
            parent.docstatus = 1
            AND parent.empresa = %(company)s
            AND child.purchase_invoice IS NOT NULL
            AND child.purchase_invoice != ''
    """, {"company": company}, as_dict=True)

    all_excluded_invoices: list[str] = [d.purchase_invoice for d in excluded_from_withholding]

    # Fase 2: Obtener facturas candidatas (sin JOIN implícito a child table)
    invoice_filters: dict = {
        "supplier": supplier,
        "posting_date": ["between", [start_date, end_date]],
        "company": company,
        "docstatus": 1,
    }
    if all_excluded_invoices:
        invoice_filters["name"] = ["not in", all_excluded_invoices]

    valid_invoice_names: list[dict] = frappe.get_all(
        "Purchase Invoice",
        filters=invoice_filters,
        fields=["name"],
        pluck="name"
    )

    if not valid_invoice_names:
        return []

    # Fase 3: Obtener datos de retención (VAT Withholding) con monto > 0
    withholding_data: list[dict] = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parenttype": "Purchase Invoice",
            "parent": ["in", valid_invoice_names],
            "charge_type": "VAT Withholding",
            "base_tax_amount": ["!=", 0],
        },
        fields=["parent", "rate as withholding_rate", "base_tax_amount"],
    )

    if not withholding_data:
        return []

    # Solo facturas que realmente tienen retención > 0
    invoices_with_withholding: set[str] = {d.parent for d in withholding_data}
    withholding_map: dict[str, dict] = {d.parent: d for d in withholding_data}

    # Fase 4: Obtener datos de IVA (VAT) para la tasa aplicada
    vat_data: list[dict] = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parenttype": "Purchase Invoice",
            "parent": ["in", list(invoices_with_withholding)],
            "charge_type": "VAT",
        },
        fields=["parent", "rate", "base_tax_amount"],
    )

    vat_map: dict[str, dict] = {}
    for d in vat_data:
        if d.parent not in vat_map:
            vat_map[d.parent] = {"rate": d.rate, "base_tax_amount": d.base_tax_amount}
        else:
            vat_map[d.parent]["base_tax_amount"] += d.base_tax_amount

    # Fase 5: Obtener datos completos de las facturas filtradas
    invoices: list[dict] = frappe.get_all(
        "Purchase Invoice",
        filters={"name": ["in", list(invoices_with_withholding)]},
        fields=[
            "name", "bill_no", "bill_control", "posting_date",
            "base_grand_total", "base_total", "total_exempt",
            "base_taxes_and_charges_added", "conversion_rate", "currency",
            "is_return", "is_debit_note",
            "credit_note_no", "debit_note_no", "affected_invoice_number",
        ]
    )

    default_currency: str = frappe.db.get_value("Company", company, "default_currency") or ""

    invoices_with_taxes: list[dict] = []
    for inv in invoices:
        vat_details: dict = vat_map.get(inv.name, {})
        wh_details: dict = withholding_map.get(inv.name, {})

        # total_exempt no tiene campo base_*, requiere conversión manual
        rate: float = inv.conversion_rate if (default_currency != inv.currency and inv.conversion_rate) else 1
        total_exempt: float = (inv.total_exempt or 0) * rate

        invoice_data: dict = {
            "purchase_invoice": inv.name,
            "bill_no": inv.bill_no,
            "bill_control": inv.bill_control,
            "posting_date": inv.posting_date,
            "grand_total": abs(inv.base_grand_total or 0),
            "total": abs(inv.base_total or 0),
            "total_exempt": abs(total_exempt),
            "taxes_and_charges_added": abs(vat_details.get("base_tax_amount", 0)),
            "credit_note_no": inv.credit_note_no,
            "debit_note_no": inv.debit_note_no,
            "affected_invoice_number": inv.affected_invoice_number,
            "is_return": inv.is_return,
            "is_debit_note": inv.is_debit_note,
            "rate": vat_details.get("rate", 0),
            "withholding_rate": abs(wh_details.get("withholding_rate", 0)),
            "tax_amount_vat": abs(wh_details.get("base_tax_amount", 0)),
        }
        invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes