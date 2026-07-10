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
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
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

        # Definimos los estilos comunes
        self.font_default = Font(name="Calibri", size=8)
        self.font_header = Font(name="Calibri", size=8, bold=True)
        self.font_header_white = Font(name="Calibri", size=8, bold=True, color="FFFFFF")
        self.font_title = Font(name="Calibri", size=14, bold=True, color="1E293B")
        self.font_meta_title = Font(name="Calibri", size=8, bold=True, color="475569")
        self.font_meta_value = Font(name="Calibri", size=8, color="1E293B")

        self.thin_border = Border(
            left=Side(style="thin", color="E2E8F0"),
            right=Side(style="thin", color="E2E8F0"),
            top=Side(style="thin", color="E2E8F0"),
            bottom=Side(style="thin", color="E2E8F0"),
        )
        self.header_border = Border(
            left=Side(style="thin", color="475569"),
            right=Side(style="thin", color="475569"),
            top=Side(style="thin", color="475569"),
            bottom=Side(style="medium", color="1E293B"),
        )
        self.total_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="medium", color="1E293B"),
            bottom=Side(style="double", color="1E293B"),
        )

        self.header_fill_primary = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid") # Dark Slate
        self.header_fill_secondary = PatternFill(start_color="334155", end_color="334155", fill_type="solid") # Lighter Slate
        self.header_fill_tertiary = PatternFill(start_color="475569", end_color="475569", fill_type="solid") # Soft slate
        self.sub_header_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid") # Soft light grey
        self.zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid") # Very soft blue/grey
        self.total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid") # Total background
        self.alert_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid") # Light emerald for summary

        self.align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
        self.align_right = Alignment(horizontal="right", vertical="center")
        self.num_fmt = "#,##0.00"

    # ── Encabezado del reporte ──

    def _add_report_header(self) -> int:
        ws = self.ws
        
        # 1. Título principal del Reporte
        ws.row_dimensions[2].height = 30
        title_cell = ws.cell(row=2, column=2, value=_("LIBRO DE COMPRAS FISCAL"))
        title_font = Font(name="Calibri", size=16, bold=True, color="1E293B")
        title_cell.font = title_font
        title_cell.alignment = Alignment(vertical="center")
        
        # 2. Definimos estilos de la Ficha Técnica / Tarjeta
        meta_label_font = Font(name="Calibri", size=9, bold=True, color="475569")
        meta_value_font = Font(name="Calibri", size=9, color="1E293B")
        card_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        
        # 3. Dibujamos y estilizamos el fondo y bordes del bloque de la tarjeta (Filas 4 a 8, columnas B a N)
        start_row = 4
        end_row = 8
        start_col = 2  # Columna B
        end_col = 14   # Columna N
        
        for r in range(start_row, end_row + 1):
            ws.row_dimensions[r].height = 20
            for c in range(start_col, end_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.fill = card_fill
                
                # Bordes externos del bloque de ficha técnica
                left_side = Side(style="thin", color="CBD5E1") if c == start_col else None
                right_side = Side(style="thin", color="CBD5E1") if c == end_col else None
                top_side = Side(style="thin", color="CBD5E1") if r == start_row else None
                bottom_side = Side(style="thin", color="CBD5E1") if r == end_row else None
                cell.border = Border(left=left_side, right=right_side, top=top_side, bottom=bottom_side)

        # 4. Insertar datos alineados
        # Nombre de Empresa
        lbl_company = ws.cell(row=5, column=2, value=_("Nombre o Razón Social:"))
        lbl_company.font = meta_label_font
        lbl_company.alignment = Alignment(horizontal="right", vertical="center")
        
        val_company = ws.cell(row=5, column=4, value=self.company_data.get("company_name", ""))
        val_company.font = Font(name="Calibri", size=9, bold=True, color="1E293B")
        val_company.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=4, end_row=5, end_column=8)
        
        # RIF
        lbl_rif = ws.cell(row=5, column=10, value=_("RIF de la Empresa:"))
        lbl_rif.font = meta_label_font
        lbl_rif.alignment = Alignment(horizontal="right", vertical="center")
        
        val_rif = ws.cell(row=5, column=12, value=self.company_data.get("tax_id", ""))
        val_rif.font = meta_value_font
        val_rif.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=12, end_row=5, end_column=14)

        # Dirección (con wrap_text por si es larga)
        lbl_dir = ws.cell(row=6, column=2, value=_("Dirección Fiscal:"))
        lbl_dir.font = meta_label_font
        lbl_dir.alignment = Alignment(horizontal="right", vertical="center")
        
        val_address = ws.cell(row=6, column=4, value=self.company_data.get("address", ""))
        val_address.font = meta_value_font
        val_address.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=6, start_column=4, end_row=6, end_column=8)
        
        # Contribuyente
        lbl_contrib = ws.cell(row=6, column=10, value=_("Contribuyente:"))
        lbl_contrib.font = meta_label_font
        lbl_contrib.alignment = Alignment(horizontal="right", vertical="center")
        
        taxpayer_type: str = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("ORDINARIO")
        val_contrib = ws.cell(row=6, column=12, value=taxpayer_type)
        val_contrib.font = meta_value_font
        val_contrib.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=6, start_column=12, end_row=6, end_column=14)

        # Período Fiscal
        lbl_period = ws.cell(row=7, column=2, value=_("Período Fiscal:"))
        lbl_period.font = meta_label_font
        lbl_period.alignment = Alignment(horizontal="right", vertical="center")
        
        period_str = "{0} - {1}".format(
            self.from_date.strftime("%d/%m/%Y"),
            self.to_date.strftime("%d/%m/%Y"),
        )
        val_period = ws.cell(row=7, column=4, value=period_str)
        val_period.font = meta_value_font
        val_period.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=7, start_column=4, end_row=7, end_column=8)

        # Retornamos 11 para que los encabezados multinivel del libro inicien en la fila 11
        return 11

    # ── Headers multinivel (3 filas) ──

    def _build_multi_level_headers(self, start_row: int) -> int:
        ws = self.ws
        r1, r2, r3 = start_row, start_row + 1, start_row + 2

        def _cell(row, col, val):
            c = ws.cell(row=row, column=col, value=val)
            c.font = self.font_header_white
            c.border = self.header_border
            c.alignment = self.align_center
            if row == r1:
                c.fill = self.header_fill_primary
            elif row == r2:
                c.fill = self.header_fill_secondary
            else:
                c.fill = self.header_fill_tertiary
            return c

        def _merge(row1, col1, row2, col2, val):
            # Style and fill the entire block first to avoid openpyxl border bugs
            for r_idx in range(row1, row2 + 1):
                for c_idx in range(col1, col2 + 1):
                    c = ws.cell(row=r_idx, column=c_idx)
                    c.border = self.header_border
                    if r_idx == r1:
                        c.fill = self.header_fill_primary
                    elif r_idx == r2:
                        c.fill = self.header_fill_secondary
                    else:
                        c.fill = self.header_fill_tertiary
            
            c = ws.cell(row=row1, column=col1, value=val)
            c.font = self.font_header_white
            c.alignment = self.align_center
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
            ws.row_dimensions[r].height = 28

        for i, col_def in enumerate(self.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = col_def.get("width", 10)

        return r3

    # ── Filas de datos ──

    def _write_data_rows(self, start_row: int) -> int:
        row_idx: int = start_row + 1
        for i, row_data in enumerate(self.data):
            fill = self.zebra_fill if i % 2 == 0 else None
            for col_idx, col_def in enumerate(self.columns, start=1):
                value = row_data.get(col_def["fieldname"])
                cell = self.ws.cell(row=row_idx, column=col_idx, value=value)
                cell.font = self.font_default
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill

                if isinstance(value, (int, float)):
                    cell.number_format = "0" if col_def["fieldname"] == "sequence_number" else self.num_fmt
                    cell.alignment = self.align_right
                else:
                    cell.alignment = self.align_left

            self.ws.row_dimensions[row_idx].height = 18
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

        # First, style the entire row
        for col_idx in range(1, len(self.columns) + 1):
            cell = self.ws.cell(row=row_idx, column=col_idx)
            cell.font = self.font_header
            cell.fill = self.total_fill
            cell.border = self.total_border

        label_cell = self.ws.cell(row=row_idx, column=1, value=_("TOTALES"))
        label_cell.font = self.font_header
        label_cell.border = self.total_border
        label_cell.fill = self.total_fill
        
        self.ws.merge_cells(start_row=row_idx, start_column=1,
                            end_row=row_idx, end_column=2)

        for col_idx, col_def in enumerate(self.columns, start=1):
            fieldname: str = col_def["fieldname"]
            if fieldname in totals:
                cell = self.ws.cell(row=row_idx, column=col_idx, value=totals[fieldname])
                cell.font = self.font_header
                cell.border = self.total_border
                cell.fill = self.total_fill
                cell.number_format = self.num_fmt
                cell.alignment = self.align_right
            elif col_idx > 2:
                cell = self.ws.cell(row=row_idx, column=col_idx)
                cell.border = self.total_border
                cell.fill = self.total_fill

        self.ws.row_dimensions[row_idx].height = 20
        return row_idx

    # ── Tabla resumen ──

    def _build_summary_table(self, start_row: int) -> int:
        ws = self.ws
        r: int = start_row + 2
        sc: int = 13  # columna M

        # Header row background and borders
        for c_offset in range(8):
            cell = ws.cell(row=r, column=sc + c_offset)
            cell.fill = self.header_fill_primary
            cell.border = self.header_border
            
        title_cell = ws.cell(row=r, column=sc, value=_("RESUMEN"))
        title_cell.font = self.font_header_white
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
        ws.row_dimensions[r].height = 24
        r += 1

        headers = [_("Concepto"), _("Base Imponible"), _("Crédito Fiscal"), _("Retención")]
        
        for c_offset in range(5):
            cell = ws.cell(row=r, column=sc + c_offset)
            cell.fill = self.header_fill_secondary
            cell.border = self.header_border
            
        concept_header_cell = ws.cell(row=r, column=sc, value=headers[0])
        concept_header_cell.font = self.font_header_white
        concept_header_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)

        for i, h in enumerate(headers[1:], start=5):
            c = ws.cell(row=r, column=sc + i, value=h)
            c.font = self.font_header_white
            c.fill = self.header_fill_secondary
            c.border = self.header_border
            c.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[r].height = 20
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

        for idx, (concept, base, iva, ret) in enumerate(rows_data):
            fill = self.zebra_fill if idx % 2 == 0 else None
            
            for c_offset in range(5):
                cell = ws.cell(row=r, column=sc + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                    
            c_cell = ws.cell(row=r, column=sc, value=concept)
            c_cell.font = self.font_default
            ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
            
            for j, val in enumerate([base, iva, ret], start=5):
                c = ws.cell(row=r, column=sc + j, value=val)
                c.font = self.font_default
                c.number_format = self.num_fmt
                c.border = self.thin_border
                if fill:
                    c.fill = fill
                c.alignment = self.align_right
            ws.row_dimensions[r].height = 18
            r += 1

        # Fila de totales del resumen
        for c_idx in range(sc, sc + 8):
            cell = ws.cell(row=r, column=c_idx)
            cell.font = self.font_header
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_label_cell = ws.cell(row=r, column=sc, value=_("Total"))
        total_label_cell.font = self.font_header
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
        
        for j, val in enumerate([
            sum(row[1] for row in rows_data),
            sum(row[2] for row in rows_data),
            sum(row[3] for row in rows_data),
        ], start=5):
            c = ws.cell(row=r, column=sc + j, value=val)
            c.font = self.font_header
            c.number_format = self.num_fmt
            c.border = self.total_border
            c.fill = self.total_fill
            c.alignment = self.align_right
        ws.row_dimensions[r].height = 20

        return r

    # ── Tabla resumen base vs. IVA ──

    def _build_taxable_vs_iva_table(self, start_row: int) -> int:
        """Construye un cuadrito aparte con el resumen de la base imponible vs. IVA."""
        ws = self.ws
        r: int = start_row + 2
        sc: int = 13  # columna M

        # Título del cuadrito
        for c_idx in range(sc, sc + 8):
            cell = ws.cell(row=r, column=c_idx)
            cell.fill = self.header_fill_primary
            cell.border = self.header_border
            
        title_cell = ws.cell(row=r, column=sc, value=_("RESUMEN BASE IMPONIBLE vs. IVA"))
        title_cell.font = self.font_header_white
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 7)
        ws.row_dimensions[r].height = 24
        r += 1

        headers = [_("Concepto / Alícuota"), _("Base Imponible"), _("Crédito Fiscal"), _("Retención")]
        
        for c_offset in range(5):
            cell = ws.cell(row=r, column=sc + c_offset)
            cell.fill = self.header_fill_secondary
            cell.border = self.header_border
            
        concept_header_cell = ws.cell(row=r, column=sc, value=headers[0])
        concept_header_cell.font = self.font_header_white
        concept_header_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)

        for i, h in enumerate(headers[1:], start=5):
            c = ws.cell(row=r, column=sc + i, value=h)
            c.font = self.font_header_white
            c.fill = self.header_fill_secondary
            c.border = self.header_border
            c.alignment = self.align_center
        ws.row_dimensions[r].height = 20
        r += 1

        # Obtener valores desde self.summary_data
        rows_data = [
            (_("Compras Internas afectadas por alícuota general (16%)"),
             flt(self.summary_data.get("base_general")),
             flt(self.summary_data.get("impuesto_general")),
             flt(self.summary_data.get("retencion_general"))),
            (_("Compras Internas afectadas por alícuota reducida (8%)"),
             flt(self.summary_data.get("base_reducida")),
             flt(self.summary_data.get("impuesto_reducida")),
             flt(self.summary_data.get("retencion_reducida"))),
            (_("Compras Internas afectadas por alícuota general + adicional (31%)"),
             flt(self.summary_data.get("base_adicional")),
             flt(self.summary_data.get("impuesto_adicional")),
             flt(self.summary_data.get("retencion_adicional"))),
        ]

        for idx, (concept, base, iva, ret) in enumerate(rows_data):
            fill = self.zebra_fill if idx % 2 == 0 else None
            
            for c_offset in range(5):
                cell = ws.cell(row=r, column=sc + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                    
            c_cell = ws.cell(row=r, column=sc, value=concept)
            c_cell.font = self.font_default
            ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
            
            for j, val in enumerate([base, iva, ret], start=5):
                c = ws.cell(row=r, column=sc + j, value=val)
                c.font = self.font_default
                c.number_format = self.num_fmt
                c.border = self.thin_border
                if fill:
                    c.fill = fill
                c.alignment = self.align_right
            ws.row_dimensions[r].height = 18
            r += 1

        # Fila de totales del resumen
        for c_idx in range(sc, sc + 8):
            cell = ws.cell(row=r, column=c_idx)
            cell.font = self.font_header
            cell.fill = self.alert_fill
            cell.border = self.total_border

        total_label_cell = ws.cell(row=r, column=sc, value=_("Total"))
        total_label_cell.font = self.font_header
        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
        
        for j, val in enumerate([
            sum(row[1] for row in rows_data),
            sum(row[2] for row in rows_data),
            sum(row[3] for row in rows_data),
        ], start=5):
            c = ws.cell(row=r, column=sc + j, value=val)
            c.font = self.font_header
            c.number_format = self.num_fmt
            c.border = self.total_border
            c.fill = self.alert_fill
            c.alignment = self.align_right
        ws.row_dimensions[r].height = 20

        return r

    # ── Orquestador ──

    def build(self) -> BytesIO:
        header_end: int = self._add_report_header()
        headers_row: int = self._build_multi_level_headers(header_end)
        last_data: int = self._write_data_rows(headers_row)
        totals_row: int = self._write_totals_row(last_data)
        summary_row: int = self._build_summary_table(totals_row)
        self._build_taxable_vs_iva_table(summary_row)

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
