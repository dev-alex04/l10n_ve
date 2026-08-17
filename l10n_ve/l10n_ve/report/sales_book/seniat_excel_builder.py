"""
Builder de Excel con formato SENIAT para el Libro de Ventas.

Replica la estructura del modelo oficial: 30 columnas (A-AD),
encabezados multinivel con merges, y agrupación por tipo de
contribuyente segun Decreto 3.584, con la misma estetica del
Libro de Compras formato SENIAT.
"""
import frappe
from frappe import _
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from frappe.utils import flt

from l10n_ve.l10n_ve.report.sales_book.sales_book import (
    get_total_row, prepare_excel_export, build_excel_filename,
)


def get_seniat_columns() -> list[dict]:
    """Retorna las columnas del formato SENIAT (lazy, evalua _() en cada llamada)."""
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
        {"label": _("No Sujetas"), "fieldname": "total_not_subject", "fieldtype": "Currency", "width": 10},
        {"label": _("Exentas"), "fieldname": "total_exempt", "fieldtype": "Currency", "width": 10},
        {"label": _("Exoneradas"), "fieldname": "total_exonerated", "fieldtype": "Currency", "width": 10},
        {"label": _("Export. FOB"), "fieldname": "ve_fob", "fieldtype": "Currency", "width": 10},
        {"label": _("Base"), "fieldname": "base_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_taxpayer", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("Base"), "fieldname": "base_dto3584", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_dto3584", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_dto3584", "fieldtype": "Currency", "width": 14},
        {"label": _("Base"), "fieldname": "base_non_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "rate_non_taxpayer", "fieldtype": "Percent", "width": 6},
        {"label": _("Impuesto"), "fieldname": "iva_non_taxpayer", "fieldtype": "Currency", "width": 14},
        {"label": _("Ajustes Déb. Fiscales"), "fieldname": "fiscal_adjustments", "fieldtype": "Currency", "width": 10},
        {"label": _("Fecha Comprobante"), "fieldname": "withholding_date", "fieldtype": "Data", "width": 10},
        {"label": _("Nro. Comprobante"), "fieldname": "vat_withholding_voucher_number", "fieldtype": "Data", "width": 15},
        {"label": _("%"), "fieldname": "vat_withholding_rate", "fieldtype": "Percent", "width": 6},
        {"label": _("IVA Retenido"), "fieldname": "iva_retained", "fieldtype": "Currency", "width": 14},
        {"label": _("Base IGTF"), "fieldname": "base_amount_igtf", "fieldtype": "Currency", "width": 14},
        {"label": _("%"), "fieldname": "igtf_rate", "fieldtype": "Percent", "width": 6},
        {"label": _("Monto IGTF"), "fieldname": "total_igtf", "fieldtype": "Currency", "width": 14},
    ]


