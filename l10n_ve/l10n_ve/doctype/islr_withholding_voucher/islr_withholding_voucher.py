# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher
from l10n_ve.utils.utils import format_amounts


class ISLRWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self) -> None:
        self.validate_address()
        self.validate_unique_voucher_number()
        self.validate_withholding_amount()

    def before_cancel(self) -> None:
        """Bloquea la cancelación si el comprobante ya fue emitido a HKA."""
        if frappe.flags.get("hka_void_confirmed"):
            return

        if self.digital_invoice_status == "Sent":
            frappe.throw(
                _("No se puede cancelar el comprobante {0} porque ya fue emitido "
                  "a la imprenta fiscal digital (TFHKA). Use el botón "
                  "\"Anular Comprobante\" para anularlo primero en HKA.").format(self.name)
            )

    def validate_unique_voucher_number(self) -> None:
        """Valida que el número de comprobante no esté duplicado."""
        if not self.voucher_number:
            return

        duplicate: str | None = frappe.db.get_value(
            "ISLR Withholding Voucher",
            {
                "voucher_number": self.voucher_number,
                "name": ["!=", self.name],
                "docstatus": ["!=", 2],
            },
        )
        if duplicate:
            frappe.throw(
                _("Ya existe un comprobante de retención ISLR con el número {0}: {1}").format(
                    frappe.bold(self.voucher_number), frappe.bold(duplicate)
                )
            )

    def validate_withholding_amount(self) -> None:
        """Impide aprobar un comprobante cuando no hay ISLR a retener."""
        total_islr: float = flt(self.totals_islr_amount)
        if not total_islr:
            frappe.throw(
                _("No se puede procesar este comprobante porque el monto total "
                  "de ISLR retenido es 0. Verifique que las facturas incluidas "
                  "tengan retención de ISLR.")
            )

    def before_print(self, settings) -> None:
        company_tax_id = frappe.db.get_value("Company", self.empresa, "tax_id")
        supplier_tax_id = frappe.db.get_value("Supplier", self.supplier, "tax_id")

        main_fields = [
            "totals_islr_base_amount",
            "totals_islr_amount",
            "totals_grand_total",
            "totals_paid_amount"
        ]

        child_fields = [
            "grand_total",
            "islr_base_amount",
            "subtracting",
            "islr_amount",
        ]

        self.company_tax_id = company_tax_id or "N/A"
        self.supplier_tax_id = supplier_tax_id or "N/A"
        format_amounts(self, main_fields, child_fields, child_table_field="islr_withholding_voucher_item")

    def before_insert(self) -> None:
        company_doc = frappe.get_cached_doc("Company", self.empresa)
        correlative_format: str = company_doc.islr_withholding_format

        final_voucher_number, final_next_correlative_number, \
            current_year, current_month = \
            self._get_and_format_correlatives(correlative_format,
                                              company_doc.islr_withholding_correlative)

        self.voucher_number = final_voucher_number
        self.posting_date = nowdate()

        company_doc.islr_withholding_correlative = final_next_correlative_number
        company_doc.save(ignore_permissions=True)

    def on_trash(self) -> None:
        document_date = self.posting_date
        current_date = getdate(nowdate())

        if document_date:
            document_month_year: str = getdate(document_date).strftime('%Y-%m')
            current_month_year: str = current_date.strftime('%Y-%m')
        else:
            frappe.throw(
                _("No se puede determinar la fecha del comprobante para la validación.")
            )

        if document_month_year != current_month_year:
            frappe.throw(
                _("No se puede eliminar el comprobante. Solo se permiten "
                  "eliminaciones para el periodo actual ({0}).").format(current_month_year)
            )


# ------------------------------------------------------------------ #
# Endpoints whitelisted                                               #
# ------------------------------------------------------------------ #

