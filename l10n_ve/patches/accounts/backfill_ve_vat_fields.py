"""
Parche de migración: Poblar campos dedicados de IVA en documentos históricos.

Negocio: Se crearon los campos ve_vat_amount, base_ve_vat_amount, ve_total_with_vat
y se actualizó la lógica de base_total_with_vat para que refleje el IVA bruto
real del documento (sin retenciones), permitiendo mostrar el IVA real en pantalla
sin alterar los campos nativos de ERPNext que controlan la contabilidad y cobranzas.

Lógica:
- ve_vat_amount / base_ve_vat_amount: suma de filas VAT o Add de la tabla de impuestos.
- ve_total_with_vat: net_total + ve_vat_amount.
- base_total_with_vat: base_net_total + base_ve_vat_amount.

Aplica a Sales Invoice, VE Sales Credit Note y VE Sales Debit Note.
"""

import frappe


def execute() -> None:
    _update_doctype("Sales Invoice")
    _update_doctype("VE Sales Credit Note")
    _update_doctype("VE Sales Debit Note")


def _update_doctype(doctype: str) -> None:
    """Pobla ve_vat_amount, base_ve_vat_amount, ve_total_with_vat y base_total_with_vat."""
    table_name: str = f"tab{doctype}"

    has_ve_vat = frappe.db.has_column(doctype, "ve_vat_amount")
    has_base_ve_vat = frappe.db.has_column(doctype, "base_ve_vat_amount")
    has_ve_total = frappe.db.has_column(doctype, "ve_total_with_vat")
    has_base_total_with_vat = frappe.db.has_column(doctype, "base_total_with_vat")

    if not any([has_ve_vat, has_base_ve_vat, has_ve_total, has_base_total_with_vat]):
        frappe.log(f"[l10n_ve] {doctype}: Ningún campo de IVA dedicado existe aún, se omite.")
        return

    # Construir SET dinámico según los campos que existen
    set_clauses = []
    if has_ve_vat:
        set_clauses.append("doc.ve_vat_amount = ROUND(IFNULL(vat.vat_ref, 0), 2)")
    if has_base_ve_vat:
        set_clauses.append("doc.base_ve_vat_amount = ROUND(IFNULL(vat.vat_bs, 0), 2)")
    if has_ve_total:
        set_clauses.append("doc.ve_total_with_vat = ROUND(doc.net_total + IFNULL(vat.vat_ref, 0), 2)")
    if has_base_total_with_vat:
        set_clauses.append("doc.base_total_with_vat = ROUND(doc.base_net_total + IFNULL(vat.vat_bs, 0), 2)")

    if not set_clauses:
        return

    set_sql = ", ".join(set_clauses)

    # UPDATE con subquery que agrega IVA bruto (VAT o Add) por documento
    frappe.db.sql(
        f"""
        UPDATE `{table_name}` doc
        LEFT JOIN (
            SELECT
                stc.parent,
                SUM(
                    CASE WHEN stc.charge_type = 'VAT' OR stc.add_deduct_tax = 'Add'
                         THEN stc.tax_amount ELSE 0 END
                ) AS vat_ref,
                SUM(
                    CASE WHEN stc.charge_type = 'VAT' OR stc.add_deduct_tax = 'Add'
                         THEN stc.base_tax_amount ELSE 0 END
                ) AS vat_bs
            FROM `tabSales Taxes and Charges` stc
            WHERE stc.parenttype = %(doctype)s
            GROUP BY stc.parent
        ) vat ON vat.parent = doc.name
        SET {set_sql}
        WHERE doc.docstatus IN (0, 1)
        """,
        {"doctype": doctype},
    )

    frappe.db.commit()

    count: int = frappe.db.sql(
        f"SELECT COUNT(*) FROM `{table_name}` WHERE docstatus IN (0, 1) AND IFNULL(base_total_with_vat, 0) > 0"
    )[0][0]
    frappe.log(f"[l10n_ve] Campos IVA dedicados poblados en {count} registros de {doctype}")