def post_process_seniat_rows(
    data: list[dict],
    general_rate: float,
    reduced_rate: float,
    additional_rate: float,
) -> list[dict]:
    """Transforma las filas del SQL al esquema de columnas SENIAT."""
    for row in data:
        row["base_taxpayer"] = 0
        row["iva_taxpayer"] = 0
        row["rate_taxpayer"] = 0

        base_dto = (
            flt(row.get("base_general_taxpayer", 0))
            + flt(row.get("base_general_non_taxpayer", 0))
        )
        iva_dto = (
            flt(row.get("iva_general_taxpayer", 0))
            + flt(row.get("iva_general_non_taxpayer", 0))
        )
        row["base_dto3584"] = base_dto
        row["iva_dto3584"] = iva_dto
        row["rate_dto3584"] = float(general_rate) if base_dto else 0

        row["base_non_taxpayer"] = 0
        row["iva_non_taxpayer"] = 0
        row["rate_non_taxpayer"] = 0

        row["export_declaration"] = ""
        row["total_not_subject"] = 0
        row["total_exonerated"] = 0
        row["fiscal_adjustments"] = 0

    return data


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
        self.font_header_white = Font(name="Calibri", size=8, bold=True, color="FFFFFF")
        self.font_total = Font(name="Calibri", size=8, bold=True)

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

        self.header_fill_primary = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        self.header_fill_secondary = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
        self.header_fill_tertiary = PatternFill(start_color="475569", end_color="475569", fill_type="solid")
        self.zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        self.total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

        self.align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        self.align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
        self.align_right = Alignment(horizontal="right", vertical="center")
        self.num_fmt = "#,##0.00"

    def _add_report_header(self) -> int:
        ws = self.ws

        ws.row_dimensions[2].height = 30
        title_cell = ws.cell(row=2, column=2, value=_("LIBRO DE VENTAS FISCAL"))
        title_font = Font(name="Calibri", size=16, bold=True, color="1E293B")
        title_cell.font = title_font
        title_cell.alignment = Alignment(vertical="center")

        meta_label_font = Font(name="Calibri", size=9, bold=True, color="475569")
        meta_value_font = Font(name="Calibri", size=9, color="1E293B")
        card_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        start_row = 4
        end_row = 8
        start_col = 2
        end_col = 14

        for r in range(start_row, end_row + 1):
            ws.row_dimensions[r].height = 20
            for c in range(start_col, end_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.fill = card_fill
                left_side = Side(style="thin", color="CBD5E1") if c == start_col else None
                right_side = Side(style="thin", color="CBD5E1") if c == end_col else None
                top_side = Side(style="thin", color="CBD5E1") if r == start_row else None
                bottom_side = Side(style="thin", color="CBD5E1") if r == end_row else None
                cell.border = Border(left=left_side, right=right_side, top=top_side, bottom=bottom_side)

        lbl_company = ws.cell(row=5, column=2, value=_("Nombre o Razón Social:"))
        lbl_company.font = meta_label_font
        lbl_company.alignment = Alignment(horizontal="right", vertical="center")

        val_company = ws.cell(row=5, column=4, value=self.company_data.get("company_name", ""))
        val_company.font = Font(name="Calibri", size=9, bold=True, color="1E293B")
        val_company.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=4, end_row=5, end_column=8)

        lbl_rif = ws.cell(row=5, column=10, value=_("RIF de la Empresa:"))
        lbl_rif.font = meta_label_font
        lbl_rif.alignment = Alignment(horizontal="right", vertical="center")

        val_rif = ws.cell(row=5, column=12, value=self.company_data.get("tax_id", ""))
        val_rif.font = meta_value_font
        val_rif.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=5, start_column=12, end_row=5, end_column=14)

        lbl_dir = ws.cell(row=6, column=2, value=_("Dirección Fiscal:"))
        lbl_dir.font = meta_label_font
        lbl_dir.alignment = Alignment(horizontal="right", vertical="center")

        val_address = ws.cell(row=6, column=4, value=self.company_data.get("address", ""))
        val_address.font = meta_value_font
        val_address.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws.merge_cells(start_row=6, start_column=4, end_row=6, end_column=8)

        lbl_contrib = ws.cell(row=6, column=10, value=_("Contribuyente:"))
        lbl_contrib.font = meta_label_font
        lbl_contrib.alignment = Alignment(horizontal="right", vertical="center")

        taxpayer_type = _("ESPECIAL") if self.company_data.get("is_special_taxpayer") else _("ORDINARIO")
        val_contrib = ws.cell(row=6, column=12, value=taxpayer_type)
        val_contrib.font = meta_value_font
        val_contrib.alignment = Alignment(horizontal="left", vertical="center")
        ws.merge_cells(start_row=6, start_column=12, end_row=6, end_column=14)

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

        return 11

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

        _merge(r1, 1, r3, 1, _("Nº oper"))
        _merge(r1, 2, r3, 2, _("Sucursal"))

        _merge(r1, 3, r1, 8, _("Factura o Documento Equivalente"))
        _cell(r2, 3, _("Fecha")); _cell(r3, 3, _("Factura"))
        _cell(r2, 4, _("Número")); _cell(r3, 4, _("RIF"))
        _merge(r2, 5, r3, 5, _("Nombre o Razón Social"))
        _cell(r2, 6, _("Serie")); _cell(r3, 6, _("Fiscal"))
        _cell(r2, 7, _("Número")); _cell(r3, 7, _("Factura"))
        _cell(r2, 8, _("Número")); _cell(r3, 8, _("Control"))

        _merge(r1, 9, r3, 9, _("Guía o Declaración de Exportación"))
        _merge(r1, 10, r3, 10, _("Nro. Nota de Débito"))
        _merge(r1, 11, r3, 11, _("Nro. Nota de Crédito"))
        _merge(r1, 12, r3, 12, _("Tipo Trans."))
        _merge(r1, 13, r3, 13, _("Nro. Factura Afectada"))
        _merge(r1, 14, r3, 14, _("Total Ventas Incluyendo I.V.A"))

        _merge(r1, 15, r1, 17, _("Ventas no Gravadas"))
        _merge(r2, 15, r3, 15, _("No Sujetas"))
        _merge(r2, 16, r3, 16, _("Exentas"))
        _merge(r2, 17, r3, 17, _("Exoneradas"))

        _merge(r1, 18, r3, 18, _("Ventas Export. FOB"))

        _merge(r1, 19, r1, 27, _("Ventas Gravadas"))
        _merge(r2, 19, r2, 21, _("A Contribuyentes"))
        _cell(r3, 19, _("Base")); _cell(r3, 20, _("%")); _cell(r3, 21, _("Impuesto"))
        _merge(r2, 22, r2, 24, _("A Contribuyentes Según Decreto 3.584"))
        _cell(r3, 22, _("Base")); _cell(r3, 23, _("%")); _cell(r3, 24, _("Impuesto"))
        _merge(r2, 25, r2, 27, _("A no Contribuyentes"))
        _cell(r3, 25, _("Base")); _cell(r3, 26, _("%")); _cell(r3, 27, _("Impuesto"))

        _merge(r1, 28, r3, 28, _("Ajustes Débitos Fiscales"))
        _merge(r1, 29, r3, 29, _("Fecha Comprobante de Retención"))
        _merge(r1, 30, r3, 30, _("Nro. Comprobante de Retención"))
        _merge(r1, 31, r3, 31, _("%"))
        _merge(r1, 32, r3, 32, _("IVA Retenido"))

        _merge(r1, 33, r1, 35, _("IGTF"))
        _merge(r2, 33, r3, 33, _("Base"))
        _merge(r2, 34, r3, 34, _("%"))
        _merge(r2, 35, r3, 35, _("Monto"))

        for r in (r1, r2, r3):
            ws.row_dimensions[r].height = 28

        for i, col_def in enumerate(self.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = col_def.get("width", 10)

        return r3

    def _write_data_rows(self, data: list[dict], start_row: int) -> int:
        ws = self.ws
        row_idx = start_row + 1
        for i, row_data in enumerate(data):
            fill = self.zebra_fill if i % 2 == 0 else None
            for col_idx, col_def in enumerate(self.columns, start=1):
                value = row_data.get(col_def["fieldname"])
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.font = self.font_default
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                if isinstance(value, (int, float)):
                    cell.number_format = "0" if col_def["fieldname"] == "sequence_number" else self.num_fmt
                    cell.alignment = self.align_right
                else:
                    cell.alignment = self.align_left
            ws.row_dimensions[row_idx].height = 18
            row_idx += 1
        return row_idx - 1

    def _write_totals_row(self, data: list[dict], after_row: int) -> int:
        ws = self.ws
        row_idx = after_row + 2

        currency_fields = [
            col["fieldname"] for col in self.columns
            if col["fieldtype"] == "Currency"
        ]
        totals = {f: 0.0 for f in currency_fields}

        for row in data:
            if row.get("is_void"):
                continue
            for field in currency_fields:
                totals[field] = flt(totals[field]) + flt(row.get(field, 0))

        for col_idx in range(1, len(self.columns) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = self.font_total
            cell.fill = self.total_fill
            cell.border = self.total_border

        label_cell = ws.cell(row=row_idx, column=1, value=_("TOTALES"))
        label_cell.font = self.font_total
        label_cell.border = self.total_border
        label_cell.fill = self.total_fill
        ws.merge_cells(start_row=row_idx, start_column=1,
                       end_row=row_idx, end_column=2)

        for col_idx, col_def in enumerate(self.columns, start=1):
            fieldname = col_def["fieldname"]
            if fieldname in totals:
                cell = ws.cell(row=row_idx, column=col_idx, value=totals[fieldname])
                cell.font = self.font_total
                cell.border = self.total_border
                cell.fill = self.total_fill
                cell.number_format = self.num_fmt
                cell.alignment = self.align_right

        ws.row_dimensions[row_idx].height = 20
        return row_idx

    def _build_summary_table(self, start_row: int) -> int:
        ws = self.ws
        if not self.summary_data:
            return start_row

        r = start_row + 2
        sc = 10

        summary_headers = [
            {"text": _("RESUMEN"), "start_col": sc, "span": 5, "align": "center"},
            {"text": _("Base Imponible"), "start_col": sc + 5, "span": 1, "align": "center"},
            {"text": _("Débito Fiscal"), "start_col": sc + 6, "span": 1, "align": "center"},
            {"text": _("Retención"), "start_col": sc + 7, "span": 1, "align": "center"},
        ]

        for header_info in summary_headers:
            span = header_info["span"]
            start_col = header_info["start_col"]
            for c_offset in range(span):
                cell = ws.cell(row=r, column=start_col + c_offset)
                cell.fill = self.header_fill_primary
                cell.border = self.header_border
            cell = ws.cell(row=r, column=start_col, value=header_info["text"])
            cell.font = self.font_header_white
            cell.alignment = Alignment(horizontal=header_info["align"], vertical="center", wrap_text=True)
            if span > 1:
                ws.merge_cells(start_row=r, start_column=start_col,
                               end_row=r, end_column=start_col + span - 1)
        ws.row_dimensions[r].height = 24
        r += 1

        summary_rows = [
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

        for i, (concept, base, iva, ret) in enumerate(summary_rows):
            fill = self.zebra_fill if i % 2 == 0 else None
            for c_offset in range(5):
                cell = ws.cell(row=r, column=sc + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
            concept_cell = ws.cell(row=r, column=sc, value=concept)
            concept_cell.font = self.font_default

            for j, val in enumerate([base, iva, ret], start=1):
                cell = ws.cell(row=r, column=sc + 4 + j, value=val)
                cell.font = self.font_default
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                cell.number_format = self.num_fmt
                cell.alignment = self.align_right

            ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)
            ws.row_dimensions[r].height = 18
            r += 1

        for c_idx in range(sc, sc + 8):
            cell = ws.cell(row=r, column=c_idx)
            cell.font = self.font_total
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_base = sum(row[1] for row in summary_rows)
        total_iva = sum(row[2] for row in summary_rows)
        total_retention = sum(row[3] for row in summary_rows)

        ws.cell(row=r, column=sc, value=_("Total")).font = self.font_total
        for j, val in enumerate([total_base, total_iva, total_retention], start=1):
            cell = ws.cell(row=r, column=sc + 4 + j, value=val)
            cell.font = self.font_total
            cell.number_format = self.num_fmt
            cell.alignment = self.align_right

        ws.merge_cells(start_row=r, start_column=sc, end_row=r, end_column=sc + 4)

        ws.row_dimensions[r].height = 20
        return r

    def _build_adjustments_table(self, start_row: int) -> int:
        if not self.adjustment_data:
            return start_row

        ws = self.ws
        r = start_row + 2
        ws.cell(row=r, column=1,
                value=_("Ajustes de Períodos Anteriores (Retenciones)")
                ).font = Font(size=12, bold=True)
        r += 2

        headers_row = self._build_multi_level_headers(r)
        last_data = self._write_data_rows(self.adjustment_data, headers_row)
        self._write_totals_row(self.adjustment_data, last_data)
        return ws.max_row

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


@frappe.whitelist()
def create_seniat_excel_file(report_name: str, filters=None, **kwargs):
    """Genera el Excel con formato fiscal SENIAT y lo devuelve en base64."""
    if not filters:
        filters = kwargs.get("filters_json")

    try:
        ctx = prepare_excel_export(filters)

        try:
            tax_doc = frappe.get_cached_doc("Taxes Rates", "Taxes Rates")
            general_rate = tax_doc.get("general_rate") or 16.0
            reduced_rate = tax_doc.get("reduced_rate") or 8.0
            additional_rate = tax_doc.get("additional_rate") or 31.0
        except Exception:
            general_rate, reduced_rate, additional_rate = 16.0, 8.0, 31.0

        main_data = post_process_seniat_rows(ctx["main_data"], general_rate, reduced_rate, additional_rate)
        adjustment_data = post_process_seniat_rows(ctx["adjustment_data"], general_rate, reduced_rate, additional_rate)

        columns = get_seniat_columns()
        columns.insert(0, {"label": "Nr Oper.", "fieldname": "sequence_number", "fieldtype": "Data", "width": 5})

        builder = SeniatExcelBuilder(
            columns, main_data, adjustment_data,
            ctx["summary_data"], ctx["company_data"],
            ctx["from_date"], ctx["to_date"],
        )
        stream = builder.build()
        b64 = base64.b64encode(stream.getvalue()).decode("utf-8")

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
