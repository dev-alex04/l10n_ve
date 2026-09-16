# Copyright (c) 2025, DominaERP and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate, getdate, get_link_to_form
from l10n_ve.controllers.withholding_voucher import WithholdingVoucher


# ── Constantes de módulo ────────────────────────────────────────────── #

# Referencia corta a la constante de clase heredada del mixin
_PURCHASE_PARENTTYPES: list[str] = WithholdingVoucher.PURCHASE_PARENTTYPES

_DOC_FIELDS: dict[str, list[str]] = {
    "Purchase Invoice": [
        "name", "bill_no", "bill_control", "posting_date", "bill_date",
        "base_grand_total", "base_total", "total_exempt",
        "base_taxes_and_charges_added", "conversion_rate", "currency",
        "is_return", "is_debit_note",
        "credit_note_no", "debit_note_no", "affected_invoice_number", "branch",
    ],
    "VE Purchase Credit Note": [
        "name", "bill_no", "bill_control", "posting_date", "bill_date",
        "base_grand_total", "base_total", "total_exempt",
        "base_taxes_and_charges_added", "conversion_rate", "currency",
        "affected_invoice_number", "branch",
    ],
    "VE Purchase Debit Note": [
        "name", "bill_no", "bill_control", "posting_date", "bill_date",
        "base_grand_total", "base_total", "total_exempt",
        "base_taxes_and_charges_added", "conversion_rate", "currency",
        "affected_invoice_number", "branch",
    ],
}


