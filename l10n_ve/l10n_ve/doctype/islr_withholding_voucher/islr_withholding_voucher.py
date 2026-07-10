# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher
from l10n_ve.utils.utils import format_amounts


# ── Constantes de módulo ────────────────────────────────────────────── #

_ISLR_INVOICE_FIELDS: list[str] = [
    "name", "bill_no", "bill_control", "posting_date",
    "grand_total", "total", "base_total", "base_grand_total",
    "outstanding_amount", "affected_invoice_number",
    "conversion_rate", "currency", "branch",
]

_DOCTYPE_CONFIG: dict[str, tuple[str, bool]] = {
    "Purchase Invoice": ("FACT", False),
    "VE Purchase Credit Note": ("N/CR", True),
    "VE Purchase Debit Note": ("N/DB", False),
}


class ISLRWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self) -> None:
        if not self.branch:
            branches = set()
            for item in self.get("islr_withholding_voucher_item") or []:
                if item.purchase_invoice and item.purchase_invoice_type:
                    br = frappe.db.get_value(item.purchase_invoice_type, item.purchase_invoice, "branch")
                    if br:
                        branches.add(br)
            if len(branches) == 1:
                self.branch = list(branches)[0]

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
        """Impide aprobar un comprobante cuando ningún item tiene ISLR a retener.

        El total neto puede ser 0 o negativo cuando NCs compensan PIs,
        pero al menos un item individual debe tener ISLR retenido.
        """
        has_any_withholding: bool = any(
            flt(item.islr_amount) for item in self.get("islr_withholding_voucher_item", [])
        )
        if not has_any_withholding:
            frappe.throw(
                _("No se puede procesar este comprobante porque ninguna factura incluida "
                  "tiene ISLR retenido. Verifique que las facturas tengan retención de ISLR.")
            )

    def before_print(self, settings) -> None:
        company_tax_id: str = frappe.get_cached_value("Company", self.empresa, "tax_id") or "N/A"
        supplier_tax_id: str = frappe.get_cached_value("Supplier", self.supplier, "tax_id") or "N/A"

        main_fields: list[str] = [
            "totals_islr_base_amount",
            "totals_islr_amount",
            "totals_grand_total",
            "totals_paid_amount"
        ]

        child_fields: list[str] = [
            "grand_total",
            "islr_base_amount",
            "subtracting",
            "islr_amount",
        ]

        self.company_tax_id = company_tax_id
        self.supplier_tax_id = supplier_tax_id
        format_amounts(self, main_fields, child_fields, child_table_field="islr_withholding_voucher_item")

    def before_insert(self) -> None:
        # Row lock atómico para prevenir race conditions en correlativos
        company_row: dict = frappe.db.sql(
            "SELECT islr_withholding_correlative, islr_withholding_format "
            "FROM `tabCompany` WHERE name = %s FOR UPDATE",
            self.empresa, as_dict=True
        )
        if not company_row:
            frappe.throw(_("Empresa no encontrada: {0}").format(self.empresa))

        company_data: dict = company_row[0]
        correlative_format: str = company_data.islr_withholding_format

        (final_voucher_number, final_next_correlative_number,
         current_year, current_month) = self._get_and_format_correlatives(
            correlative_format, company_data.islr_withholding_correlative
        )

        self.voucher_number = final_voucher_number
        self.posting_date = nowdate()

        # Incremento atómico: gap aceptable si insert() falla después
        frappe.db.sql(
            "UPDATE `tabCompany` SET islr_withholding_correlative = %s WHERE name = %s",
            (final_next_correlative_number, self.empresa)
        )

    def on_trash(self) -> None:
        if self.docstatus == 2:
            frappe.throw(
                _("No se puede eliminar un comprobante de retención cancelado. "
                  "El comprobante debe permanecer en el historial como cancelado.")
            )

        if not self.posting_date:
            frappe.throw(
                _("No se puede determinar la fecha del comprobante para la validación.")
            )

        document_month: str = getdate(self.posting_date).strftime('%Y-%m')
        current_month: str = getdate(nowdate()).strftime('%Y-%m')

        if document_month != current_month:
            frappe.throw(
                _("No se puede eliminar el comprobante. Solo se permiten "
                  "eliminaciones para el periodo actual ({0}).").format(current_month)
            )


# ── API pública ──────────────────────────────────────────────────────── #

