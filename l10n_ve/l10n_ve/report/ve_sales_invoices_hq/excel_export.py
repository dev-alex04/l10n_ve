# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Exportación a Excel del Reporte HQ de facturas de venta.

Reutiliza la misma estética profesional del Libro de Ventas (``ExcelBuilder``):
encabezado institucional con RIF/dirección, formato numérico de moneda,
estilizado de tabla con filas alternadas, fila de totales con doble borde y
el cuadro de Resumen Fiscal SENIAT al final que cuadra exactamente con el Libro de Ventas.

Se genera en un **worker de fondo** y se entrega como File privado, no en base64
dentro de la respuesta. El motivo es el costo de memoria de ``ExcelBuilder``: usa un
``Workbook()`` normal, que mantiene todo el árbol de celdas vivo. Sobre el caso real
medido —10.712 filas x 38 columnas en ``domina.galanet``— eso son ~107 MB de pico
contra los ~4 MB de un builder ``write_only``. Ese pico dentro de un worker web, con
varios usuarios exportando a la vez, es lo que decide si el servidor aguanta; en la
cola ocurre en un proceso descartable y la request vuelve de inmediato.

Los archivos quedan en disco, así que ``purge_old_hq_excel_exports`` los borra pasados
unos días (mismo criterio que ``purge_old_fiscal_download_zips``): una nueva
exportación los regenera bajo demanda.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime
from frappe.utils.file_manager import save_file

from l10n_ve.l10n_ve.report.sales_book.excel_builder import ExcelBuilder
from l10n_ve.l10n_ve.report.sales_book.sales_book import get_total_row as _sales_book_total_row
from l10n_ve.l10n_ve.report.ve_sales_invoices_hq.ve_sales_invoices_hq import (
    TAXABLE_BASE_FIELDS,
    VAT_AMOUNT_FIELDS,
    get_hq_data,
    sum_consolidated,
)

#: Evento realtime con el que el job avisa al usuario que pidió la exportación.
EVENT_HQ_EXCEL_READY: str = "hq-excel-ready"

#: Días que se conservan los Excel generados antes de que el purge los borre.
EXPORT_RETENTION_DAYS: int = 3


@frappe.whitelist()
def download_hq_excel(filters: str | dict | None = None) -> dict:
    """Encola la generación del Excel del Reporte HQ.

    El endpoint es invocable por sí solo: sin el chequeo de rol, cualquier usuario
    autenticado podría bajarse la facturación completa del período saltándose la
    restricción del reporte.
    """
    frappe.only_for(("VE Sales Book HQ", "System Manager"))

    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})

    # El JS ya lo valida, pero el endpoint acepta filtros arbitrarios y sin company
    # esto sería un frappe.get_doc("Company", None) con traceback en vez de mensaje.
    if not filters.get("company"):
        frappe.throw(_("Seleccione una Compañía para exportar el reporte."))

    frappe.enqueue(
        "l10n_ve.l10n_ve.report.ve_sales_invoices_hq.excel_export.generate_hq_excel_job",
        queue="long",
        # Sin timeout explícito RQ mata el job con el default de la cola, y el caso
        # real proyectado a 30.000 filas ronda los 45s de pura generación.
        timeout=1800,
        filters=filters,
        request_user=frappe.session.user,
    )

    return {"type": "queued", "filename": _build_filename(filters)}


def generate_hq_excel_job(filters: dict, request_user: str) -> None:
    """Arma el Excel, lo guarda como File privado y avisa por realtime al que lo pidió."""
    frappe.set_user(request_user)

    try:
        file_url = _build_and_save(filters)
    except Exception:
        frappe.log_error(
            title=_("Reporte HQ: falló la exportación a Excel"),
            message=frappe.get_traceback(),
        )
        frappe.publish_realtime(
            EVENT_HQ_EXCEL_READY,
            {"error": _("No se pudo generar el archivo. Revise el Log de Errores.")},
            user=request_user,
        )
        return

    frappe.publish_realtime(
        EVENT_HQ_EXCEL_READY,
        {"file_url": file_url, "filename": _build_filename(filters)},
        user=request_user,
    )