class VATWithholdingVoucher(Document, WithholdingVoucher):

    def validate(self) -> None:
        if not self.branch:
            branches = set()
            for item in self.get("vat_withholding_voucher_item") or []:
                if item.purchase_invoice and item.purchase_invoice_type:
                    br = frappe.db.get_value(item.purchase_invoice_type, item.purchase_invoice, "branch")
                    if br:
                        branches.add(br)
            if len(branches) == 1:
                self.branch = list(branches)[0]

        self.validate_address()
        self.validate_fiscal_period()
        self.validate_unique_voucher_number()
        self.validate_no_duplicate_invoices()
        if self.is_new() and self.amended_from:
            self._populate_withholding_rate()
        self.validate_withholding_amount()

    def validate_no_duplicate_invoices(self) -> None:
        """Bloquea si alguna factura de las líneas ya está en otro comprobante no cancelado.

        Cubre todos los caminos (flujo manual, botón desde la factura,
        inserción programática): el filtro de get_valid_invoices solo excluye
        comprobantes aprobados y no protege contra borradores concurrentes.
        """
        items: list[tuple[str, str]] = [
            (item.purchase_invoice_type or "Purchase Invoice", item.purchase_invoice)
            for item in self.get("vat_withholding_voucher_item", [])
            if item.purchase_invoice
        ]
        if not items:
            return

        seen: set[tuple[str, str]] = set()
        for pair in items:
            if pair in seen:
                frappe.throw(
                    _("La factura {0} está repetida en las líneas del comprobante.").format(pair[1])
                )
            seen.add(pair)

        rows = frappe.db.sql(
            """
            SELECT child.purchase_invoice_type, child.purchase_invoice,
                   parent.name, parent.voucher_number, parent.docstatus
            FROM `tabVAT Withholding Voucher Item` child
            INNER JOIN `tabVAT Withholding Voucher` parent ON parent.name = child.parent
            WHERE child.purchase_invoice IN %(invoices)s
              AND parent.docstatus < 2
              AND parent.name != %(own_name)s
            """,
            {"invoices": [name for _type, name in items], "own_name": self.name or ""},
            as_dict=True,
        )

        conflicts = [
            _("{0} ya está en el comprobante {1}").format(
                row.purchase_invoice,
                _voucher_link(row),
            )
            for row in rows
            if (row.purchase_invoice_type or "Purchase Invoice", row.purchase_invoice) in seen
        ]
        if conflicts:
            frappe.throw("<br>".join(conflicts), title=_("Factura ya comprobada"))

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
                "parenttype": ["in", _PURCHASE_PARENTTYPES],
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

    def before_print(self, settings=None) -> None:
        """Populate tax_id fields before printing so the print format can render them."""
        self.company_tax_id = frappe.get_cached_value("Company", self.empresa, "tax_id") or "N/A"
        self.supplier_tax_id = frappe.get_cached_value("Supplier", self.supplier, "tax_id") or "N/A"
        self.supplier_name = frappe.get_cached_value("Supplier", self.supplier, "supplier_name") or self.supplier

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

    def before_insert(self) -> None:
        # Row lock atómico para prevenir race conditions en correlativos
        company_row: dict = frappe.db.sql(
            "SELECT vat_withholding_correlative, vat_withholding_format "
            "FROM `tabCompany` WHERE name = %s FOR UPDATE",
            self.empresa, as_dict=True
        )
        if not company_row:
            frappe.throw(_("Empresa no encontrada: {0}").format(self.empresa))

        company_data: dict = company_row[0]
        correlative_format: str = company_data.vat_withholding_format

        final_voucher_number, final_next_correlative_number, year, month = \
            self._get_and_format_correlatives(correlative_format, company_data.vat_withholding_correlative)

        self.voucher_number = final_voucher_number
        self.fiscal_period = f"{month}/{year}"

        # Incremento atómico: gap aceptable si insert() falla después
        frappe.db.sql(
            "UPDATE `tabCompany` SET vat_withholding_correlative = %s WHERE name = %s",
            (final_next_correlative_number, self.empresa)
        )

    def on_trash(self) -> None:
        if self.docstatus == 2:
            frappe.throw(
                _("No se puede eliminar un comprobante de retención cancelado. "
                  "El comprobante debe permanecer en el historial como cancelado.")
            )

        if not self.issue_date:
            frappe.throw(
                _("No se puede determinar la fecha del comprobante para la validación.")
            )

        document_month: str = getdate(self.issue_date).strftime('%Y-%m')
        current_month: str = getdate(nowdate()).strftime('%Y-%m')

        if document_month != current_month:
            frappe.throw(
                _("No se puede eliminar el comprobante. Solo se permiten "
                  "eliminaciones para el periodo actual ({0}).").format(current_month)
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
        """Impide aprobar un comprobante cuando ningún item tiene IVA a retener.

        El total neto puede ser 0 o negativo cuando NCs compensan PIs,
        pero al menos un item individual debe tener IVA retenido.
        """
        has_any_withholding: bool = any(
            flt(item.tax_amount_vat) for item in self.get("vat_withholding_voucher_item", [])
        )
        if not has_any_withholding:
            frappe.throw(
                _("No se puede procesar este comprobante porque ninguna factura incluida "
                  "tiene IVA retenido. Verifique que las facturas tengan IVA gravable.")
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
    """Obtiene facturas de compra, NC y ND válidas para un comprobante de retención IVA.

    Criterios de inclusión:
    - Documento aprobado (docstatus=1) del proveedor y rango de fechas indicado
    - Que tenga una fila de impuesto tipo 'VAT Withholding' con monto > 0
    - Que no esté ya incluida en otro comprobante vigente (no cancelado)

    Args:
        exclude_voucher: Nombre del comprobante actual para no auto-excluirse.
    """
    # Fase 1: Documentos ya asignados a comprobantes vigentes
    all_excluded_invoices: list[str] = _get_excluded_invoices(company, exclude_voucher)

    # Fase 2: Candidatos por DocType (1 query UNION ALL)
    names_by_doctype: dict[str, list[str]] = _get_candidate_invoices(
        supplier, start_date, end_date, company, all_excluded_invoices, branch=branch
    )

    all_valid_names: list[str] = []
    for names in names_by_doctype.values():
        all_valid_names.extend(names)

    if not all_valid_names:
        return []

    # Fase 3: Datos de retención (VAT Withholding) con monto > 0
    withholding_map: dict[str, dict] = _get_withholding_map(all_valid_names)
    if not withholding_map:
        return []

    invoices_with_withholding: set[str] = set(withholding_map)

    # Fase 4: Datos de IVA (VAT) para la tasa aplicada
    vat_map: dict[str, dict] = _get_vat_map(invoices_with_withholding)

    # Fase 5: Datos completos de facturas filtradas por retención
    default_currency: str = frappe.get_cached_value("Company", company, "default_currency") or ""

    invoices_with_taxes: list[dict] = []
    for doc_type, candidate_names in names_by_doctype.items():
        candidate_set: set[str] = set(candidate_names)
        filtered: list[str] = [n for n in invoices_with_withholding if n in candidate_set]
        if not filtered:
            continue

        docs: list[dict] = frappe.get_all(
            doc_type,
            filters={"name": ["in", filtered]},
            fields=_DOC_FIELDS[doc_type],
        )
        for doc in docs:
            invoices_with_taxes.append(
                _build_invoice_row(doc, vat_map, withholding_map, default_currency, doc_type=doc_type)
            )

    return invoices_with_taxes


# ── Funciones internas ───────────────────────────────────────────────── #

def _get_excluded_invoices(company: str, exclude_voucher: str) -> list[str]:
    """Obtiene documentos ya asignados a comprobantes vigentes."""
    rows: list[dict] = frappe.db.sql("""
        SELECT child.purchase_invoice
        FROM `tabVAT Withholding Voucher Item` child
        INNER JOIN `tabVAT Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.docstatus = 1
            AND parent.empresa = %(company)s
            AND parent.name != %(exclude_voucher)s
            AND child.purchase_invoice IS NOT NULL
            AND child.purchase_invoice != ''
    """, {"company": company, "exclude_voucher": exclude_voucher or ""}, as_dict=True)

    return [d.purchase_invoice for d in rows]


def _get_candidate_invoices(
    supplier: str,
    start_date: str,
    end_date: str,
    company: str,
    excluded: list[str],
    branch: str = "",
) -> dict[str, list[str]]:
    """Obtiene nombres de documentos candidatos agrupados por DocType.

    Ejecuta 1 query UNION ALL en vez de N queries separadas.
    """
    params: dict = {
        "supplier": supplier,
        "start_date": start_date,
        "end_date": end_date,
        "company": company,
    }

    exclusion_clause: str = ""
    if excluded:
        exclusion_clause = "AND name NOT IN %(excluded)s"
        params["excluded"] = excluded

    branch_clause: str = ""
    if branch:
        branch_clause = "AND branch = %(branch)s"
        params["branch"] = branch
    else:
        branch_clause = "AND (branch IS NULL OR branch = '')"

    unions: list[str] = []
    for dt in _PURCHASE_PARENTTYPES:
        tab: str = f"`tab{dt}`"
        unions.append(f"""
            SELECT name, '{dt}' AS doctype FROM {tab}
            WHERE supplier = %(supplier)s
              AND posting_date BETWEEN %(start_date)s AND %(end_date)s
              AND company = %(company)s
              AND docstatus = 1
              {exclusion_clause}
              {branch_clause}
        """)

    rows: list[dict] = frappe.db.sql(
        " UNION ALL ".join(unions), params, as_dict=True
    )

    result: dict[str, list[str]] = {dt: [] for dt in _PURCHASE_PARENTTYPES}
    for r in rows:
        result[r.doctype].append(r.name)
    return result


def _get_withholding_map(all_valid_names: list[str]) -> dict[str, dict]:
    """Obtiene datos de retención (VAT Withholding) indexados por parent."""
    withholding_data: list[dict] = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parenttype": ["in", _PURCHASE_PARENTTYPES],
            "parent": ["in", all_valid_names],
            "charge_type": "VAT Withholding",
            "base_tax_amount": ["!=", 0],
        },
        fields=["parent", "rate as withholding_rate", "base_tax_amount"],
    )
    return {d.parent: d for d in withholding_data}


