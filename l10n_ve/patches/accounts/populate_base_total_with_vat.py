"""
Parche de migración: Poblar base_total_with_vat en documentos históricos.

Negocio: El campo "Total Base + IVA (Bs)" fue agregado para que el equipo
financiero visualice el monto antes de retenciones. Este parche llena el
valor para todos los documentos aprobados que no lo tenían.

Lógica: Para cada documento, toma el base_total de la primera fila de
impuestos con charge_type = 'VAT'. Si no existe fila VAT, usa base_net_total.
"""

import frappe


def execute() -> None:
    _update_doctype("Sales Invoice")
    _update_doctype("VE Sales Credit Note")
    _update_doctype("VE Sales Debit Note")


def _update_doctype(doctype: str) -> None:
    """Actualiza base_total_with_vat para un DocType específico."""
    table_name: str = f"tab{doctype}"

    if not frappe.db.has_column(doctype, "base_total_with_vat"):
        return

    # Actualizar con base_total de la fila VAT
    affected: int = frappe.db.sql(
        f"""
        UPDATE `{table_name}` doc
        INNER JOIN `tabSales Taxes and Charges` stc
            ON stc.parent = doc.name
            AND stc.parenttype = %(doctype)s
            AND stc.charge_type = 'VAT'
            AND stc.idx = (
                SELECT MIN(stc2.idx)
                FROM `tabSales Taxes and Charges` stc2
                WHERE stc2.parent = doc.name
                    AND stc2.parenttype = %(doctype)s
                    AND stc2.charge_type = 'VAT'
            )
        SET doc.base_total_with_vat = stc.base_total
        WHERE doc.docstatus = 1
            AND IFNULL(doc.base_total_with_vat, 0) = 0
        """,
        {"doctype": doctype},
    )

    # Fallback: documentos sin fila VAT → usar base_net_total
    frappe.db.sql(
        f"""
        UPDATE `{table_name}`
        SET base_total_with_vat = base_net_total
        WHERE docstatus = 1
            AND IFNULL(base_total_with_vat, 0) = 0
        """
    )

    frappe.db.commit()

    count: int = frappe.db.count(
        doctype,
        {"docstatus": 1, "base_total_with_vat": (">", 0)},
    )
    frappe.log(f"[l10n_ve] base_total_with_vat poblado en {count} registros de {doctype}")
