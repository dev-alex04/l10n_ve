# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate, get_link_to_form
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher
from l10n_ve.utils.utils import format_amounts


# ── Constantes de módulo ────────────────────────────────────────────── #

_ISLR_INVOICE_FIELDS: list[str] = [
    "name", "bill_no", "bill_control", "posting_date", "bill_date",
    "grand_total", "total", "base_total", "base_grand_total",
    "outstanding_amount", "affected_invoice_number",
    "conversion_rate", "currency", "branch",
    "base_taxes_and_charges_added",
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
        self.validate_no_duplicate_invoices()
        self.validate_withholding_amount()

    def validate_no_duplicate_invoices(self) -> None:
        """Bloquea si algún par (factura, concepto) ya está en otro comprobante no cancelado.

        Cubre todos los caminos (flujo manual, botón desde la factura,
        inserción programática): el filtro de get_valid_invoices solo excluye
        comprobantes aprobados y no protege contra borradores concurrentes.
        La unidad es el par factura+código: conceptos distintos de la misma
        factura pueden vivir en comprobantes distintos.
        """
        items: list[tuple[str, str, str]] = [
            (
                item.purchase_invoice_type or "Purchase Invoice",
                item.purchase_invoice,
                item.code or "",
            )
            for item in self.get("islr_withholding_voucher_item", [])
            if item.purchase_invoice
        ]
        if not items:
            return

        seen: set[tuple[str, str, str]] = set()
        for triple in items:
            if triple in seen:
                frappe.throw(
                    _("La factura {0} con el concepto {1} está repetida en las "
                      "líneas del comprobante.").format(triple[1], triple[2])
                )
            seen.add(triple)

        rows = frappe.db.sql(
            """
            SELECT child.purchase_invoice_type, child.purchase_invoice, child.code,
                   parent.name, parent.voucher_number, parent.docstatus
            FROM `tabISLR Withholding Voucher Item` child
            INNER JOIN `tabISLR Withholding Voucher` parent ON parent.name = child.parent
            WHERE child.purchase_invoice IN %(invoices)s
              AND parent.docstatus < 2
              AND parent.name != %(own_name)s
            """,
            {"invoices": [name for _type, name, _code in items], "own_name": self.name or ""},
            as_dict=True,
        )

        conflicts = [
            _("{0} (concepto {1}) ya está en el comprobante {2}").format(
                row.purchase_invoice,
                row.code,
                _voucher_link(row),
            )
            for row in rows
            if (
                row.purchase_invoice_type or "Purchase Invoice",
                row.purchase_invoice,
                row.code or "",
            ) in seen
        ]
        if conflicts:
            frappe.throw("<br>".join(conflicts), title=_("Factura ya comprobada"))

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

    # Grand total en moneda de la empresa (antes de retenciones: base + IVA)
    grand_total_vef: float = abs(flt(invoice.base_total or 0)) + abs(flt(invoice.base_taxes_and_charges_added or 0))

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
        "posting_date": invoice.bill_date or invoice.posting_date,
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


# ── Creación desde la factura de compra ─────────────────────────────── #

# Espejo de ISLR_ITEM_TOTAL_MAP del JS del comprobante: los totales del
# padre no se recalculan en el servidor, hay que sumarlos al construirlo.
_ISLR_TOTAL_ITEM_MAP: dict[str, str] = {
    "totals_islr_base_amount": "islr_base_amount",
    "totals_islr_amount": "islr_amount",
    "totals_grand_total": "grand_total",
    "totals_paid_amount": "paid_amount",
}


def _find_voucher_containing_invoice(purchase_invoice: str, docstatus: int) -> dict | None:
    """Retorna {name, voucher_number} del comprobante ISLR (con ese docstatus) que ya incluye la factura."""
    rows = frappe.db.sql(
        """
        SELECT parent.name, parent.voucher_number
        FROM `tabISLR Withholding Voucher Item` child
        INNER JOIN `tabISLR Withholding Voucher` parent ON parent.name = child.parent
        WHERE child.purchase_invoice = %s AND parent.docstatus = %s
        LIMIT 1
        """,
        (purchase_invoice, docstatus),
        as_dict=True,
    )
    return rows[0] if rows else None


def _voucher_link(voucher: dict) -> str:
    """Enlace al comprobante con el N° de comprobante (no el name) como texto."""
    return get_link_to_form(
        "ISLR Withholding Voucher", voucher["name"],
        voucher.get("voucher_number") or voucher["name"],
    )


@frappe.whitelist()
def make_islr_withholding_voucher(source_name: str) -> dict:
    """Crea, aprueba y emite a HKA un Comprobante de Retención ISLR desde la factura de compra.

    Reusa get_valid_invoices para calcular las líneas (una por concepto ISLR,
    mismos filtros y montos que el flujo del formulario). Si la emisión a HKA
    falla, el comprobante queda aprobado en estado Error y el cron lo reintenta.
    """
    frappe.has_permission("ISLR Withholding Voucher", "create", throw=True)

    invoice = frappe.get_doc("Purchase Invoice", source_name)
    if invoice.docstatus != 1:
        frappe.throw(_("La factura debe estar validada para generar el comprobante de retención."))

    draft = _find_voucher_containing_invoice(invoice.name, docstatus=0)
    if draft:
        frappe.throw(
            _("La factura ya está incluida en el comprobante {0}.").format(
                _voucher_link(draft)
            )
        )

    posting_date = str(invoice.posting_date)
    rows = [
        row
        for row in get_valid_invoices(
            supplier=invoice.supplier,
            start_date=posting_date,
            end_date=posting_date,
            company=invoice.company,
            branch=invoice.get("branch") or "",
        )
        if row.get("purchase_invoice") == invoice.name
    ]

    if not rows:
        submitted = _find_voucher_containing_invoice(invoice.name, docstatus=1)
        if submitted:
            frappe.throw(
                _("Todos los conceptos ISLR de la factura ya están en el "
                  "comprobante {0}.").format(_voucher_link(submitted))
            )
        frappe.throw(
            _("La factura no tiene conceptos de ISLR aplicados "
              "(botón 'Agregar ISLR' en la factura antes de validarla).")
        )

    # Fail-closed TEMPRANO: sin serie digital activa para la sucursal se aborta
    # ANTES de crear el comprobante — no consumir correlativo de la Company ni
    # dejar un comprobante aprobado atascado en Error reintentándose en el cron.
    from l10n_ve.digital_invoice.retention_integration import _validate_digital_series
    series_errors = _validate_digital_series(
        frappe._dict(empresa=invoice.company, branch=invoice.get("branch") or "")
    )
    if series_errors:
        frappe.throw(series_errors[0], title=_("Serie de Facturación No Encontrada"))

    doc = frappe.new_doc("ISLR Withholding Voucher")
    doc.empresa = invoice.company
    doc.supplier = invoice.supplier
    doc.branch = invoice.get("branch") or ""
    doc.start_date = posting_date
    doc.end_date = posting_date

    totals: dict[str, float] = {field: 0.0 for field in _ISLR_TOTAL_ITEM_MAP}
    for row in rows:
        doc.append("islr_withholding_voucher_item", row)
        sign = -1 if row.get("is_return") else 1
        for total_field, item_field in _ISLR_TOTAL_ITEM_MAP.items():
            totals[total_field] += flt(row.get(item_field)) * sign

    for field, value in totals.items():
        doc.set(field, value)

    doc.insert(ignore_permissions=True)
    doc.flags.ignore_permissions = True
    doc.submit()
    # Persistir creación+aprobación antes de emitir: si la emisión a HKA
    # falla, el comprobante queda aprobado en Error y el cron lo reintenta.
    frappe.db.commit()

    return _emit_islr_voucher(doc.name)


def _emit_islr_voucher(voucher_name: str) -> dict:
    """Emite el comprobante a HKA y arma la respuesta para el formulario."""
    from l10n_ve.digital_invoice.islr_withholding_integration import process_islr_voucher

    try:
        emitted = bool(process_islr_voucher(voucher_name))
    except Exception:
        frappe.log_error(
            title=f"Error emitiendo {voucher_name} a HKA desde la factura de compra",
            message=frappe.get_traceback(),
        )
        emitted = False

    info = frappe.db.get_value(
        "ISLR Withholding Voucher", voucher_name,
        ["voucher_number", "bill_control"], as_dict=True,
    ) or frappe._dict()

    error_note = None
    if not emitted:
        error_note = frappe.db.get_value(
            "VE Digital Invoice Log",
            {"sales_invoice": voucher_name, "status": "Error",
             "document_type": "ISLR Withholding Voucher"},
            "notes", order_by="creation desc",
        )

    return {
        "voucher": voucher_name,
        "emitted": emitted,
        "voucher_number": info.get("voucher_number"),
        "bill_control": info.get("bill_control"),
        "error": error_note,
    }
