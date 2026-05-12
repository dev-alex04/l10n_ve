"""
Builder de Excel con formato SENIAT para el Libro de Compras.

Replica la estructura del modelo oficial: ~38 columnas (A-AL),
encabezados multinivel con merges, y agrupación por tipo de compra
(Importación, Nacional, Decreto 3.085).
"""
import frappe
from frappe import _
import base64
import json
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from frappe.utils import flt, getdate

from l10n_ve.l10n_ve.report.purchase_book.purchase_book import (
    execute, get_totals_from_data,
)


# ──────────────────────────────────────────────────────────────────────
#  Definición de columnas formato SENIAT
# ──────────────────────────────────────────────────────────────────────

SENIAT_COLUMNS: list[dict] = [
    # A: Nr Oper. (se inyecta en create_seniat_excel_file)
    # B-E: Datos del documento
    {"label": "Fecha Factura", "fieldname": "bill_date", "fieldtype": "Data", "width": 12},
    {"label": "RIF", "fieldname": "tax_id", "fieldtype": "Data", "width": 14},
    {"label": "Nombre o Razón Social", "fieldname": "supplier_name", "fieldtype": "Data", "width": 30},
    {"label": "T.Proveedor", "fieldname": "supplier_type", "fieldtype": "Data", "width": 6},
    # F-G: Importación
    {"label": "Nro. Planilla Importación", "fieldname": "nro_planilla", "fieldtype": "Data", "width": 10},
    {"label": "Nro. Expediente Importación", "fieldname": "nro_expediente_importacion", "fieldtype": "Data", "width": 10},
    # H-K: Documento
    {"label": "Nro. Factura", "fieldname": "bill_no", "fieldtype": "Data", "width": 12},
    {"label": "Nro. Control", "fieldname": "bill_control", "fieldtype": "Data", "width": 12},
    {"label": "Nro. Nota de Débito", "fieldname": "debit_note_no", "fieldtype": "Data", "width": 10},
    {"label": "Nro. Nota de Crédito", "fieldname": "credit_note_no", "fieldtype": "Data", "width": 10},
    # L: Tipo transacción
    {"label": "Tipo Tr", "fieldname": "transaction_type", "fieldtype": "Data", "width": 6},
    # M: Factura afectada
    {"label": "Nro. Factura Afectada", "fieldname": "affected_invoice_number", "fieldtype": "Data", "width": 12},
    # N: Total compras
    {"label": "Total Compras Incl. IVA", "fieldname": "grand_total", "fieldtype": "Currency", "width": 16},
    # O-Q: Compras no gravadas
    {"label": "No Sujetas", "fieldname": "total_not_subject", "fieldtype": "Currency", "width": 12},
    {"label": "Exentas", "fieldname": "total_exempt", "fieldtype": "Currency", "width": 12},
    {"label": "Exoneradas", "fieldname": "total_exonerated", "fieldtype": "Currency", "width": 12},
    # R-T: Compras de Importación
    {"label": "Base Import.", "fieldname": "base_importacion", "fieldtype": "Currency", "width": 14},
    {"label": "% Import.", "fieldname": "rate_importacion", "fieldtype": "Percent", "width": 6},
    {"label": "Impuesto Import.", "fieldname": "impuesto_importacion", "fieldtype": "Currency", "width": 14},
    # U-W: Compras Nacionales
    {"label": "Base Nacional", "fieldname": "base_nacional", "fieldtype": "Currency", "width": 16},
    {"label": "% Nacional", "fieldname": "rate_nacional", "fieldtype": "Percent", "width": 6},
    {"label": "Impuesto Nacional", "fieldname": "impuesto_nacional", "fieldtype": "Currency", "width": 16},
    # X-Z: Compras Nacionales Decreto 3.085 (Grupo 1 — Reducida)
    {"label": "Base Dto.3085 Red.", "fieldname": "base_dto3085_red", "fieldtype": "Currency", "width": 14},
    {"label": "% Dto.3085 Red.", "fieldname": "rate_dto3085_red", "fieldtype": "Percent", "width": 6},
    {"label": "Impuesto Dto.3085 Red.", "fieldname": "impuesto_dto3085_red", "fieldtype": "Currency", "width": 14},
    # AA-AC: Compras Nacionales Decreto 3.085 (Grupo 2 — Adicional)
    {"label": "Base Dto.3085 Adic.", "fieldname": "base_dto3085_adic", "fieldtype": "Currency", "width": 14},
    {"label": "% Dto.3085 Adic.", "fieldname": "rate_dto3085_adic", "fieldtype": "Percent", "width": 6},
    {"label": "Impuesto Dto.3085 Adic.", "fieldname": "impuesto_dto3085_adic", "fieldtype": "Currency", "width": 14},
    # AD: Ajustes / Créditos fiscales
    {"label": "Créditos Fiscales", "fieldname": "creditos_fiscales", "fieldtype": "Currency", "width": 12},
    # AE-AG: Retención IVA
    {"label": "Fecha Comprobante", "fieldname": "fecha_entrega", "fieldtype": "Data", "width": 12},
    {"label": "Nro. Comprobante Retención", "fieldname": "nro_comprobante_retencion", "fieldtype": "Data", "width": 18},
    {"label": "% Ret.", "fieldname": "porcentaje_ret", "fieldtype": "Percent", "width": 6},
    # AH-AI: IVA Retenido e ISLR
    {"label": "IVA Retenido por el Comprador", "fieldname": "taxes_and_charges_deducted", "fieldtype": "Currency", "width": 16},
    {"label": "Ret. ISLR", "fieldname": "ret_islr_monto", "fieldtype": "Currency", "width": 12},
]