def _build_and_save(filters: dict) -> str:
    """Genera el libro y lo persiste como File privado. Devuelve su ``file_url``."""
    # A propósito NO se usa execute(): esa es la función de PANTALLA, donde las filas
    # viajan como lista y se ocultan las columnas numéricas que el período trae vacías.
    # El Excel es el artefacto que contabilidad contrasta contra lo declarado, así que
    # sale del núcleo y lleva SIEMPRE las columnas completas del libro.
    hq: dict = get_hq_data(filters)
    columns: list[dict] = list(hq["columns"])

    # Asegurar la columna de número de operación al inicio
    if not any(c.get("fieldname") == "sequence_number" for c in columns):
        columns.insert(0, {"label": _("Nr Oper."), "fieldname": "sequence_number", "fieldtype": "Int", "width": 60})

    main_data = hq["main_data"]
    adjustment_data = hq["adjustment_data"]

    for i, row in enumerate(main_data + adjustment_data):
        row["sequence_number"] = i + 1

    builder = ExcelBuilder(
        _("REPORTE DE FACTURAS DE VENTA HQ"),
        columns,
        main_data,
        adjustment_data,
        _build_summary_data(main_data),
        _get_company_data(filters["company"]),
        getdate(filters.get("from_date")),
        getdate(filters.get("to_date")),
    )

    file_doc = save_file(
        fname=_build_filename(filters),
        content=builder.build().getvalue(),
        dt="Report",
        dn="ve_sales_invoices_hq",
        folder="Home/Attachments",
        is_private=1,
    )
    return file_doc.file_url


def _build_summary_data(main_data: list[dict]) -> dict:
    """Totales de la fila final del Excel.

    ``get_total_row`` es del Libro de Ventas y arma un dict fijo que no incluye las dos
    columnas consolidadas del HQ, así que salían vacías justo en la fila de Totales. Se
    derivan de los mismos totales por alícuota para que cuadren con las columnas de
    arriba por construcción, sin recorrer las filas de nuevo.
    """
    totals: dict = _sales_book_total_row(main_data)
    if not totals:
        return totals

    totals["taxable_amount"] = sum_consolidated(totals, TAXABLE_BASE_FIELDS)
    totals["total_vat"] = sum_consolidated(totals, VAT_AMOUNT_FIELDS)
    return totals


def _get_company_data(company: str) -> dict:
    address_name = frappe.db.get_value("Company", company, "custom_company_primary_address")
    company_address: str = (
        frappe.db.get_value("Address", address_name, "address_line1")
        if address_name else None
    ) or _("Dirección no disponible")

    company_doc = frappe.get_cached_doc("Company", company)
    return {
        "company_name": company_doc.company_name,
        "tax_id": company_doc.tax_id,
        "is_special_taxpayer": company_doc.is_special_taxpayer,
        "address": company_address,
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


def purge_old_hq_excel_exports(retention_days: int = EXPORT_RETENTION_DAYS) -> None:
    """Tarea programada: borra los Excel del Reporte HQ ya vencidos.

    El export dejó de viajar en base64 y ahora queda en disco, así que hay que
    limpiarlo. Mismo criterio que ``purge_old_fiscal_download_zips``: se borra el
    archivo pasados ``retention_days`` días y una nueva exportación lo regenera.
    """
    from frappe.utils import add_days, nowdate

    cutoff = add_days(nowdate(), -retention_days)
    stale = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Report",
            "attached_to_name": "ve_sales_invoices_hq",
            "creation": ["<", cutoff],
        },
        pluck="name",
    )

    deleted = 0
    for name in stale:
        try:
            frappe.delete_doc("File", name, ignore_permissions=True, delete_permanently=True)
            frappe.db.commit()
            deleted += 1
        except Exception:
            # Un archivo que no se puede borrar no debe abortar el resto del lote.
            frappe.db.rollback()
            frappe.log_error(
                title=_("Reporte HQ: no se pudo borrar el Excel vencido {0}").format(name),
                message=frappe.get_traceback(),
            )

    if deleted:
        frappe.logger("l10n_ve").info(
            f"purge_old_hq_excel_exports: {deleted} Excel borrados de {len(stale)} "
            f"con más de {retention_days} días."
        )
