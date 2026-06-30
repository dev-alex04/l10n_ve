"""
Parche de migración: Propagar bill_no y bill_control hacia tabGL Entry.
Sincroniza los números de factura y control desde las facturas de venta (Sales Invoice)
y compra (Purchase Invoice) a los asientos contables existentes que aún no los posean.
"""

from __future__ import annotations

import frappe


BATCH_SIZE: int = 500

VOUCHER_SOURCES: list[dict] = [
    {
        "voucher_type": "Sales Invoice",
        "table": "tabSales Invoice",
        "bill_no_field": "bill_no",
        "bill_control_field": "bill_control",
    },
    {
        "voucher_type": "Purchase Invoice",
        "table": "tabPurchase Invoice",
        "bill_no_field": "bill_no",
        "bill_control_field": "bill_control",
    },
]


def execute() -> None:
    """
    Punto de entrada de la migración.
    Itera sobre los tipos de factura y propaga los números a los GL Entries.
    """
    total_updated: int = 0

    for source in VOUCHER_SOURCES:
        updated = _backfill_voucher_type(source)
        total_updated += updated
        frappe.log(
            f"[l10n_ve] {source['voucher_type']}: {updated} GL Entries actualizados."
        )

    frappe.log(f"[l10n_ve] Backfill completado. Total de GL Entries actualizados: {total_updated}")


def _backfill_voucher_type(source: dict) -> int:
    """Ejecuta el backfill para un tipo de comprobante específico de forma paginada."""
    voucher_type: str = source["voucher_type"]
    table: str = source["table"]
    bill_no_field: str = source["bill_no_field"]
    bill_control_field: str = source["bill_control_field"]

    total_updated: int = 0
    limit: int = BATCH_SIZE
    offset: int = 0

    while True:
        invoices: list[dict] = frappe.db.sql(
            f"""
            SELECT
                name,
                `{bill_no_field}`       AS bill_no,
                `{bill_control_field}`  AS bill_control
            FROM `{table}`
            WHERE
                docstatus = 1
                AND (
                    (`{bill_no_field}`      IS NOT NULL AND `{bill_no_field}`      != '')
                    OR
                    (`{bill_control_field}` IS NOT NULL AND `{bill_control_field}` != '')
                )
            ORDER BY name
            LIMIT {limit} OFFSET {offset}
            """,
            as_dict=True,
        )

        if not invoices:
            break

        try:
            updated = _update_gl_entries_batch(voucher_type, invoices)
            total_updated += updated
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            frappe.log_error(message=str(e), title="Backfill GL Entry Bill Fields Error")
            raise e

        if len(invoices) < limit:
            break

        offset += limit

    return total_updated


def _update_gl_entries_batch(voucher_type: str, batch: list[dict]) -> int:
    """Actualiza en lote los GL Entries."""
    if not batch:
        return 0

    voucher_names: list[str] = [inv["name"] for inv in batch]
    placeholders: str = ", ".join(["%s"] * len(voucher_names))

    case_bill_no_parts: list[str] = []
    case_bill_control_parts: list[str] = []
    params_bill_no: list = []
    params_bill_control: list = []

    for inv in batch:
        if inv.get("bill_no"):
            case_bill_no_parts.append("WHEN voucher_no = %s THEN %s")
            params_bill_no.extend([inv["name"], inv["bill_no"]])

        if inv.get("bill_control"):
            case_bill_control_parts.append("WHEN voucher_no = %s THEN %s")
            params_bill_control.extend([inv["name"], inv["bill_control"]])

    if not case_bill_no_parts and not case_bill_control_parts:
        return 0

    set_clauses: list[str] = []
    query_params: list = []

    if case_bill_no_parts:
        set_clauses.append(
            f"bill_no = CASE {' '.join(case_bill_no_parts)} ELSE bill_no END"
        )
        query_params.extend(params_bill_no)

    if case_bill_control_parts:
        set_clauses.append(
            f"bill_control = CASE {' '.join(case_bill_control_parts)} ELSE bill_control END"
        )
        query_params.extend(params_bill_control)

    query_params.append(voucher_type)
    query_params.extend(voucher_names)

    sql: str = f"""
        UPDATE `tabGL Entry`
        SET
            {','.join(set_clauses)}
        WHERE
            voucher_type = %s
            AND voucher_no IN ({placeholders})
            AND is_cancelled = 0
            AND (bill_no IS NULL OR bill_no = '' OR bill_control IS NULL OR bill_control = '')
    """

    frappe.db.sql(sql, query_params)
    return frappe.db._cursor.rowcount