def _post_process_seniat_rows(
    data: list[dict],
    general_rate: float,
    reduced_rate: float,
    additional_rate: float,
) -> list[dict]:
    """Transforma las filas del SQL al esquema de columnas SENIAT para compras."""
    for row in data:
        # Compras Nacionales (tasa general) → U-W
        row["base_nacional"] = flt(row.get("base_general"))
        row["impuesto_nacional"] = flt(row.get("impuesto_general"))
        row["rate_nacional"] = general_rate / 100 if row["base_nacional"] else 0

        # Compras Nacionales Dto 3.085 Reducida → X-Z
        row["base_dto3085_red"] = flt(row.get("base_reducida"))
        row["impuesto_dto3085_red"] = flt(row.get("impuesto_reducida"))
        row["rate_dto3085_red"] = reduced_rate / 100 if row["base_dto3085_red"] else 0

        # Compras Nacionales Dto 3.085 Adicional → AA-AC
        row["base_dto3085_adic"] = flt(row.get("base_adicional"))
        row["impuesto_dto3085_adic"] = flt(row.get("impuesto_adicional"))
        row["rate_dto3085_adic"] = additional_rate / 100 if row["base_dto3085_adic"] else 0

        # Columnas vacías (N/A para compras nacionales)
        row["total_not_subject"] = 0
        row["total_exonerated"] = 0
        row["base_importacion"] = 0
        row["rate_importacion"] = 0
        row["impuesto_importacion"] = 0
        row["creditos_fiscales"] = 0
        # ret_islr_monto ya viene de la query SQL con el monto real

    return data


# ──────────────────────────────────────────────────────────────────────
#  Builder de Excel formato SENIAT
# ──────────────────────────────────────────────────────────────────────