def _get_vat_map(invoices_with_withholding: set[str]) -> dict[str, dict]:
    """Obtiene datos de IVA (VAT) indexados por parent, acumulando base_tax_amount."""
    if not invoices_with_withholding:
        return {}

    vat_data: list[dict] = frappe.get_all(
        "Purchase Taxes and Charges",
        filters={
            "parenttype": ["in", _PURCHASE_PARENTTYPES],
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

    return vat_map


def _build_invoice_row(
    inv: dict,
    vat_map: dict[str, dict],
    withholding_map: dict[str, dict],
    default_currency: str,
    doc_type: str = "Purchase Invoice",
) -> dict:
    """Construye un dict de fila para el child table del comprobante de retención IVA.

    Montos siempre en positivo (abs). La diferenciación NC/ND/PI se hace
    mediante los campos credit_note_no y debit_note_no en el child table.
    """
    vat_details: dict = vat_map.get(inv.name, {})
    wh_details: dict = withholding_map.get(inv.name, {})

    rate: float = inv.conversion_rate if (default_currency != inv.currency and inv.conversion_rate) else 1
    total_exempt: float = (inv.total_exempt or 0) * rate

    is_nc: bool = doc_type == "VE Purchase Credit Note"
    is_nd: bool = doc_type == "VE Purchase Debit Note"

    # El total de la línea es el BRUTO de la factura: base + IVA. No se deriva de
    # base_grand_total, que en una factura de compra ya viene neto de TODAS las retenciones
    # (ver overrides/purchase_invoice.py::_grand_total_includes_withholding). Restituirle solo
    # la de IVA dejaba el total corto exactamente en el ISLR: el comprobante impreso mostraba
    # 13.144.929,48 donde el detalle decía 13.375.542,28 (caso VNET, 16-sep-2026). El detalle
    # del payload de HKA ya suma base + exento + IVA, así que esta es la misma cuenta y las
    # dos filas cierran entre sí.
    taxable_base = abs((inv.base_total or 0) - total_exempt)
    gross_total = abs(inv.base_total or 0) + abs(vat_details.get("base_tax_amount", 0))

    return {
        "purchase_invoice_type": doc_type,
        "purchase_invoice": inv.name,
        "bill_no": inv.bill_no,
        "bill_control": inv.bill_control,
        "posting_date": inv.bill_date or inv.posting_date,
        "grand_total": gross_total,
        "total": taxable_base,
        "total_exempt": abs(total_exempt),
        "taxes_and_charges_added": abs(vat_details.get("base_tax_amount", 0)),
        # NC: credit_note_no = bill_no para diferenciación en totales y reporte
        "credit_note_no": inv.bill_no if is_nc else inv.get("credit_note_no"),
        # ND: debit_note_no = bill_no para diferenciación en totales y reporte
        "debit_note_no": inv.bill_no if is_nd else inv.get("debit_note_no"),
        "affected_invoice_number": inv.affected_invoice_number,
        "is_return": 1 if is_nc else inv.get("is_return", 0),
        "rate": vat_details.get("rate", 0),
        "withholding_rate": abs(wh_details.get("withholding_rate", 0)),
        "tax_amount_vat": abs(wh_details.get("base_tax_amount", 0)),
        "branch": inv.branch,
    }


# ── Creación desde la factura de compra ─────────────────────────────── #

# Espejo de VAT_ITEM_TOTAL_MAP del JS del comprobante: los totales del
# padre no se recalculan en el servidor, hay que sumarlos al construirlo.
_VAT_TOTAL_ITEM_MAP: dict[str, str] = {
    "totals_grand_total": "grand_total",
    "totals_total_exempt": "total_exempt",
    "totals_total": "total",
    "totals_taxes_and_charges_added": "taxes_and_charges_added",
    "totals_tax_amount_vat": "tax_amount_vat",
}


def _find_voucher_containing_invoice(purchase_invoice: str, docstatus: int) -> dict | None:
    """Retorna {name, voucher_number} del comprobante IVA (con ese docstatus) que ya incluye la factura."""
    rows = frappe.db.sql(
        """
        SELECT parent.name, parent.voucher_number
        FROM `tabVAT Withholding Voucher Item` child
        INNER JOIN `tabVAT Withholding Voucher` parent ON parent.name = child.parent
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
        "VAT Withholding Voucher", voucher["name"],
        voucher.get("voucher_number") or voucher["name"],
    )


@frappe.whitelist()
def make_vat_withholding_voucher(source_name: str, source_doctype: str = "Purchase Invoice") -> dict:
    """Crea, aprueba y emite a HKA un Comprobante de Retención IVA desde la factura de compra o ND.

    Reusa get_valid_invoices para calcular la línea (mismos filtros y montos
    que el flujo del formulario). Si la emisión a HKA falla, el comprobante
    queda aprobado en estado Error y el cron de emisión lo reintenta.
    """
    frappe.has_permission("VAT Withholding Voucher", "create", throw=True)

    invoice = frappe.get_doc(source_doctype, source_name)
    if invoice.docstatus != 1:
        frappe.throw(_("El documento de compra debe estar validado para generar el comprobante de retención."))

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
                _("La factura ya está incluida en el comprobante {0}.").format(
                    _voucher_link(submitted)
                )
            )
        frappe.throw(
            _("La factura no tiene retención de IVA aplicada "
              "(fila 'VAT Withholding' en la tabla de impuestos).")
        )

    # Fail-closed TEMPRANO: si HKA está habilitado globalmente, sin serie digital activa
    # para la sucursal se aborta ANTES de crear el comprobante — no consumir correlativo
    # de la Company ni dejar un comprobante aprobado atascado en Error reintentándose en
    # el cron. No usar `is_hk_enabled_for_company`: ya exige que la sucursal tenga serie
    # activa, así que envolver la validación en ese chequeo la vuelve inalcanzable justo
    # para la sucursal sin serie, que es el caso que debe abortar.
    from frappe.utils import cint
    if cint(frappe.db.get_single_value("TFHKA Settings", "enabled")):
        from l10n_ve.digital_invoice.retention_integration import _validate_digital_series
        series_errors = _validate_digital_series(
            frappe._dict(empresa=invoice.company, branch=invoice.get("branch") or "")
        )
        if series_errors:
            frappe.throw(series_errors[0], title=_("Serie de Facturación No Encontrada"))

    doc = frappe.new_doc("VAT Withholding Voucher")
    doc.empresa = invoice.company
    doc.supplier = invoice.supplier
    doc.branch = invoice.get("branch") or ""
    doc.start_date = posting_date
    doc.end_date = posting_date
    doc.issue_date = nowdate()
    doc.delivery_date = nowdate()

    totals: dict[str, float] = {field: 0.0 for field in _VAT_TOTAL_ITEM_MAP}
    for row in rows:
        doc.append("vat_withholding_voucher_item", row)
        sign = -1 if row.get("is_return") else 1
        for total_field, item_field in _VAT_TOTAL_ITEM_MAP.items():
            totals[total_field] += flt(row.get(item_field)) * sign

    for field, value in totals.items():
        doc.set(field, value)

    doc.insert(ignore_permissions=True)
    doc.flags.ignore_permissions = True
    doc.submit()
    # Persistir creación+aprobación antes de emitir: si la emisión a HKA
    # falla, el comprobante queda aprobado en Error y el cron lo reintenta.
    frappe.db.commit()

    return _emit_vat_voucher(doc.name)


def _emit_vat_voucher(voucher_name: str) -> dict:
    """Emite el comprobante a HKA y arma la respuesta para el formulario."""
    from l10n_ve.digital_invoice.retention_integration import process_retention_voucher

    try:
        emitted = bool(process_retention_voucher(voucher_name))
    except Exception:
        frappe.log_error(
            title=f"Error emitiendo {voucher_name} a HKA desde la factura de compra",
            message=frappe.get_traceback(),
        )
        emitted = False

    info = frappe.db.get_value(
        "VAT Withholding Voucher", voucher_name,
        ["voucher_number", "bill_control"], as_dict=True,
    ) or frappe._dict()

    error_note = None
    if not emitted:
        error_note = frappe.db.get_value(
            "VE Digital Invoice Log",
            {"sales_invoice": voucher_name, "status": "Error",
             "document_type": "VAT Withholding Voucher"},
            "notes", order_by="creation desc",
        )

    return {
        "voucher": voucher_name,
        "emitted": emitted,
        "voucher_number": info.get("voucher_number"),
        "bill_control": info.get("bill_control"),
        "error": error_note,
    }
