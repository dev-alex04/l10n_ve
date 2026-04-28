"""
Builder de Excel con formato SENIAT para el Libro de Ventas.

Replica la estructura del modelo oficial: 30 columnas (A-AD),
encabezados multinivel con merges, y agrupación por tipo de
contribuyente según Decreto 3.584.
"""
import frappe
from frappe import _
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from frappe.utils import flt

from l10n_ve.l10n_ve.report.sales_book.sales_book import (
    get_total_row, prepare_excel_export, build_excel_filename,
)


# ──────────────────────────────────────────────────────────────────────
#  Definición de columnas formato SENIAT (A-AD = 30 columnas)
# ──────────────────────────────────────────────────────────────────────

def get_seniat_columns() -> list[dict]:
    """Columnas del formato SENIAT. Nr Oper. se inyecta después."""
    return [
        {"label": _("Sucursal"), "fieldname": "branch", "fieldtype": "Data", "width": 14},
        {"label": _("Fecha Factura"), "fieldname": "posting_date", "fieldtype": "Data", "width": 10},
        {"label": _("RIF"), "fieldname": "customer_tax_id", "fieldtype": "Data", "width": 12},
        {"label": _("Nombre o Razón Social"), "fieldname": "customer_name", "fieldtype": "Data", "width": 30},
        {"label": _("Serie Fiscal"), "fieldname": "fiscal_series", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Factura"), "fieldname": "bill_no", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Control"), "fieldname": "bill_control", "fieldtype": "Data", "width": 12},
        {"label": _("Guía/Decl. Export."), "fieldname": "export_declaration", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Nota de Débito"), "fieldname": "debit_note_no", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Nota de Crédito"), "fieldname": "credit_note_no", "fieldtype": "Data", "width": 10},
        {"label": _("Tipo Trans."), "fieldname": "transaction_type", "fieldtype": "Data", "width": 8},
        {"label": _("Nro. Fact. Afectada"), "fieldname": "affected_invoice_number", "fieldtype": "Data", "width": 10},
        {"label": _("Total Ventas Incl. IVA"), "fieldname": "grand_total", "fieldtype": "Currency", "width": 14},
        # Ventas no Gravadas (3 sub-columnas)
        {"label": _("No Sujetas"), "fieldname": "total_not_subject", "fieldtype": "Currency", "width": 10},
        {"label": _("Exentas"), "fieldname": "total_exempt", "fieldtype": "Currency", "width": 10},
        {"label": _("Exoneradas"), "fieldname": "total_exonerated", "fieldtype": "Currency", "width": 10},
        {"label": _("Export. FOB"), "fieldname": "ve_fob", "fieldtype": "Currency", "width": 10},
        # A Contribuyentes (tasa general)
        {"label": _("Base"), "fieldname": "base_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_taxpayer", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_taxpayer", "fieldtype": "Currency", "width": 14},
        # A Contribuyentes Según Decreto 3.584 (reducida + adicional)
        {"label": _("Base"), "fieldname": "base_dto3584", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_dto3584", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_dto3584", "fieldtype": "Currency", "width": 14},
        # A No Contribuyentes
        {"label": _("Base"), "fieldname": "base_non_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_non_taxpayer", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_non_taxpayer", "fieldtype": "Currency", "width": 14},
        # Ajustes
        {"label": _("Ajustes Déb. Fiscales"), "fieldname": "fiscal_adjustments", "fieldtype": "Currency", "width": 10},
        # Retención
        {"label": _("Fecha Comprobante"), "fieldname": "withholding_date", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Comprobante"), "fieldname": "vat_withholding_voucher_number", "fieldtype": "Data", "width": 15},
        {"label": _("%"), "fieldname": "vat_withholding_rate", "fieldtype": "Percent", "width": 6},
        {"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 14},
        # IGTF - Impuesto a las Grandes Transacciones Financieras
        {"label": _("Base IGTF"), "fieldname": "base_amount_igtf", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "igtf_rate", "fieldtype": "Percent", "width": 6},
        {"label": _("Monto IGTF"), "fieldname": "total_igtf", "fieldtype": "Currency", "width": 14},
    ]


# ──────────────────────────────────────────────────────────────────────
#  Post-procesamiento: transforma datos SQL → formato SENIAT
# ──────────────────────────────────────────────────────────────────────

def post_process_seniat_rows(
    data: list[dict],
    general_rate: float,
    reduced_rate: float,
    additional_rate: float,
) -> list[dict]:
    """Transforma las filas del SQL al esquema de columnas SENIAT."""
    for row in data:
        # TODO: [DOMINA-BACKLOG] Separar ventas por tipo de contribuyente:
        #   - A Contribuyentes (Q-S): reservada, siempre vacía bajo Dto 3.584.
        #   - Dto 3.584 (T-V): ventas a contribuyentes (con RIF) al 16%.
        #   - A No Contribuyentes (W-Y): ventas a consumidores finales (sin RIF).
        #   Actualmente TODO va a Dto 3.584 como solución temporal.
        #   Jira: Backlog Domina ERP Venezuela

        # A Contribuyentes (Q-S): columna RESERVADA, siempre vacía.
        row["base_taxpayer"] = 0
        row["iva_taxpayer"] = 0
        row["rate_taxpayer"] = 0

        # A Contribuyentes Según Decreto 3.584 (T-V): TEMPORALMENTE agrupa
        # TODAS las ventas (contribuyentes + no contribuyentes) al 16%.
        base_dto: float = (
            flt(row.get("base_general_taxpayer", 0))
            + flt(row.get("base_general_non_taxpayer", 0))
        )
        iva_dto: float = (
            flt(row.get("iva_general_taxpayer", 0))
            + flt(row.get("iva_general_non_taxpayer", 0))
        )
        row["base_dto3584"] = base_dto
        row["iva_dto3584"] = iva_dto
        row["rate_dto3584"] = general_rate if base_dto else 0

        # A No Contribuyentes (W-Y): vacía temporalmente (ver TODO arriba).
        row["base_non_taxpayer"] = 0
        row["iva_non_taxpayer"] = 0
        row["rate_non_taxpayer"] = 0

        # Columnas vacías del formato SENIAT
        row["export_declaration"] = ""
        row["total_not_subject"] = 0
        row["total_exonerated"] = 0
        row["fiscal_adjustments"] = 0

    return data


# ──────────────────────────────────────────────────────────────────────
#  Builder de Excel formato SENIAT
# ──────────────────────────────────────────────────────────────────────

class SeniatExcelBuilder:

    def __init__(self, columns, main_data, adjustment_data, summary_data,
                 company_data, from_date, to_date):
        self.columns = columns
        self.main_data = main_data
        self.adjustment_data = adjustment_data
        self.summary_data = summary_data
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date

        self.wb = Workbook()
        self.ws = self.wb.active
        self.ws.title = "Libro de Ventas"

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
        """Encabezado estilo formato actual: título, razón social, RIF,
        dirección, tipo de contribuyente y período fiscal."""
        ws = self.ws
        right_col: int = 12  # Columna L para datos del lado derecho

        # Fila 1: Título
        title = ws.cell(row=1, column=1, value=_("Libro de Ventas Fiscal"))
        title.font = Font(name="Calibri", size=10, bold=True, underline="single")

        # Fila 3-4: Nombre o Razón Social / RIF
        ws.cell(row=3, column=1, value=_("Nombre o Razón Social:")).font = self.font_header
        ws.cell(row=4, column=1, value=self.company_data.get("company_name", "")).font = self.font_default

        ws.cell(row=3, column=right_col,
                value=_("Número de Registro de Información Fiscal (RIF):")).font = self.font_header
        ws.cell(row=4, column=right_col,
                value=self.company_data.get("tax_id", "")).font = self.font_default

        # Fila 6-7: Dirección / Tipo de Contribuyente
        ws.cell(row=6, column=1, value=_("Dirección:")).font = self.font_header
        ws.cell(row=7, column=1, value=self.company_data.get("address", "")).font = self.font_default

        ws.cell(row=6, column=right_col, value=_("Tipo de Contribuyente:")).font = self.font_header
        taxpayer_type: str = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("ORDINARIO")
        ws.cell(row=7, column=right_col, value=taxpayer_type).font = self.font_default

        # Fila 9-10: Período Fiscal
        ws.cell(row=9, column=1, value=_("Período Fiscal:")).font = self.font_header
        ws.cell(row=10, column=1, value="{0} - {1}".format(
            self.from_date.strftime("%d/%m/%Y"),
            self.to_date.strftime("%d/%m/%Y"),
        )).font = self.font_default

        return 12  # siguiente fila disponible (headers empiezan en fila 12)

    # ── Headers multinivel (3 filas) ──

    def _build_multi_level_headers(self, start_row: int) -> int:
        """3 niveles de encabezados con merges, réplica del modelo SENIAT."""
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

        # Col A: "Nº oper" (3 filas)
        _merge(r1, 1, r3, 1, _("Nº oper"))

        # Col B: "Sucursal" (3 filas)
        _merge(r1, 2, r3, 2, _("Sucursal"))

        # Cols C-H: "Factura o Documento Equivalente"
        _merge(r1, 3, r1, 8, _("Factura o Documento Equivalente"))
        _cell(r2, 3, _("Fecha")); _cell(r3, 3, _("Factura"))
        _cell(r2, 4, _("Número")); _cell(r3, 4, _("RIF"))
        _merge(r2, 5, r3, 5, _("Nombre o Razón Social"))
        _cell(r2, 6, _("Serie")); _cell(r3, 6, _("Fiscal"))
        _cell(r2, 7, _("Número")); _cell(r3, 7, _("Factura"))
        _cell(r2, 8, _("Número")); _cell(r3, 8, _("Control"))

        # Col I: merge 3 filas
        _merge(r1, 9, r3, 9, _("Guía o Declaración de Exportación"))

        # Col J: merge 3 filas
        _merge(r1, 10, r3, 10, _("Nro. Nota de Débito"))

        # Col K: merge 3 filas
        _merge(r1, 11, r3, 11, _("Nro. Nota de Crédito"))

        # Col L: merge 3 filas
        _merge(r1, 12, r3, 12, _("Tipo Trans."))

        # Col M: merge 3 filas
        _merge(r1, 13, r3, 13, _("Nro. Factura Afectada"))

        # Col N: merge 3 filas
        _merge(r1, 14, r3, 14, _("Total Ventas Incluyendo I.V.A"))

        # Cols O-Q: "Ventas no Gravadas"
        _merge(r1, 15, r1, 17, _("Ventas no Gravadas"))
        _merge(r2, 15, r3, 15, _("No Sujetas"))
        _merge(r2, 16, r3, 16, _("Exentas"))
        _merge(r2, 17, r3, 17, _("Exoneradas"))

        # Col R: merge 3 filas
        _merge(r1, 18, r3, 18, _("Ventas Export. FOB"))

        # Cols S-AA: "Ventas Gravadas"
        _merge(r1, 19, r1, 27, _("Ventas Gravadas"))
        # S-U: A Contribuyentes
        _merge(r2, 19, r2, 21, _("A Contribuyentes"))
        _cell(r3, 19, _("Base")); _cell(r3, 20, _("%")); _cell(r3, 21, _("Impuesto"))
        # V-X: Dto 3.584
        _merge(r2, 22, r2, 24, _("A Contribuyentes Según Decreto 3.584"))
        _cell(r3, 22, _("Base")); _cell(r3, 23, _("%")); _cell(r3, 24, _("Impuesto"))
        # Y-AA: A No Contribuyentes
        _merge(r2, 25, r2, 27, _("A no Contribuyentes"))
        _cell(r3, 25, _("Base")); _cell(r3, 26, _("%")); _cell(r3, 27, _("Impuesto"))

        # Col AB: merge 3 filas
        _merge(r1, 28, r3, 28, _("Ajustes Débitos Fiscales"))

        # Col AC: merge 3 filas
        _merge(r1, 29, r3, 29, _("Fecha Comprobante de Retención"))

        # Col AD: merge 3 filas
        _merge(r1, 30, r3, 30, _("Nro. Comprobante de Retención"))

        # Col AE: "%" (merge 3 filas)
        _merge(r1, 31, r3, 31, _("%"))

        # Col AF: "IVA Retenido" (merge 3 filas)
        _merge(r1, 32, r3, 32, _("IVA Retenido"))

        # Cols AG-AI: "IGTF"
        _merge(r1, 33, r1, 35, _("IGTF"))
        _merge(r2, 33, r3, 33, _("Base"))
        _merge(r2, 34, r3, 34, _("%"))
        _merge(r2, 35, r3, 35, _("Monto"))

        # Altura de filas
        for r in (r1, r2, r3):
            ws.row_dimensions[r].height = 25

        # Anchos de columna
        for i, col_def in enumerate(self.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = col_def.get("width", 10)

        return r3  # fila donde empiezan los datos

    # ── Filas de datos ──

    def _write_data_rows(self, data: list[dict], start_row: int) -> int:
        row_idx: int = start_row + 1
        for row_data in data:
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

    def _write_totals_row(self, data: list[dict], after_row: int) -> int:
        """Fila de totales: suma todas las columnas Currency desde los datos."""
        row_idx: int = after_row + 2

        # Calcular sumas excluyendo anuladas y NC
        currency_fields: list[str] = [
            col["fieldname"] for col in self.columns
            if col["fieldtype"] == "Currency"
        ]
        totals: dict = {f: 0.0 for f in currency_fields}

        for row in data:
            if row.get("is_void"):
                continue
            for field in currency_fields:
                totals[field] = flt(totals[field]) + flt(row.get(field, 0))

        # Escribir etiqueta "TOTALES"
        label_cell = self.ws.cell(row=row_idx, column=1, value=_("TOTALES"))
        label_cell.font = self.font_header
        label_cell.border = self.border
        self.ws.merge_cells(start_row=row_idx, start_column=1,
                            end_row=row_idx, end_column=2)

        # Escribir valores
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
        sc: int = 10  # start column

        ws.cell(row=r, column=sc, value=_("Resumen de Totales")).font = Font(bold=True, size=12)
        r += 1

        headers = [_("Concepto"), _("Base Imponible"), _("Débito Fiscal"), _("Retención")]
        for i, h in enumerate(headers):
            c = ws.cell(row=r, column=sc + i, value=h)
            c.font = self.font_header
            c.border = self.border
        r += 1

        rows_data = [
            (_("De las Ventas Internas NO Gravadas"),
             self.summary_data.get("total_exempt", 0), 0, 0),
            (_("Ventas de exportación"), 0, 0, 0),
            (_("Alícuota General"),
             flt(self.summary_data.get("base_general_taxpayer", 0))
             + flt(self.summary_data.get("base_general_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_general_taxpayer", 0))
             + flt(self.summary_data.get("iva_general_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_retained_general", 0))),
            (_("Alícuota General + Adicional"),
             flt(self.summary_data.get("base_additional_taxpayer", 0))
             + flt(self.summary_data.get("base_additional_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_additional_taxpayer", 0))
             + flt(self.summary_data.get("iva_additional_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_retained_additional", 0))),
            (_("Alícuota Reducida"),
             flt(self.summary_data.get("base_reduced_taxpayer", 0))
             + flt(self.summary_data.get("base_reduced_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_reduced_taxpayer", 0))
             + flt(self.summary_data.get("iva_reduced_non_taxpayer", 0)),
             flt(self.summary_data.get("iva_retained_reduced", 0))),
        ]

        for concept, base, iva, ret in rows_data:
            ws.cell(row=r, column=sc, value=concept).font = self.font_default
            for j, val in enumerate([base, iva, ret], start=1):
                c = ws.cell(row=r, column=sc + j, value=val)
                c.font = self.font_default
                c.number_format = self.num_fmt
                c.border = self.border
            r += 1

        # Fila de totales del resumen
        ws.cell(row=r, column=sc, value=_("Totales")).font = self.font_header
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

    # ── Tabla de ajustes ──

    def _build_adjustments_table(self, start_row: int) -> int:
        if not self.adjustment_data:
            return start_row

        r: int = start_row + 2
        self.ws.cell(row=r, column=1,
                     value=_("Ajustes de Períodos Anteriores (Retenciones)")
                     ).font = Font(size=12, bold=True)
        r += 2

        headers_row = self._build_multi_level_headers(r)
        last_data = self._write_data_rows(self.adjustment_data, headers_row)
        self._write_totals_row(self.adjustment_data, last_data)
        return self.ws.max_row

    # ── Orquestador ──

    def build(self) -> BytesIO:
        header_end = self._add_report_header()
        headers_row = self._build_multi_level_headers(header_end)
        last_data = self._write_data_rows(self.main_data, headers_row)
        totals_row = self._write_totals_row(self.main_data, last_data)
        summary_row = self._build_summary_table(totals_row)
        self._build_adjustments_table(summary_row)

        stream = BytesIO()
        self.wb.save(stream)
        stream.seek(0)
        return stream


# ──────────────────────────────────────────────────────────────────────
#  API pública
# ──────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def create_seniat_excel_file(report_name: str, filters=None, **kwargs):
    """Genera el Excel con formato fiscal SENIAT y lo devuelve en base64."""
    if not filters:
        filters = kwargs.get("filters_json")

    try:
        ctx: dict = prepare_excel_export(filters)

        # Obtener tasas de impuestos
        try:
            tax_doc = frappe.get_cached_doc("Taxes Rates", "Taxes Rates")
            general_rate: float = tax_doc.get("general_rate") or 16.0
            reduced_rate: float = tax_doc.get("reduced_rate") or 8.0
            additional_rate: float = tax_doc.get("additional_rate") or 31.0
        except Exception:
            general_rate, reduced_rate, additional_rate = 16.0, 8.0, 31.0

        # Post-procesar al formato SENIAT
        main_data = post_process_seniat_rows(ctx["main_data"], general_rate, reduced_rate, additional_rate)
        adjustment_data = post_process_seniat_rows(ctx["adjustment_data"], general_rate, reduced_rate, additional_rate)

        # Columnas SENIAT + Nr Oper.
        columns: list[dict] = get_seniat_columns()
        columns.insert(0, {"label": "Nr Oper.", "fieldname": "sequence_number", "fieldtype": "Data", "width": 5})

        builder = SeniatExcelBuilder(
            columns, main_data, adjustment_data,
            ctx["summary_data"], ctx["company_data"],
            ctx["from_date"], ctx["to_date"],
        )
        stream: BytesIO = builder.build()
        b64: str = base64.b64encode(stream.getvalue()).decode("utf-8")

        return {
            "type": "download",
            "filename": build_excel_filename(
                ctx["company_doc"].company_name, ctx["from_date"], ctx["to_date"]
            ),
            "filecontent": b64,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_seniat_excel_file")
        frappe.throw(_("Error al generar el Excel formato SENIAT: {0}").format(e))
