import json
import base64
from io import BytesIO
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill

import frappe
from frappe import _

from l10n_ve.l10n_ve.report.purchase_book.purchase_book import execute, get_totals_from_data


class ExcelBuilder:
    """
    Clase para construir el archivo de Excel en memoria para el Libro de Compras.
    """
    def __init__(self, title, columns, data, totals, company_data, from_date, to_date, report_summary):
        self.title = title
        self.columns = [col for col in columns if not col.get("hidden")]
        self.totals = totals
        self.company_data = company_data
        self.from_date = from_date
        self.to_date = to_date
        self.report_summary = report_summary

        self.workbook = Workbook()
        self.sheet = self.workbook.active
        self.sheet.title = "Reporte de Compras"

        # Definimos los estilos comunes
        self.default_font = Font(name='Calibri', size=8)
        self.header_font = Font(name='Calibri', size=8, bold=True)
        self.header_font_white = Font(name='Calibri', size=8, bold=True, color="FFFFFF")
        self.total_font = Font(name='Calibri', size=8, bold=True)
        self.title_font = Font(name='Calibri', size=14, bold=True, color="1E293B")
        self.meta_title_font = Font(name='Calibri', size=8, bold=True, color="475569")
        self.meta_value_font = Font(name='Calibri', size=8, color="1E293B")

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
        self.sub_header_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid") # Soft light grey
        self.zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid") # Very soft blue/grey
        self.total_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid") # Total background
        self.alert_fill = PatternFill(start_color="ECFDF5", end_color="ECFDF5", fill_type="solid") # Light emerald for summary

        self.data_alignment = Alignment(horizontal="left", vertical="center")
        self.numeric_format = '#,##0.00'
        self.int_format = '0'

        # Procesar y asignar números de secuencia a todos los datos
        self.data = self.process_data(data)

    def _add_report_header(self) -> int:
        ws = self.sheet
        
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

    def _build_multi_level_headers(self, start_row: int) -> int:
        """Construye los encabezados de varios niveles para la tabla principal."""
        current_row = start_row

        header_levels = [
            [{"text": _("Compras a Contribuyentes"), "start_col": 16, "span": 6}],
            [
                {"text": _("Tasa Reducida 8%"), "start_col": 16, "span": 2},
                {"text": _("Tasa General 16%"), "start_col": 18, "span": 2},
                {"text": _("Tasa General + Adicional 31%"), "start_col": 20, "span": 2},
                {"text": _("Retención"), "start_col": 23, "span": 6},
            ],
        ]

        for level, level_headers in enumerate(header_levels):
            for header_info in level_headers:
                span = header_info["span"]
                start_col = header_info["start_col"]
                fill = self.header_fill_primary if level == 0 else self.header_fill_secondary
                
                # Apply styles to all cells in the span
                for c_offset in range(span):
                    cell = self.sheet.cell(row=current_row, column=start_col + c_offset)
                    cell.fill = fill
                    cell.border = self.header_border
                
                # Write and merge
                cell = self.sheet.cell(row=current_row, column=start_col, value=header_info["text"])
                cell.font = self.header_font_white
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                if span > 1:
                    self.sheet.merge_cells(
                        start_row=current_row,
                        start_column=start_col,
                        end_row=current_row,
                        end_column=start_col + span - 1,
                    )
            current_row += 1

        for col_index, col_def in enumerate(self.columns, start=1):
            header = col_def.get("label")
            cell = self.sheet.cell(row=current_row, column=col_index, value=header)
            cell.font = self.header_font_white
            cell.fill = self.header_fill_primary
            cell.border = self.header_border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            self.sheet.row_dimensions[current_row].height = 28
            self.sheet.column_dimensions[get_column_letter(col_index)].width = (
                6 if col_def.get("fieldname") == "sequence_number" else 13
            )

        return current_row

    def _write_data_rows(self, start_row: int) -> int:
        """Escribe las filas de datos en la tabla principal."""
        row_index = start_row + 1
        for i, row_data in enumerate(self.data):
            fill = self.zebra_fill if i % 2 == 0 else None
            for col_index, col in enumerate(self.columns, start=1):
                fieldname = col.get("fieldname")
                cell_value = row_data.get(fieldname)

                cell = self.sheet.cell(row=row_index, column=col_index, value=cell_value)
                cell.font = self.default_font
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill

                if isinstance(cell_value, (int, float)):
                    cell.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    cell.number_format = self.int_format if fieldname == "sequence_number" else self.numeric_format
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

            self.sheet.row_dimensions[row_index].height = 18
            row_index += 1
        return row_index

    def _write_totals_row(self, start_row: int) -> int:
        """Escribe la fila de totales al final de la tabla principal."""
        total_row_index = start_row
        
        # Style the entire row first
        for col_index in range(1, len(self.columns) + 1):
            cell = self.sheet.cell(row=total_row_index, column=col_index)
            cell.font = self.total_font
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_label_cell = self.sheet.cell(row=total_row_index, column=1, value=_("Totales"))
        total_label_cell.font = self.total_font
        total_label_cell.border = self.total_border
        total_label_cell.fill = self.total_fill

        for col_index, col in enumerate(self.columns, start=1):
            fieldname = col.get("fieldname")
            if fieldname in self.totals:
                total_value = self.totals.get(fieldname)
                total_cell = self.sheet.cell(row=total_row_index, column=col_index, value=total_value)
                total_cell.font = self.total_font
                total_cell.border = self.total_border
                total_cell.fill = self.total_fill
                total_cell.number_format = self.numeric_format
                total_cell.alignment = Alignment(horizontal="right", vertical="center")

        self.sheet.row_dimensions[total_row_index].height = 20
        return total_row_index

    def _build_main_table(self, start_row: int) -> int:
        """Construye la tabla principal con encabezados, datos y totales."""
        headers_last_row = self._build_multi_level_headers(start_row)
        data_last_row = self._write_data_rows(headers_last_row)
        totals_last_row = self._write_totals_row(data_last_row)
        return totals_last_row

    def _add_summary_table(self, start_row: int) -> int:
        """Construye la tabla de resumen de totales."""
        if not self.totals:
            return start_row

        current_row = start_row + 2
        summary_start_col = 13

        # Configuración de encabezados del resumen
        summary_headers = [
            {"text": _("RESUMEN"), "start_col": summary_start_col, "span": 5, "align": "center"},
            {"text": _("Base Imponible"), "start_col": summary_start_col + 5, "span": 1, "align": "center"},
            {"text": _("Crédito Fiscal"), "start_col": summary_start_col + 6, "span": 1, "align": "center"},
            {"text": _("Retención"), "start_col": summary_start_col + 7, "span": 1, "align": "center"},
        ]

        for header_info in summary_headers:
            span = header_info["span"]
            start_col = header_info["start_col"]
            
            for c_offset in range(span):
                cell = self.sheet.cell(row=current_row, column=start_col + c_offset)
                cell.fill = self.header_fill_primary
                cell.border = self.header_border
                
            cell = self.sheet.cell(row=current_row, column=start_col, value=header_info["text"])
            cell.font = self.header_font_white
            cell.alignment = Alignment(horizontal=header_info["align"], vertical="center", wrap_text=True)
            self.sheet.column_dimensions[get_column_letter(start_col)].width = 12
            if span > 1:
                self.sheet.merge_cells(
                    start_row=current_row,
                    start_column=start_col,
                    end_row=current_row,
                    end_column=start_col + span - 1,
                )
        self.sheet.row_dimensions[current_row].height = 24

        start_table_row = current_row
        current_row += 1

        summary_rows = [
            {"concept": _("Compras no gravadas y/o sin derecho a crédito fiscal"),
             "base": self.totals.get("total_exempt", 0), "credit": 0, "retention": 0},

            {"concept": _("Importaciones gravadas por alícuota general"),
             "base": self.totals.get("import_base_general", 0),
             "credit": self.totals.get("import_impuesto_general", 0),
             "retention": 0},

            {"concept": _(" Importaciones gravadas por alícuota general más adicional"),
             "base": self.totals.get("import_base_adicional", 0),
             "credit": self.totals.get("import_impuesto_adicional", 0),
             "retention": 0},

            {"concept": _("Importaciones gravadas por alícuota reducida"),
             "base": self.totals.get("import_base_reducida", 0),
             "credit": self.totals.get("import_impuesto_reducida", 0),
             "retention": 0},

            {"concept": _("Compras Internas (tasa general)"),
             "base": self.totals.get("base_general", 0),
             "credit": self.totals.get("impuesto_general", 0),
             "retention": self.totals.get("retencion_general", 0)},

            {"concept": _("Compras Internas (tasa general + adicional)"),
             "base": self.totals.get("base_adicional", 0),
             "credit": self.totals.get("impuesto_adicional", 0),
             "retention": self.totals.get("retencion_adicional", 0)},

            {"concept": _("Compras Internas (tasa reducida)"),
             "base": self.totals.get("base_reducida", 0),
             "credit": self.totals.get("impuesto_reducida", 0),
             "retention": self.totals.get("retencion_reducida", 0)},
        ]

        for i, row_data in enumerate(summary_rows):
            fill = self.zebra_fill if i % 2 == 0 else None
            
            for c_offset in range(5):
                cell = self.sheet.cell(row=current_row, column=summary_start_col + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                    
            concept_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=row_data["concept"])
            concept_cell.font = self.default_font
            self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

            base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=row_data["base"])
            credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=row_data["credit"])
            retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=row_data["retention"])

            for cell in [base_cell, credit_cell, retention_cell]:
                cell.font = self.default_font
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                cell.number_format = self.numeric_format
                cell.alignment = Alignment(horizontal="right", vertical="center")
            
            self.sheet.row_dimensions[current_row].height = 18
            current_row += 1

        # Fila de totales del resumen
        total_base = sum(row["base"] for row in summary_rows)
        total_credit = sum(row["credit"] for row in summary_rows)
        total_retention = sum(row["retention"] for row in summary_rows)

        for c_idx in range(summary_start_col, summary_start_col + 8):
            cell = self.sheet.cell(row=current_row, column=c_idx)
            cell.font = self.total_font
            cell.fill = self.total_fill
            cell.border = self.total_border

        total_label_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=_("Total"))
        total_label_cell.font = self.total_font
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

        total_base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=total_base)
        total_credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=total_credit)
        total_retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=total_retention)

        for cell in [total_base_cell, total_credit_cell, total_retention_cell]:
            cell.font = self.total_font
            cell.number_format = self.numeric_format
            cell.alignment = Alignment(horizontal="right", vertical="center")

        self.sheet.row_dimensions[current_row].height = 20
        return self.sheet.max_row

    def _add_taxable_vs_iva_table(self, start_row: int) -> int:
        """Construye un cuadrito aparte con el resumen de la base imponible vs. IVA."""
        if not self.totals:
            return start_row

        current_row = start_row + 2
        summary_start_col = 13

        # Título del cuadrito
        for c_idx in range(summary_start_col, summary_start_col + 8):
            cell = self.sheet.cell(row=current_row, column=c_idx)
            cell.fill = self.header_fill_primary
            cell.border = self.header_border
            
        title_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=_("RESUMEN BASE IMPONIBLE vs. IVA"))
        title_cell.font = self.header_font_white
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 7)
        self.sheet.row_dimensions[current_row].height = 24

        current_row += 1
        headers = [_("Concepto / Alícuota"), _("Base Imponible"), _("Crédito Fiscal"), _("Retención")]

        for c_offset in range(5):
            cell = self.sheet.cell(row=current_row, column=summary_start_col + c_offset)
            cell.fill = self.header_fill_secondary
            cell.border = self.header_border
            
        concept_header_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=headers[0])
        concept_header_cell.font = self.header_font_white
        concept_header_cell.alignment = Alignment(horizontal="center", vertical="center")
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

        for i, h in enumerate(headers[1:], start=5):
            c = self.sheet.cell(row=current_row, column=summary_start_col + i, value=h)
            c.font = self.header_font_white
            c.fill = self.header_fill_secondary
            c.border = self.header_border
            c.alignment = Alignment(horizontal="center", vertical="center")
        self.sheet.row_dimensions[current_row].height = 20

        start_table_row = current_row
        current_row += 1

        rows_data = [
            {"concept": _("Compras Internas afectadas por alícuota general (16%)"), 
             "base": self.totals.get("base_general", 0), 
             "credit": self.totals.get("impuesto_general", 0), 
             "retention": self.totals.get("retencion_general", 0)},
            {"concept": _("Compras Internas afectadas por alícuota reducida (8%)"), 
             "base": self.totals.get("base_reducida", 0), 
             "credit": self.totals.get("impuesto_reducida", 0), 
             "retention": self.totals.get("retencion_reducida", 0)},
            {"concept": _("Compras Internas afectadas por alícuota general + adicional (31%)"), 
             "base": self.totals.get("base_adicional", 0), 
             "credit": self.totals.get("impuesto_adicional", 0), 
             "retention": self.totals.get("retencion_adicional", 0)},
        ]

        for idx, row_data in enumerate(rows_data):
            fill = self.zebra_fill if idx % 2 == 0 else None
            
            for c_offset in range(5):
                cell = self.sheet.cell(row=current_row, column=summary_start_col + c_offset)
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                    
            concept_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=row_data["concept"])
            concept_cell.font = self.default_font
            self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

            base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=row_data["base"])
            credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=row_data["credit"])
            retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=row_data["retention"])

            for cell in [base_cell, credit_cell, retention_cell]:
                cell.font = self.default_font
                cell.border = self.thin_border
                if fill:
                    cell.fill = fill
                cell.number_format = self.numeric_format
                cell.alignment = Alignment(horizontal="right", vertical="center")
            
            self.sheet.row_dimensions[current_row].height = 18
            current_row += 1

        # Fila de totales del cuadrito
        total_base = sum(row["base"] for row in rows_data)
        total_credit = sum(row["credit"] for row in rows_data)
        total_retention = sum(row["retention"] for row in rows_data)

        for c_idx in range(summary_start_col, summary_start_col + 8):
            cell = self.sheet.cell(row=current_row, column=c_idx)
            cell.font = self.total_font
            cell.fill = self.alert_fill
            cell.border = self.total_border

        total_label_cell = self.sheet.cell(row=current_row, column=summary_start_col, value=_("Total"))
        total_label_cell.font = self.total_font
        self.sheet.merge_cells(start_row=current_row, start_column=summary_start_col, end_row=current_row, end_column=summary_start_col + 4)

        total_base_cell = self.sheet.cell(row=current_row, column=summary_start_col + 5, value=total_base)
        total_credit_cell = self.sheet.cell(row=current_row, column=summary_start_col + 6, value=total_credit)
        total_retention_cell = self.sheet.cell(row=current_row, column=summary_start_col + 7, value=total_retention)

        for cell in [total_base_cell, total_credit_cell, total_retention_cell]:
            cell.font = self.total_font
            cell.number_format = self.numeric_format
            cell.alignment = Alignment(horizontal="right", vertical="center")

        self.sheet.row_dimensions[current_row].height = 20
        return self.sheet.max_row

    def build(self):
        """
        Construye el libro de Excel orquestando los métodos de construcción.
        """
        try:
            last_row_header = self._add_report_header()
            last_row_main_table = self._build_main_table(last_row_header)
            last_row_summary = self._add_summary_table(last_row_main_table)
            self._add_taxable_vs_iva_table(last_row_summary)

            file_stream = BytesIO()
            self.workbook.save(file_stream)
            file_stream.seek(0)
            return file_stream
        except Exception as e:
            frappe.throw(_("Ocurrió un error al construir el archivo de Excel: {0}").format(e))


    def process_data(self, data: list[dict]) -> list[dict]:
        processed_data = []

        for invoice in data:
            processed_invoice = invoice.copy()

            processed_invoice['fecha_entrega'] = ''
            processed_invoice['porcentaje_ret'] = ''
            processed_invoice['taxes_and_charges_deducted'] = 0.0
            processed_invoice['nro_comprobante_retencion'] = ''

            if invoice.get("nro_comprobante_retencion"):

                withholding_voucher = invoice.copy()

                withholding_voucher['bill_no'] = ''
                withholding_voucher['grand_total'] = 0.0
                withholding_voucher['bill_control'] = ''
                withholding_voucher['base_general'] = 0.0
                withholding_voucher['total_exempt'] = 0.0
                withholding_voucher['base_reducida'] = 0.0
                withholding_voucher['base_adicional'] = 0.0
                withholding_voucher['impuesto_general'] = 0.0
                withholding_voucher['impuesto_reducida'] = 0.0
                withholding_voucher['impuesto_adicional'] = 0.0
                withholding_voucher['affected_invoice_number'] = invoice.get('bill_no')

                processed_data.append(withholding_voucher)

            processed_data.append(processed_invoice)

        # Asignar el número de secuencia después de procesar y duplicar filas
        for i, row in enumerate(processed_data):
            row["sequence_number"] = i + 1

        return processed_data