class SeniatPurchaseExcelBuilder:
    """Genera el Excel de Libro de Compras con formato SENIAT."""

    def __init__(
        self,
        columns: list[dict],
        data: list[dict],
        summary_data: dict,
        company_data: dict,
        from_date,
        to_date,
    ):
        self.columns = columns
        self.data = data
        self.summary_data = summary_data
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date

        self.wb = Workbook()
        self.ws = self.wb.active
        self.ws.title = "Libro de Compras"

        self.font_default = Font(name="Calibri", size=8)
        self.font_header = Font(name="Calibri", size=8, bold=True)
        self.font_title = Font(name="Calibri", size=10, bold=True)
        self.border = Border(
            left=Side("thin"), right=Side("thin"),
            top=Side("thin"), bottom=Side("thin"),
        )
        self.align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
        self.align_right = Alignment(horizontal="right", vertical="center")
        self.num_fmt = "#,##0.00"

    # ── Encabezado del reporte ──

    def _add_report_header(self) -> int:
        ws = self.ws
        right_col: int = 12

        title_cell = ws.cell(row=1, column=1, value=_("Libro de Compras Fiscal"))
        title_cell.font = Font(name="Calibri", size=10, bold=True, underline="single")

        ws.cell(row=3, column=1, value=_("Nombre o Razón Social:")).font = self.font_header
        ws.cell(row=4, column=1, value=self.company_data.get("company_name", "")).font = self.font_default

        ws.cell(row=3, column=right_col,
                value=_("Número de Registro de Información Fiscal (RIF):")).font = self.font_header
        ws.cell(row=4, column=right_col,
                value=self.company_data.get("tax_id", "")).font = self.font_default

        ws.cell(row=6, column=1, value=_("Dirección:")).font = self.font_header
        ws.cell(row=7, column=1, value=self.company_data.get("address", "")).font = self.font_default

        ws.cell(row=6, column=right_col, value=_("Tipo de Contribuyente:")).font = self.font_header
        taxpayer_type: str = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("ORDINARIO")
        ws.cell(row=7, column=right_col, value=taxpayer_type).font = self.font_default

        ws.cell(row=9, column=1, value=_("Período Fiscal:")).font = self.font_header
        ws.cell(row=10, column=1, value="{0} - {1}".format(
            self.from_date.strftime("%d/%m/%Y"),
            self.to_date.strftime("%d/%m/%Y"),
        )).font = self.font_default

        return 12

    # ── Headers multinivel (3 filas) ──

    def _build_multi_level_headers(self, start_row: int) -> int:
        ws = self.ws
        r1, r2, r3 = start_row, start_row + 1, start_row + 2

        def _cell(row, col, val):
            c = ws.cell(row=row, column=col, value=val)
            c.font = self.font_header
            c.border = self.border
            c.alignment = self.align_center
            return c

        def _merge(row1, col1, row2, col2, val):
            _cell(row1, col1, val)
            if row1 != row2 or col1 != col2:
                ws.merge_cells(start_row=row1, start_column=col1,
                               end_row=row2, end_column=col2)

        # Col A: Nº oper (3 filas)
        _merge(r1, 1, r3, 1, _("Nº oper"))

        # Cols B-M: "Factura o Documento Equivalente"
        _merge(r1, 2, r1, 13, _("Factura o Documento Equivalente"))
        _merge(r2, 2, r3, 2, _("Fecha\nFactura"))
        _merge(r2, 3, r3, 3, _("Número\nRIF"))
        _merge(r2, 4, r3, 4, _("Nombre o Razón Social"))
        _merge(r2, 5, r3, 5, _("T.Proveedor"))
        _merge(r2, 6, r3, 6, _("Nro. Planilla\nImportación"))
        _merge(r2, 7, r3, 7, _("Nro. Expediente\nImportación"))
        _merge(r2, 8, r3, 8, _("Número de\nFactura"))
        _merge(r2, 9, r3, 9, _("Número de\nControl"))
        _merge(r2, 10, r3, 10, _("Número de\nNota de Débito"))
        _merge(r2, 11, r3, 11, _("Número de\nNota de Crédito"))
        _merge(r2, 12, r3, 12, _("Tipo\nTr"))
        _merge(r2, 13, r3, 13, _("Número de\nFactura Afectada"))

        # Col N: Total Compras (3 filas)
        _merge(r1, 14, r1, 14, _("Total Compras"))
        _merge(r2, 14, r3, 14, _("Incluyendo\nI.V.A"))

        # Cols O-Q: "Compras no Gravadas y/o sin Derecho a CF"
        _merge(r1, 15, r1, 17, _("Compras no Gravadas y/o sin Derecho a CF"))
        _merge(r2, 15, r3, 15, _("Compras No\nSujetas"))
        _merge(r2, 16, r3, 16, _("Compras\nExentas"))
        _merge(r2, 17, r3, 17, _("Compras\nExoneradas"))

        # Cols R-AC: "Compras con Derecho a Crédito" (un solo merge nivel 1)
        _merge(r1, 18, r1, 29, _("Compras con Derecho a Crédito"))
        # R-T: Compras de Importación (nivel 2)
        _merge(r2, 18, r2, 20, _("Compras de Importación"))
        _cell(r3, 18, _("Base")); _cell(r3, 19, _("%")); _cell(r3, 20, _("Impuesto"))
        # U-W: Compras Nacionales (nivel 2)
        _merge(r2, 21, r2, 23, _("Compras Nacionales"))
        _cell(r3, 21, _("Base")); _cell(r3, 22, _("%")); _cell(r3, 23, _("Impuesto"))
        # X-Z: Compras Nacionales Según Decreto 3.085 (nivel 2)
        _merge(r2, 24, r2, 26, _("Compras Nacionales Según Decreto 3.085"))
        _cell(r3, 24, _("Base")); _cell(r3, 25, _("%")); _cell(r3, 26, _("Impuesto"))
        # AA-AC: Compras Nacionales Según Decreto 3.085 (nivel 2)
        _merge(r2, 27, r2, 29, _("Compras Nacionales Según Decreto 3.085"))
        _cell(r3, 27, _("Base")); _cell(r3, 28, _("%")); _cell(r3, 29, _("Impuesto"))

        # Col AD: Ajustes / Créditos Fiscales
        _cell(r1, 30, _("Ajustes"))
        _merge(r2, 30, r3, 30, _("Créditos\nFiscales"))

        # Col AE: Fecha Comprobante
        _cell(r1, 31, _("Fecha"))
        _merge(r2, 31, r3, 31, _("Comprobante\nde Retención"))

        # Col AF: Nro. Comprobante (3 filas merge)
        _merge(r1, 32, r3, 32, _("Nro. Comprobante de Retención"))

        # Col AG: % Retención
        _merge(r1, 33, r3, 33, _("%"))

        # Col AH: IVA Retenido
        _cell(r1, 34, _("IVA"))
        _merge(r2, 34, r3, 34, _("Retenido por\nel Comprador"))

        # Col AI: Ret. ISLR
        _merge(r1, 35, r3, 35, _("Ret. ISLR"))

        for r in (r1, r2, r3):
            ws.row_dimensions[r].height = 25

        for i, col_def in enumerate(self.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = col_def.get("width", 10)

        return r3

    # ── Filas de datos ──

    def _write_data_rows(self, start_row: int) -> int:
        row_idx: int = start_row + 1
        for row_data in self.data:
            for col_idx, col_def in enumerate(self.columns, start=1):
                value = row_data.get(col_def["fieldname"])
                cell = self.ws.cell(row=row_idx, column=col_idx, value=value)
                cell.font = self.font_default
                cell.border = self.border

                if isinstance(value, (int, float)):
                    cell.number_format = "0" if col_def["fieldname"] == "sequence_number" else self.num_fmt
                    cell.alignment = self.align_right
                else:
                    cell.alignment = self.align_left

            row_idx += 1
        return row_idx - 1

    # ── Fila de totales ──

    def _write_totals_row(self, after_row: int) -> int:
        row_idx: int = after_row + 2
        currency_fields: list[str] = [
            col["fieldname"] for col in self.columns
            if col["fieldtype"] == "Currency"
        ]
        totals: dict = {f: 0.0 for f in currency_fields}

        for row in self.data:
            for field in currency_fields:
                totals[field] = flt(totals[field]) + flt(row.get(field, 0))

        label_cell = self.ws.cell(row=row_idx, column=1, value=_("TOTALES"))
        label_cell.font = self.font_header
        label_cell.border = self.border
        self.ws.merge_cells(start_row=row_idx, start_column=1,
                            end_row=row_idx, end_column=2)

        for col_idx, col_def in enumerate(self.columns, start=1):
            fieldname: str = col_def["fieldname"]
            if fieldname in totals:
                cell = self.ws.cell(row=row_idx, column=col_idx, value=totals[fieldname])
                cell.font = self.font_header
                cell.border = self.border
                cell.number_format = self.num_fmt
                cell.alignment = self.align_right
            elif col_idx > 2:
                cell = self.ws.cell(row=row_idx, column=col_idx)
                cell.border = self.border

        return row_idx

    # ── Tabla resumen ──

    def _build_summary_table(self, start_row: int) -> int:
        ws = self.ws
        r: int = start_row + 2
        sc: int = 13  # columna M

        ws.cell(row=r, column=sc, value=_("RESUMEN")).font = Font(bold=True, size=12)
        r += 1

        headers = [_("Concepto"), _("Base Imponible"), _("Crédito Fiscal"), _("Retención")]
        for i, h in enumerate(headers):
            c = ws.cell(row=r, column=sc + i, value=h)
            c.font = self.font_header
            c.border = self.border
        r += 1

        rows_data = [
            (_("Compras no gravadas y/o sin derecho a crédito fiscal"),
             flt(self.summary_data.get("total_exempt")), 0, 0),
            (_("Importaciones gravadas por alícuota general"), 0, 0, 0),
            (_(" Importaciones gravadas por alícuota general más adicional"), 0, 0, 0),
            (_("Importaciones gravadas por alícuota reducida"), 0, 0, 0),
            (_("Compras Internas (tasa general)"),
             flt(self.summary_data.get("base_general")),
             flt(self.summary_data.get("impuesto_general")),
             flt(self.summary_data.get("taxes_and_charges_deducted"))),
            (_("Compras Internas (tasa general + adicional)"),
             flt(self.summary_data.get("base_adicional")),
             flt(self.summary_data.get("impuesto_adicional")), 0),
            (_("Compras Internas (tasa reducida)"),
             flt(self.summary_data.get("base_reducida")),
             flt(self.summary_data.get("impuesto_reducida")), 0),
        ]

        for concept, base, iva, ret in rows_data:
            ws.cell(row=r, column=sc, value=concept).font = self.font_default
            ws.cell(row=r, column=sc, value=concept).border = self.border
            for j, val in enumerate([base, iva, ret], start=1):
                c = ws.cell(row=r, column=sc + j, value=val)
                c.font = self.font_default
                c.number_format = self.num_fmt
                c.border = self.border
            r += 1

        # Fila de totales del resumen
        ws.cell(row=r, column=sc, value=_("Total")).font = self.font_header
        for j, val in enumerate([
            sum(row[1] for row in rows_data),
            sum(row[2] for row in rows_data),
            sum(row[3] for row in rows_data),
        ], start=1):
            c = ws.cell(row=r, column=sc + j, value=val)
            c.font = self.font_header
            c.number_format = self.num_fmt
            c.border = self.border

        return r

    # ── Orquestador ──

    def build(self) -> BytesIO:
        header_end: int = self._add_report_header()
        headers_row: int = self._build_multi_level_headers(header_end)
        last_data: int = self._write_data_rows(headers_row)
        totals_row: int = self._write_totals_row(last_data)
        self._build_summary_table(totals_row)

        stream = BytesIO()
        self.wb.save(stream)
        stream.seek(0)
        return stream


# ──────────────────────────────────────────────────────────────────────
#  Helpers compartidos
# ──────────────────────────────────────────────────────────────────────

def build_purchase_excel_filename(company_name: str, from_date, to_date) -> str:
    """Genera nombre de archivo consistente para ambos formatos."""
    safe_company: str = company_name.replace("/", "-").replace("\\", "-")
    return f"Libro de Compras - {safe_company} - {from_date.strftime('%d-%m-%Y')} al {to_date.strftime('%d-%m-%Y')}.xlsx"


def prepare_purchase_excel_export(filters: dict) -> dict:
    """Prepara los datos comunes para ambos formatos de exportación Excel."""
    if isinstance(filters, str):
        filters = json.loads(filters)

    _columns, data, _msg, _chart, _report_summary = execute(filters)

    for i, row in enumerate(data):
        row["sequence_number"] = i + 1

    if not data:
        frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

    summary_data: dict = get_totals_from_data(data)

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

    from_date = getdate(filters.get("from_date") or filters.get("date_from"))
    to_date = getdate(filters.get("to_date"))

    return {
        "data": data,
        "summary_data": summary_data,
        "company_data": company_data,
        "company_doc": company_doc,
        "from_date": from_date,
        "to_date": to_date,
    }


# ──────────────────────────────────────────────────────────────────────
#  API pública
# ──────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def create_seniat_excel_file(report_name: str, filters=None, **kwargs):
    """Genera el Excel con formato fiscal SENIAT y lo devuelve en base64."""
    if not filters:
        filters = kwargs.get("filters_json")

    try:
        from l10n_ve.l10n_ve.report.purchase_book.purchase_book import _get_tax_rates

        ctx: dict = prepare_purchase_excel_export(filters)
        general_rate, reduced_rate, additional_rate = _get_tax_rates()

        # Post-procesar al formato SENIAT
        seniat_data: list[dict] = _post_process_seniat_rows(
            ctx["data"], general_rate, reduced_rate, additional_rate,
        )

        # Columnas SENIAT + Nr Oper.
        columns: list[dict] = list(SENIAT_COLUMNS)
        columns.insert(0, {
            "label": "Nr Oper.",
            "fieldname": "sequence_number",
            "fieldtype": "Data",
            "width": 5,
        })

        builder = SeniatPurchaseExcelBuilder(
            columns, seniat_data,
            ctx["summary_data"], ctx["company_data"],
            ctx["from_date"], ctx["to_date"],
        )
        stream: BytesIO = builder.build()
        b64: str = base64.b64encode(stream.getvalue()).decode("utf-8")

        return {
            "type": "download",
            "filename": build_purchase_excel_filename(
                ctx["company_doc"].company_name, ctx["from_date"], ctx["to_date"],
            ),
            "filecontent": b64,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_seniat_excel_file (Purchase Book)")
        frappe.throw(_("Error al generar el Excel formato SENIAT: {0}").format(e))