@frappe.whitelist()
def get_valid_invoices(
    supplier: str,
    start_date: str,
    end_date: str,
    company: str,
) -> list[dict]:
    """Obtiene facturas de compra con retención ISLR para el comprobante.

    Lee directamente desde Purchase Taxes and Charges (charge_type='ISLR')
    de facturas aprobadas en el rango de fechas indicado.

    Genera una fila por cada concepto ISLR de cada factura (multi-concepto).
    Excluye combinaciones (factura, código) ya incluidas en otros comprobantes.
    """
    default_currency: str = frappe.get_cached_value(
        "Company", company, "default_currency"
    ) or ""

    type_of_person: str = frappe.db.get_value(
        "Supplier", supplier, "type_of_person"
    ) or ""
    if not type_of_person:
        frappe.throw(
            _("El Proveedor debe tener un 'Tipo de Persona' definido "
              "para procesar retenciones ISLR.")
        )

    # Combinaciones (factura, código) ya en otros comprobantes (no cancelados)
    excluded_combinations: list[dict] = frappe.db.sql("""
        SELECT child.purchase_invoice, child.code
        FROM `tabISLR Withholding Voucher Item` child
        INNER JOIN `tabISLR Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.docstatus != 2
            AND parent.empresa = %(company)s
            AND child.purchase_invoice IS NOT NULL
            AND child.purchase_invoice != ''
    """, {"company": company}, as_dict=True)

    excluded_set: set[tuple[str, str]] = {
        (d.purchase_invoice, d.code or "") for d in excluded_combinations
    }

    # Facturas válidas en el rango de fechas
    valid_invoices: list[dict] = frappe.get_all(
        "Purchase Invoice",
        filters={
            "supplier": supplier,
            "posting_date": ["between", [start_date, end_date]],
            "company": company,
            "docstatus": 1,
            "is_return": 0,
            "is_debit_note": 0,
        },
        fields=[
            "name", "bill_no", "bill_control", "posting_date",
            "grand_total", "total", "base_total", "base_grand_total",
            "outstanding_amount", "affected_invoice_number",
            "conversion_rate", "currency"
        ]
    )

    if not valid_invoices:
        return []

    valid_invoice_names: list[str] = [inv.name for inv in valid_invoices]
    invoice_map: dict = {inv.name: inv for inv in valid_invoices}

    # Obtener todas las filas ISLR de las facturas válidas
    islr_taxes: list[dict] = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parent": ["in", valid_invoice_names],
            "parenttype": "Purchase Invoice",
            "charge_type": "ISLR",
        },
        fields=[
            "parent", "rate", "tax_amount", "base_tax_amount",
            "percentage_base", "subtracting", "code",
            "base_tax_amount_after_discount_amount"
        ]
    )

    if not islr_taxes:
        return []

    invoices_with_taxes: list[dict] = []

    for tax in islr_taxes:
        invoice = invoice_map.get(tax.parent)
        if not invoice:
            continue

        tax_code: str = tax.code or ""

        # Excluir si ya está en otro comprobante
        if (tax.parent, tax_code) in excluded_set:
            continue

        # Factor de conversión a moneda de la empresa
        conversion_rate: float = flt(invoice.conversion_rate) or 1.0
        is_multicurrency: bool = default_currency != invoice.currency
        rate: float = conversion_rate if is_multicurrency else 1.0

        # Base de retención ISLR en moneda de la empresa
        islr_base_amount: float = flt(
            flt(invoice.total) * flt(tax.percentage_base or 100) / 100 * rate, 2
        )

        # Monto retenido ISLR en moneda de la empresa
        islr_amount: float = abs(flt(
            tax.base_tax_amount_after_discount_amount or tax.base_tax_amount, 2
        ))

        # Grand total en moneda de la empresa
        grand_total_vef: float = abs(flt(invoice.grand_total or 0) * rate)

        # Monto abonado (pagado) en moneda de la empresa
        paid_amount: float = max(
            flt(invoice.base_grand_total or 0)
            - flt(invoice.outstanding_amount or 0), 0
        )

        invoice_data: dict = {
            "purchase_invoice": invoice.name,
            "doc_no": invoice.bill_no,
            "doc_type": "FACT",
            "bill_control": invoice.bill_control,
            "posting_date": invoice.posting_date,
            "rate": flt(tax.rate),
            "subtracting": abs(flt(tax.subtracting)),
            "islr_amount": islr_amount,
            "code": tax_code,
            "islr_base_amount": abs(islr_base_amount),
            "grand_total": grand_total_vef,
            "total": abs(flt(invoice.total)),
            "affected_invoice_number": invoice.affected_invoice_number,
            "paid_amount": paid_amount,
        }

        invoices_with_taxes.append(invoice_data)

    return invoices_with_taxes