@frappe.whitelist()
def create_excel_file(report_name, filters=None, **kwargs):
    """
    Genera el archivo de Excel directamente y lo guarda.
    """
    if not filters:
        filters = kwargs.get("filters_json")

    if isinstance(filters, str):
        filters = json.loads(filters)

    try:

        columns, data, message, chart, report_summary = execute(filters)

        counter_column = {
            "label": "Nr Oper.",
            "fieldname": "sequence_number",
            "width": 50
        }
        columns.insert(0, counter_column)

        totals = get_totals_from_data(data)

        if not data:
            frappe.throw(_("No se encontraron datos para los filtros seleccionados."))

        company_doc = frappe.get_doc("Company", filters.get("company"))
        address_name = company_doc.get("custom_company_primary_address")
        company_address = frappe.db.get_value("Address", address_name, "address_line1") if address_name else _("Dirección no disponible")

        company_data = {
            "company_name": company_doc.company_name,
            "tax_id": company_doc.tax_id,
            "is_special_taxpayer": company_doc.is_special_taxpayer,
            "address": company_address
        }

        from_date = frappe.utils.getdate(filters.get("from_date") or filters.get("date_from"))
        to_date = frappe.utils.getdate(filters.get("to_date"))

        title = _("Libro de Compras")

        builder = ExcelBuilder(
            title,
            columns,
            data,
            totals,
            company_data,
            from_date,
            to_date,
            report_summary
        )
        excel_content = builder.build()

        excel_content_bytes = excel_content.getvalue()
        base64_content = base64.b64encode(excel_content_bytes).decode('utf-8')

        safe_company: str = company_data["company_name"].replace("/", "-").replace("\\", "-")
        filename: str = f"{title} - {safe_company} - {from_date.strftime('%d-%m-%Y')} al {to_date.strftime('%d-%m-%Y')}.xlsx"

        return {
            "type": "download",
            "filename": filename,
            "filecontent": base64_content
        }


    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error en create_excel_file")
        frappe.throw(_("Ocurrió un error al generar el archivo de Excel: {0}").format(e))