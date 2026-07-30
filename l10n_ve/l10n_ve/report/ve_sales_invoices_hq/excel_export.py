# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Exportación a Excel del Reporte HQ de facturas de venta.

Reutiliza la misma estética profesional del Libro de Ventas (``ExcelBuilder``):
encabezado institucional con RIF/dirección, formato numérico de moneda,
estilizado de tabla con filas alternadas, fila de totales con doble borde y
el cuadro de Resumen Fiscal SENIAT al final que cuadra exactamente con el Libro de Ventas.
"""

import base64
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from l10n_ve.l10n_ve.report.sales_book.excel_builder import ExcelBuilder
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_total_row as _sales_book_total_row
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq import get_hq_data


@frappe.whitelist()
def download_hq_excel(filters: str | dict | None = None) -> dict:
    """Genera el Excel del Reporte HQ con la estética del Libro de Ventas y lo devuelve en base64."""
    frappe.only_for(("VE Sales Book HQ", "System Manager"))

    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

    hq: dict = get_hq_data(filters)
    columns: list[dict] = list(hq["columns"])

    # Asegurar la columna de número de operación al inicio
    if not any(c.get("fieldname") == "sequence_number" for c in columns):
        columns.insert(0, {"label": _("Nr Oper."), "fieldname": "sequence_number", "fieldtype": "Int", "width": 60})

    main_data = hq["main_data"]
    adjustment_data = hq["adjustment_data"]

    for i, row in enumerate(main_data + adjustment_data):
        row["sequence_number"] = i + 1

    summary_data = _sales_book_total_row(main_data)

    company_doc = frappe.get_doc("Company", filters.get("company"))
    address_name = company_doc.get("custom_company_primary_address")
    company_address: str = (
        frappe.db.get_value("Address", address_name, "address_line1")
        if address_name else _("Dirección no disponible")
    )

    company_data: dict = {
        "company_name": company_doc.company_name,
        "tax_id": company_doc.tax_id,
        "is_special_taxpayer": company_doc.is_special_taxpayer,
        "address": company_address,
    }

    from_date = frappe.utils.getdate(filters.get("from_date"))
    to_date = frappe.utils.getdate(filters.get("to_date"))

    builder = ExcelBuilder(
        _("REPORTE DE FACTURAS DE VENTA HQ"),
        columns,
        main_data,
        adjustment_data,
        summary_data,
        company_data,
        from_date,
        to_date,
    )

    excel_stream = builder.build()
    base64_content = base64.b64encode(excel_stream.getvalue()).decode("ascii")

    return {
        "type": "download",
        "filename": _build_filename(filters),
        "filecontent": base64_content,
    }


def _build_filename(filters: dict) -> str:
    """``Facturas_Venta_HQ_20260201_20260731.xlsx``."""
    parts: list[str] = ["Facturas_Venta_HQ"]
    for key in ("from_date", "to_date"):
        value = filters.get(key)
        if value:
            parts.append(getdate(value).strftime("%Y%m%d"))
    if len(parts) == 1:
        parts.append(now_datetime().strftime("%Y%m%d"))
    return "{0}.xlsx".format("_".join(parts))

