import frappe
import frappe.desk.query_report as _qr_module
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import datetime

# Guardar la función original de exportación de manera segura en el propio módulo de Frappe
if not hasattr(_qr_module, "_orig_export_query"):
    _qr_module._orig_export_query = _qr_module._export_query

def apply() -> None:
    """Aplica el patch dinámico reemplazando la función _export_query de Frappe."""
    if not hasattr(_qr_module, "_orig_export_query"):
        _qr_module._orig_export_query = _qr_module._export_query
    _qr_module._export_query = _patched_export_query

def _patched_export_query(form_params, csv_params, populate_response=True):
    try:
        # Convertir form_params a frappe._dict para soportar de manera segura notación de atributos
        form_params = frappe._dict(form_params)
        report_name = form_params.report_name
        file_format_type = form_params.file_format_type
        
        # Validar si el reporte pertenece a los módulos objetivo (L10N Ve o Accounts)
        is_target_report = False
        if report_name:
            report_module = frappe.db.get_value("Report", report_name, "module")
            is_target_report = report_module in ["L10N Ve", "Accounts"]
        
        # Si no pertenece a los módulos objetivo o no es formato Excel, usar comportamiento original
        if not is_target_report or file_format_type != "Excel":
            return _qr_module._orig_export_query(form_params, csv_params, populate_response=populate_response)
            
        # Es un reporte de L10N Ve y formato Excel. Obtenemos el Excel básico generado por Frappe
        res = _qr_module._orig_export_query(form_params, csv_params, populate_response=False)
        if not res:
            return
            
        report_name_out, file_extension, content = res
        
        # Aplicar el diseño premium
        try:
            content = apply_professional_styling(content, report_name)
        except Exception as e:
            # Si el formateo falla, registrar error pero permitir que descargue el archivo sin formato
            frappe.log_error(
                title=f"Error de Estilos Excel: {report_name}",
                message=frappe.get_traceback()
            )
            
        if not populate_response:
            return report_name_out, file_extension, content
            
        from frappe.desk.utils import provide_binary_file
        provide_binary_file(report_name_out, file_extension, content)
        
    except Exception as e:
        # RED DE SEGURIDAD ABSOLUTA: Ante cualquier excepción no controlada en nuestro código,
        # registrar error y descargar el archivo original sin estilos. El usuario NUNCA se quedará sin descargar.
        try:
            frappe.log_error(
                title="Falla crítica en parche de exportación Excel L10N Ve",
                message=frappe.get_traceback()
            )
        except Exception:
            pass
            
        return _qr_module._orig_export_query(form_params, csv_params, populate_response=populate_response)