@frappe.whitelist()
def get_valid_invoices(
    supplier: str,
    start_date: str,
    end_date: str,
    company: str,
    exclude_voucher: str = "",
    branch: str = "",
) -> list[dict]:
    """Obtiene facturas de compra, NC y ND con retención ISLR para el comprobante.

    Lee directamente desde Purchase Taxes and Charges (charge_type='ISLR')
    de facturas aprobadas en el rango de fechas indicado.

    Genera una fila por cada concepto ISLR de cada factura (multi-concepto).
    Excluye combinaciones (factura, código) ya incluidas en otros comprobantes.

    Args:
        exclude_voucher: Nombre del comprobante actual para no auto-excluirse.
    """
    default_currency: str = frappe.get_cached_value(
        "Company", company, "default_currency"
    ) or ""

    type_of_person: str = frappe.get_cached_value(
        "Supplier", supplier, "type_of_person"
    ) or ""
    if not type_of_person:
        frappe.throw(
            _("El Proveedor debe tener un 'Tipo de Persona' definido "
              "para procesar retenciones ISLR.")
        )

    # Fase 1: Exclusiones + candidatos
    excluded_set: set[tuple[str, str]] = _get_excluded_combinations(company, exclude_voucher)
    doc_map: dict[str, dict] = _get_candidate_invoices(supplier, start_date, end_date, company, branch=branch)

    all_names: list[str] = list(doc_map)
    if not all_names:
        return []

    # Fase 2: Filas ISLR de los candidatos
    islr_taxes: list[dict] = _get_islr_taxes(all_names)
    if not islr_taxes:
        return []

    # Fase 3: Construir filas del child table
    invoices_with_taxes: list[dict] = []
    for tax in islr_taxes:
        invoice: dict | None = doc_map.get(tax.parent)
        if not invoice:
            continue

        tax_code: str = tax.code or ""
        if (tax.parent, tax_code) in excluded_set:
            continue

        row: dict = _build_islr_row(invoice, tax, default_currency)
        invoices_with_taxes.append(row)

    return invoices_with_taxes


# ── Funciones internas ───────────────────────────────────────────────── #

def _get_excluded_combinations(company: str, exclude_voucher: str) -> set[tuple[str, str]]:
    """Obtiene combinaciones (factura, código) ya asignadas a comprobantes vigentes."""
    rows: list[dict] = frappe.db.sql("""
        SELECT child.purchase_invoice, child.code
        FROM `tabISLR Withholding Voucher Item` child
        INNER JOIN `tabISLR Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.docstatus = 1
            AND parent.empresa = %(company)s
            AND parent.name != %(exclude_voucher)s
            AND child.purchase_invoice IS NOT NULL
            AND child.purchase_invoice != ''
    """, {"company": company, "exclude_voucher": exclude_voucher or ""}, as_dict=True)

    return {(d.purchase_invoice, d.code or "") for d in rows}


def _get_candidate_invoices(
    supplier: str,
    start_date: str,
    end_date: str,
    company: str,
    branch: str = "",
) -> dict[str, dict]:
    """Obtiene documentos candidatos con datos completos, indexados por name.

    Ejecuta 1 query UNION ALL en vez de 3 queries separadas.
    PI filtra is_return=0 y is_debit_note=0; NC y ND no tienen esos campos.
    """
    params: dict = {
        "supplier": supplier,
        "start_date": start_date,
        "end_date": end_date,
        "company": company,
    }

    fields_sql: str = ", ".join(_ISLR_INVOICE_FIELDS)

    branch_clause: str = ""
    if branch:
        branch_clause = "AND branch = %(branch)s"
        params["branch"] = branch
    else:
        branch_clause = "AND (branch IS NULL OR branch = '')"

    unions: list[str] = []
    for dt in WithholdingVoucher.PURCHASE_PARENTTYPES:
        extra: str = "AND is_return = 0 AND is_debit_note = 0" if dt == "Purchase Invoice" else ""
        unions.append(f"""
            SELECT {fields_sql}, '{dt}' AS doctype
            FROM `tab{dt}`
            WHERE supplier = %(supplier)s
              AND posting_date BETWEEN %(start_date)s AND %(end_date)s
              AND company = %(company)s
              AND docstatus = 1
              {extra}
              {branch_clause}
        """)

    rows: list[dict] = frappe.db.sql(
        " UNION ALL ".join(unions), params, as_dict=True
    )

    return {r.name: r for r in rows}


def _get_islr_taxes(all_names: list[str]) -> list[dict]:
    """Obtiene filas ISLR de Purchase Taxes and Charges para los documentos indicados."""
    return frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parent": ["in", all_names],
            "parenttype": ["in", WithholdingVoucher.PURCHASE_PARENTTYPES],
            "charge_type": "ISLR",
        },
        fields=[
            "parent", "parenttype", "rate", "tax_amount", "base_tax_amount",
            "percentage_base", "subtracting", "code",
            "base_tax_amount_after_discount_amount",
        ],
    )


def _build_islr_row(
    invoice: dict,
    tax: dict,
    default_currency: str,
) -> dict:
    """Construye un dict de fila para el child table del comprobante ISLR.

    Montos siempre en positivo (abs). La diferenciación NC/ND/PI se hace
    mediante el campo doc_type en el child table.
    """
    doc_type_label, is_return = _DOCTYPE_CONFIG.get(invoice.doctype, ("FACT", False))

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

    return {
        "purchase_invoice_type": invoice.doctype,
        "purchase_invoice": invoice.name,
        "doc_no": invoice.bill_no,
        "doc_type": doc_type_label,
        "bill_control": invoice.bill_control,
        "posting_date": invoice.posting_date,
        "rate": flt(tax.rate),
        "subtracting": abs(flt(tax.subtracting)),
        "islr_amount": islr_amount,
        "code": tax.code or "",
        "islr_base_amount": abs(islr_base_amount),
        "grand_total": grand_total_vef,
        "total": abs(flt(invoice.total)),
        "affected_invoice_number": invoice.affected_invoice_number,
        "paid_amount": paid_amount,
        "is_return": 1 if is_return else 0,
        "branch": invoice.branch,
    }
