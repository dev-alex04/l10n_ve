# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Exportación a Excel del Reporte HQ de facturas de venta.

Se genera **íntegramente en memoria** (``BytesIO``) y se devuelve al navegador
en base64: nunca se escribe un archivo en el disco del servidor, así que no hay
nada que limpiar después ni basura acumulándose entre descargas.

Dos decisiones tomadas a partir de medir el caso real (10.712 filas x 36
columnas en ``domina.galanet``):

* ``write_only=True`` en openpyxl. El modo normal mantiene todo el árbol de
  celdas vivo: **106,9 MB de pico de RAM contra 4,0 MB** (27x) y además tarda
  más (22,0s contra 14,5s). Con varios usuarios exportando a la vez, esa
  diferencia es la que decide si el servidor aguanta.
* **base64 dentro de la respuesta JSON**, como el resto de la casa
  (``isp_control_dashboard``, ``sales_book``). El archivo resultante es chico
  —1,32 MB para 10.712 filas, ~3,7 MB proyectado a 30.000— así que no hace
  falta streaming binario y se gana el manejo de errores y el indicador de
  progreso del lado JS.

Lo que sí pesa es el TIEMPO de generación (~15s para 10.712 filas, ~45s
proyectado a 30.000), por eso el botón muestra un indicador mientras trabaja.
"""

import base64
from io import BytesIO

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq import execute

SHEET_DATA: str = "Facturas"
SHEET_SUMMARY: str = "Resumen"

HEADER_FILL: PatternFill = PatternFill("solid", fgColor="2A3346")
HEADER_FONT: Font = Font(bold=True, color="FFFFFF")
HEADER_ALIGN: Alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Ancho por tipo de columna: evita el Excel ilegible de columnas de 8 caracteres.
WIDTH_BY_FIELDTYPE: dict = {
    "Currency": 18,
    "Float": 14,
    "Int": 10,
    "Date": 12,
    "Data": 20,
}
DEFAULT_WIDTH: int = 18
MAX_WIDTH: int = 42


@frappe.whitelist()
def download_hq_excel(filters: str | dict | None = None) -> dict:
    """Genera el Excel del Reporte HQ y lo devuelve para descarga directa.

    El endpoint es invocable por sí solo: sin el chequeo de rol, cualquier
    usuario autenticado podría bajarse la facturación completa del período
    saltándose la restricción del reporte.
    """
    frappe.only_for(("VE Sales Book HQ", "System Manager"))

    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

    columns, data, _message, _chart, report_summary = execute(filters)

    output: BytesIO = BytesIO()
    try:
        workbook = _build_workbook(columns, data, report_summary)
        workbook.save(output)
        content: bytes = output.getvalue()
    finally:
        # Liberar el buffer sin esperar al recolector: en una exportación grande
        # son megabytes retenidos por el worker.
        output.close()

    return {
        "type": "download",
        "filename": _build_filename(filters),
        "filecontent": base64.b64encode(content).decode("ascii"),
    }


def _build_workbook(columns: list[dict], data: list[dict], report_summary: list[dict]) -> Workbook:
    """Arma el libro en modo write_only (ver nota de memoria en el módulo)."""
    workbook = Workbook(write_only=True)

    sheet = workbook.create_sheet(SHEET_DATA)
    fieldnames: list[str] = [c.get("fieldname") for c in columns if c.get("fieldname")]

    _apply_column_widths(sheet, columns, fieldnames)

    # OJO: en write_only, freeze_panes debe fijarse ANTES de escribir filas
    # (si se pone después no queda en el archivo y el encabezado se pierde al
    # hacer scroll, que con 10.000+ filas vuelve el Excel incómodo de revisar).
    sheet.freeze_panes = "A2"

    sheet.append([_header_cell(sheet, c) for c in columns if c.get("fieldname")])
    for row in data:
        sheet.append([row.get(fieldname) for fieldname in fieldnames])

    # El autofiltro sí se fija al final: necesita el total de filas escritas.
    if fieldnames:
        sheet.auto_filter.ref = "A1:{0}{1}".format(
            get_column_letter(len(fieldnames)), len(data) + 1
        )

    _append_summary_sheet(workbook, report_summary)
    return workbook


def _header_cell(sheet, column: dict):
    cell = WriteOnlyCell(sheet, value=column.get("label") or column.get("fieldname"))
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.alignment = HEADER_ALIGN
    return cell


def _apply_column_widths(sheet, columns: list[dict], fieldnames: list[str]) -> None:
    for index, column in enumerate(c for c in columns if c.get("fieldname")):
        # Ojo: el 'width' de un reporte Frappe puede ser un entero (píxeles) o
        # la cadena "auto"; en ese caso se cae al ancho por tipo de campo.
        width = _as_number(column.get("width")) or WIDTH_BY_FIELDTYPE.get(
            column.get("fieldtype"), DEFAULT_WIDTH
        )
        # Excel mide en caracteres, no en píxeles: se aproxima y se acota para
        # que no salgan columnas absurdas.
        if width > 60:
            width = width / 7
        sheet.column_dimensions[get_column_letter(index + 1)].width = min(
            max(int(width), 10), MAX_WIDTH
        )


def _as_number(value) -> float:
    """Devuelve el ancho como número, o 0 si no lo es (p.ej. ``"auto"``)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _append_summary_sheet(workbook: Workbook, report_summary: list[dict]) -> None:
    """Hoja con los totales del reporte.

    Es lo que contabilidad compara contra el libro declarado, así que va en el
    archivo y no solo en pantalla.
    """
    if not report_summary:
        return

    sheet = workbook.create_sheet(SHEET_SUMMARY)
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 24

    header = [
        _header_cell(sheet, {"label": _("Concepto")}),
        _header_cell(sheet, {"label": _("Monto")}),
    ]
    sheet.append(header)

    for item in report_summary:
        if not isinstance(item, dict):
            continue
        sheet.append([item.get("label"), item.get("value")])


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