def apply_professional_styling(content: bytes, report_name: str) -> bytes:
    wb = openpyxl.load_workbook(BytesIO(content))
    
    # Diccionario de traducción al español de nombres de reportes
    report_translations = {
        # Reportes L10N Ve
        "ve_analytical_ledger": "Mayor Analítico",
        "ve_journal_book": "Libro Diario",
        "ve_ledger_book": "Libro Mayor",
        "ve_balance_sheet": "Balance General",
        "ve_profit_and_loss": "Estado de Resultados",
        "ve_cash_flow": "Estado de Flujos de Efectivo",
        "ve_statement_changes_equity": "Estado de Cambios en el Patrimonio",
        "ve_account_balances": "Saldos de Cuentas",
        "ve_fixed_assets_schedule": "Cronograma de Activos Fijos",
        "iva_forma_30": "Declaración de IVA (Forma 30)",
        "prorrata_iva": "Prorrata de IVA",
        "purchase_book": "Libro de Compras",
        "sales_book": "Libro de Ventas",
        "trial_balance_vef": "Balance de Comprobación (VEF)",
        "vat_report": "Reporte de IVA",
        "islr_withholding": "Retenciones de ISLR",
        "vat_withholding": "Retenciones de IVA",
        "customer_retention": "Retenciones de Clientes",
        "igtf_received": "Reporte de IGTF Percibido",
        "Customer Retention": "Retenciones de Clientes",
        "IGTF received": "Reporte de IGTF Percibido",
        "ISLR Withholding": "Retenciones de ISLR",
        "Sales book": "Libro de Ventas",
        "VAT Withholding": "Retenciones de IVA",
        "VAT report": "Reporte de IVA",
        
        # Reportes de Accounts (ERPNext)
        "General Ledger": "Mayor General",
        "Trial Balance": "Balance de Comprobación",
        "Balance Sheet": "Balance General",
        "Profit and Loss Statement": "Estado de Resultados",
        "Cash Flow": "Flujo de Caja",
        "Accounts Payable": "Cuentas por Pagar",
        "Accounts Payable Summary": "Resumen de Cuentas por Pagar",
        "Accounts Receivable": "Cuentas por Cobrar",
        "Accounts Receivable Summary": "Resumen de Cuentas por Cobrar",
        "Asset Depreciation Ledger": "Libro de Depreciación de Activos",
        "Asset Depreciations and Balances": "Depreciaciones y Saldos de Activos",
        "Bank Clearance Summary": "Resumen de Liquidación Bancaria",
        "Bank Reconciliation Statement": "Conciliación Bancaria",
    }
    
    # Obtener el título traducido o formateado
    translated_title = report_translations.get(report_name)
    if not translated_title:
        translated_title = frappe._(report_name)
        if translated_title == report_name:
            translated_title = report_name.replace("_", " ").title()
            
    font_family = "Segoe UI"
    
    # Premium Corporate Palette (Slate & Charcoal)
    c_header_fill = "0F172A"       # Charcoal / Dark Slate (Primary)
    c_zebra_fill = "F8FAFC"        # Zebra muy sutil
    c_total_fill = "F1F5F9"        # Fondo suave para totales
    c_section_color = "0F172A"     # Color del texto de secciones
    c_accent_border = "475569"     # Borde acento (Gris Steel)
    c_grid_border = "E2E8F0"       # Gris suave para cuadrícula normal
    
    # Fuentes profesionales
    header_font = Font(name=font_family, size=11, bold=True, color="FFFFFF")
    data_font = Font(name=font_family, size=10, color="1E293B")
    total_font = Font(name=font_family, size=10, bold=True, color="0F172A")
    section_font = Font(name=font_family, size=10.5, bold=True, color=c_section_color)
    filter_label_font = Font(name=font_family, size=9, bold=True, color="475569")
    filter_val_font = Font(name=font_family, size=9, italic=True, color="1E293B")
    
    # Banners corporativos
    title_font = Font(name=font_family, size=15, bold=True, color="0F172A")
    subtitle_font = Font(name=font_family, size=9.5, italic=True, color="475569")
    
    # Rellenos
    header_fill = PatternFill(start_color=c_header_fill, end_color=c_header_fill, fill_type="solid")
    zebra_fill = PatternFill(start_color=c_zebra_fill, end_color=c_zebra_fill, fill_type="solid")
    total_fill = PatternFill(start_color=c_total_fill, end_color=c_total_fill, fill_type="solid")
    
    # Bordes
    thin_grid = Side(style='thin', color=c_grid_border)
    medium_accent = Side(style='medium', color=c_header_fill)
    thin_accent = Side(style='thin', color=c_accent_border)
    double_accent = Side(style='double', color=c_header_fill)
    
    data_border = Border(left=thin_grid, right=thin_grid, top=thin_grid, bottom=thin_grid)
    total_border = Border(left=thin_grid, right=thin_grid, top=thin_accent, bottom=double_accent)
    
    # Alineaciones
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")
    
    for ws in wb.worksheets:
        # Asegurar líneas de cuadrícula visibles
        ws.views.sheetView[0].showGridLines = True
        
        orig_header_row_idx = 1
        has_empty_row = False
        filters = []
        
        # Encontrar la cabecera original y extraer filtros
        # Optimizamos convirtiendo a lista solo las primeras 30 filas
        first_rows = list(ws.iter_rows(max_row=30, values_only=True))
        for idx, row_cells in enumerate(first_rows):
            if all(v is None or str(v).strip() == "" for v in row_cells):
                orig_header_row_idx = idx + 2
                has_empty_row = True
                break
                
        # Extraer filtros si existen
        if has_empty_row and orig_header_row_idx > 1:
            for r in range(1, orig_header_row_idx - 1):
                label = str(ws.cell(row=r, column=1).value or '').strip()
                val = str(ws.cell(row=r, column=2).value or '').strip()
                if label:
                    filters.append((label.replace(":", ""), val))
            
            # Borrar las filas de filtros originales para reacomodarlas en el banner
            ws.delete_rows(1, orig_header_row_idx - 1)
            
        # Insertar exactamente 4 filas al principio para el banner corporativo
        ws.insert_rows(1, 4)
        header_row_idx = 5
        
        # Diseñar el Banner Corporativo
        # Título del reporte (Traducido al español)
        ws.cell(row=1, column=1).value = str(translated_title).upper()
        ws.cell(row=1, column=1).font = title_font
        ws.row_dimensions[1].height = 24
        
        # Subtítulo con fecha
        generated_on = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.cell(row=2, column=1).value = f"Generado: {generated_on} | Localización Venezuela"
        ws.cell(row=2, column=1).font = subtitle_font
        ws.row_dimensions[2].height = 16
        
        # Filtros en la fila 3
        ws.row_dimensions[3].height = 18
        if filters:
            col_idx = 1
            for label, val in filters:
                if col_idx + 1 > ws.max_column:
                    break
                # Etiqueta
                cell_lbl = ws.cell(row=3, column=col_idx)
                cell_lbl.value = f"{label}:"
                cell_lbl.font = filter_label_font
                cell_lbl.alignment = align_right
                # Valor
                cell_val = ws.cell(row=3, column=col_idx+1)
                cell_val.value = val
                cell_val.font = filter_val_font
                cell_val.alignment = align_left
                col_idx += 2
                
        # Separador visual en fila 4
        for c in range(1, ws.max_column + 1):
            ws.cell(row=4, column=c).border = Border(bottom=thin_accent)
        ws.row_dimensions[4].height = 10
        
        # Formatear cabecera de la tabla principal
        ws.row_dimensions[header_row_idx].height = 28
        header_cells = list(ws.iter_rows(min_row=header_row_idx, max_row=header_row_idx))[0]
        for cell in header_cells:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = align_center
            cell.border = Border(left=thin_grid, right=thin_grid, top=medium_accent, bottom=medium_accent)
            
        # Inicializar longitudes de columna con las de las cabeceras
        max_lens = [len(str(cell.value or '')) for cell in header_cells]
        
        # LÍMITE DE SEGURIDAD PARA REPORTES GRANDES (Fuerza bypass de celdas de datos individuales)
        # Si tiene más de 3000 filas, solo formateamos cabecera, totales y autoajustamos anchos con muestra.
        is_large_sheet = ws.max_row > 3000
        
        if is_large_sheet:
            # Formatear la última fila (totales si corresponde)
            last_row_idx = ws.max_row
            last_row = list(ws.iter_rows(min_row=last_row_idx, max_row=last_row_idx))[0]
            ws.row_dimensions[last_row_idx].height = 21
            
            first_val = str(last_row[0].value or '')
            second_val = str(last_row[1].value or '') if len(last_row) > 1 else ''
            is_totals_row = (
                "total" in first_val.lower() or 
                "total" in second_val.lower() or 
                "totales" in first_val.lower() or 
                "totales" in second_val.lower() or
                "utilidad" in first_val.lower() or
                "excedente" in first_val.lower()
            )
            
            for c_idx, cell in enumerate(last_row):
                val = cell.value
                if is_totals_row:
                    cell.font = total_font
                    cell.fill = total_fill
                    cell.border = total_border
                else:
                    cell.font = data_font
                    cell.border = data_border
                    
                if isinstance(val, (int, float)):
                    cell.alignment = align_right
                    header_label = str(header_cells[c_idx].value or '').lower()
                    if "alícuota" in header_label or "porcentaje" in header_label or "%" in header_label:
                        cell.number_format = '0.00%'
                    else:
                        cell.number_format = '#,##0.00;(#,##0.00);"-"'
                elif isinstance(val, (datetime.date, datetime.datetime)):
                    cell.alignment = align_center
                else:
                    val_str = str(val or '')
                    if len(val_str) == 10 and val_str[4] == '-' and val_str[7] == '-':
                        cell.alignment = align_center
                    else:
                        cell.alignment = align_left
                        
            # Formatear cuerpo completo (rápido, aplicando fuentes, bordes y zebra striping)
            for r_idx, row in enumerate(ws.iter_rows(min_row=header_row_idx + 1, max_row=last_row_idx - 1), start=header_row_idx + 1):
                is_even = (r_idx - header_row_idx) % 2 == 0
                for c_idx, cell in enumerate(row):
                    val = cell.value
                    
                    cell.font = data_font
                    cell.border = data_border
                    if is_even:
                        cell.fill = zebra_fill
                        
                    if isinstance(val, (int, float)):
                        cell.alignment = align_right
                        header_label = str(header_cells[c_idx].value or '').lower()
                        if "alícuota" in header_label or "porcentaje" in header_label or "%" in header_label:
                            cell.number_format = '0.00%'
                        else:
                            cell.number_format = '#,##0.00;(#,##0.00);"-"'
                    elif isinstance(val, (datetime.date, datetime.datetime)):
                        cell.alignment = align_center
                    else:
                        val_str = str(val or '')
                        if len(val_str) == 10 and val_str[4] == '-' and val_str[7] == '-':
                            cell.alignment = align_center
                        else:
                            cell.alignment = align_left
                            
            # Autoajustar usando una muestra de las primeras 50 filas
            sample_rows = list(ws.iter_rows(min_row=header_row_idx + 1, max_row=header_row_idx + 50, values_only=True))
            for row_vals in sample_rows:
                for c_idx, val in enumerate(row_vals):
                    if c_idx >= len(max_lens):
                        break
                    val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val or '')
                    max_lens[c_idx] = max(max_lens[c_idx], len(val_str))
        else:
            # Iterar y formatear todas las celdas secuencialmente (para reportes pequeños/medianos)
            for r_idx, row in enumerate(ws.iter_rows(min_row=header_row_idx + 1), start=header_row_idx + 1):
                first_val = str(row[0].value or '')
                second_val = str(row[1].value or '') if len(row) > 1 else ''
                
                is_totals_row = (
                    "total" in first_val.lower() or 
                    "total" in second_val.lower() or 
                    "totales" in first_val.lower() or 
                    "totales" in second_val.lower() or
                    "utilidad" in first_val.lower() or
                    "excedente" in first_val.lower()
                )
                
                has_numeric_values = False
                for cell in row[1:]:
                    if isinstance(cell.value, (int, float)):
                        has_numeric_values = True
                        break
                        
                is_section_header = not has_numeric_values and not is_totals_row and len(first_val.strip()) > 0
                ws.row_dimensions[r_idx].height = 21
                
                for c_idx, cell in enumerate(row):
                    val = cell.value
                    
                    # Calcular longitud para autoajuste
                    val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val or '')
                    lines = val_str.split('\n')
                    for line in lines:
                        if len(line) > max_lens[c_idx]:
                            max_lens[c_idx] = len(line)
                            
                    cell.font = data_font
                    cell.border = data_border
                    
                    if isinstance(val, (int, float)):
                        cell.alignment = align_right
                        header_label = str(header_cells[c_idx].value or '').lower()
                        if "alícuota" in header_label or "porcentaje" in header_label or "%" in header_label:
                            cell.number_format = '0.00%'
                        else:
                            cell.number_format = '#,##0.00;(#,##0.00);"-"'
                    elif isinstance(val, (datetime.date, datetime.datetime)):
                        cell.alignment = align_center
                    else:
                        if len(val_str) == 10 and val_str[4] == '-' and val_str[7] == '-':
                            cell.alignment = align_center
                        else:
                            cell.alignment = align_left
                            
                    if is_totals_row:
                        cell.font = total_font
                        cell.fill = total_fill
                        cell.border = total_border
                    elif is_section_header:
                        cell.font = section_font
                        cell.border = Border(bottom=thin_accent)
                        if c_idx == 0:
                            cell.alignment = align_left
                    else:
                        if (r_idx - header_row_idx) % 2 == 0:
                            cell.fill = zebra_fill
                            
        # Aplicar anchos calculados
        for c_idx, max_len in enumerate(max_lens):
            col_letter = get_column_letter(c_idx + 1)
            ws.column_dimensions[col_letter].width = max(max_len + 5, 12)
            
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
