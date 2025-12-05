import frappe
from frappe import _
from frappe.utils import flt, getdate
from datetime import datetime
from typing import Any
from frappe.utils import get_link_to_form
import csv
import os
import unicodedata
import io
import openpyxl
import xlrd


@frappe.whitelist()
def start_custom_import(docname: str) -> dict[str, Any]:
    """
    Método de importación personalizado y simplificado para extractos bancarios.
    Lee un archivo CSV o Excel y crea documentos de Bank Transaction.
    """

    doc = frappe.get_doc("Bank Statement Import", docname)
    if not doc.import_file:
        frappe.throw(_("Por favor, adjunte el archivo del extracto bancario primero."))

    file_path = os.path.join(frappe.get_site_path(), doc.import_file.lstrip('/'))

    file_extension = os.path.splitext(doc.import_file)[1].lstrip('.')
    data = []

    if file_extension in ['csv']:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                data = list(reader)

        except Exception as e:
            frappe.throw(_("Error al leer el archivo CSV: {0}").format(str(e)))

    elif file_extension in ['xlsx']:
        try:
            with open(file_path, "rb") as f:
                workbook = openpyxl.load_workbook(io.BytesIO(f.read()))
                for sheet in workbook:
                    data.extend(
                        ([cell if cell is not None else "" for cell in row])
                        for row in sheet.iter_rows(values_only=True)
                    )
        except Exception as e:
            frappe.throw(_("Error al leer el archivo XLSX: {0}").format(str(e)))

    elif file_extension in ['xls']:
        try:
            workbook = xlrd.open_workbook(file_path)
            for sheet in workbook.sheets():
                for row_idx in range(sheet.nrows):
                    processed_row = [

                    datetime(*xlrd.xldate_as_tuple(sheet.cell_value(row_idx, col_idx),
                                                    workbook.datemode)[:3]).strftime("%d/%m/%Y")

                    if sheet.cell_type(row_idx, col_idx) == xlrd.XL_CELL_DATE
                    else sheet.cell_value(row_idx, col_idx)
                    if sheet.cell_value(row_idx, col_idx) is not None else ""
                    for col_idx in range(sheet.ncols)

                    ]

                    data.append(processed_row)
        except Exception as e:
            frappe.throw(_("Error al leer el archivo XLS: {0}").format(str(e)))

    else:
        frappe.throw(_("Formato de archivo no soportado. Solo se aceptan CSV, XLS y XLSX."))

    if not data or len(data) < 2:
        frappe.throw(_("No se pudieron leer los datos del archivo o el archivo está vacío."))

    column_to_field_map: dict[str, str] = {}

    if doc.bank:
        try:
            bank_doc = frappe.get_doc("Bank", doc.bank)
            if hasattr(bank_doc, 'bank_transaction_mapping') and bank_doc.bank_transaction_mapping:

                dynamic_map = {mapping.file_field: mapping.bank_transaction_field
                               for mapping in bank_doc.bank_transaction_mapping}

                column_to_field_map = dynamic_map

            else:
                bank_link = get_link_to_form("Bank", doc.bank)
                frappe.throw(
                    _("El banco {0} no tiene un mapeo de campos configurado. "
                      "Por favor, vaya a la configuración del banco y defina las " \
                      "columnas en la tabla 'Mapeo de Transacciones Bancarias'.").format(bank_link),

                    title=_("Configuración Requerida")
                )

        except frappe.DoesNotExistError:
            frappe.throw(_("El banco '{0}' no existe o no se pudo cargar.").format(doc.bank))

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), _("Error al cargar el " \
                                                       "mapeo de transacciones bancarias del " \
                                                       "banco '{0}'").format(doc.bank))

            frappe.throw(_("Ocurrió un error al cargar la configuración " \
                           "del banco: {0}").format(str(e)))
    else:
        frappe.throw(_("Por favor, seleccione un banco para la importación."))

    expected_headers = list(column_to_field_map.keys())

    header_row_index = -1

    best_match_count = 0
    best_match_row_index = -1
    best_match_row_normalized = {}

    normalized_expected_headers = {
        "".join(c for c in unicodedata.normalize('NFD', h.lower())
                  if unicodedata.category(c) != 'Mn'): h for h in expected_headers
    }

    for i, row in enumerate(data):
        row_normalized = {"".join(c for c in unicodedata.normalize('NFD', str(x).lower().strip())
                                    if unicodedata.category(c) != 'Mn'): str(x).strip()
                                    for x in row if x}

        found_headers_count = sum(1 for h in normalized_expected_headers
                                    if h in row_normalized)

        if found_headers_count > best_match_count:
            best_match_count = found_headers_count
            best_match_row_index = i
            best_match_row_normalized = row_normalized

    if best_match_row_index != -1:
        header_row_index = best_match_row_index
        row_normalized = best_match_row_normalized

        original_map = {norm_h: orig_h for norm_h,
                        orig_h in normalized_expected_headers.items()}

        found_normalized_headers = row_normalized.keys()

        missing_header_details = [
            f"{original_map[norm_h]} (para el campo: {column_to_field_map[original_map[norm_h]]})"
            for norm_h in normalized_expected_headers
            if norm_h not in found_normalized_headers
        ]

        if missing_header_details:
            frappe.throw(
                _("No se encontraron las siguientes columnas obligatorias en el archivo:"
                  "<br><b>{0}</b><br><br>Por favor, corrija el nombre de las columnas en el "
                  "archivo o ajuste el mapeo en la configuración del banco.").format("<br>".join(missing_header_details)),
                title=_("Columnas Obligatorias Faltantes")
            )

        column_to_field_map = {row_normalized[norm_h]: column_to_field_map[orig_h]
                               for norm_h, orig_h
                               in normalized_expected_headers.items()
                               if norm_h in row_normalized}


    if header_row_index == -1:
        frappe.throw(_("No se encontró una fila de encabezados con todas las columnas" \
                       " requeridas: {0}").format(", ".join(expected_headers)),
                        title=_("Encabezados no encontrados"))

    file_headers = data[header_row_index]
    header_indexes = {h: i for i, h in enumerate(file_headers) if h in column_to_field_map.keys()}

    transactions_data = data[header_row_index + 1:]

    transactions_created = 0
    errors = []
    skipped_rows = []

    EXCLUSION_KEYWORDS = [
        "total", "saldo", "final", "resumen", "importe", "debito total", "saldo final"
    ]

    def should_exclude_row(row_data):
        """Comprueba si una fila contiene alguna palabra clave de exclusión."""
        normalized_row_values = [
            "".join(c for c in unicodedata.normalize('NFD', str(x).lower().strip())
                    if unicodedata.category(c) != 'Mn')
            for x in row_data
        ]
        for val in normalized_row_values:
            for keyword in EXCLUSION_KEYWORDS:
                if keyword in val:
                    return True
        return False

    for i, row in enumerate(transactions_data):
        row_num = header_row_index + 2 + i
        try:
            if not any(row):
                skipped_rows.append(str(row_num))
                continue

            if should_exclude_row(row):
                skipped_rows.append(str(row_num))
                continue

            is_valid_row = True
            for col_name in column_to_field_map.keys():
                idx = header_indexes.get(col_name)
                if idx is None or idx >= len(row) or not str(row[idx]).strip():
                    is_valid_row = False
                    break

            if not is_valid_row:
                skipped_rows.append(str(row_num))
                continue

            new_transaction = frappe.new_doc("Bank Transaction")
            new_transaction.company = doc.company
            new_transaction.bank_account = doc.bank_account

            for col_name, field_name in column_to_field_map.items():
                idx = header_indexes.get(col_name)
                value = row[idx] if idx is not None and idx < len(row) else None

                if value:
                    if field_name in ["deposit", "withdrawal"]:
                        new_transaction.set(field_name, abs(flt(value)))

                    elif field_name == "date":
                        try:
                            date_obj = datetime.strptime(str(value).split()[0], "%d/%m/%Y").date()
                            new_transaction.set(field_name, date_obj)

                        except (ValueError, TypeError):
                            new_transaction.set(field_name, getdate(value))
                    else:
                        new_transaction.set(field_name, value)

            if flt(new_transaction.withdrawal) > 0 and flt(new_transaction.deposit) > 0:
                errors.append(_("Error en la fila {0}: La fila tiene valores " \
                                "tanto en Débito como en Crédito.").format(row_num))
                continue

            if not flt(new_transaction.withdrawal) and not flt(new_transaction.deposit):
                skipped_rows.append(str(row_num))
                continue

            new_transaction.allocated_amount = new_transaction.withdrawal
            new_transaction.unallocated_amount = new_transaction.deposit

            new_transaction.flags.ignore_permissions = True
            new_transaction.insert()
            new_transaction.submit()

            transactions_created += 1

        except Exception as e:
            errors.append(_("Error en la fila {0}: {1}").format(row_num, str(e)))
            frappe.log_error(frappe.get_traceback(), _("Error en importación de extracto bancario"))

    if not errors and transactions_created > 0:
        doc.status = "Success"
    elif errors and transactions_created > 0:
        doc.status = "Partial Success"
    else:
        doc.status = "Error"

    doc.save(ignore_permissions=True)

    final_message = ""
    if transactions_created > 0:
        final_message += _("Transacciones creadas: {0}").format(transactions_created)

    if skipped_rows:
        final_message += "<br>" + _("Filas omitidas ({0}): {1}").format(
            len(skipped_rows), ", ".join(skipped_rows)
        )

    if errors:
        final_message += "<br>" + _("Errores: <br>{0}").format("<br>".join(errors))
        frappe.msgprint(
            _("Proceso completado con errores.") + "<br>" + final_message,
            title=_("Resultado de la Importación"),
            indicator="orange"
        )
    elif transactions_created > 0:
        frappe.msgprint(
            _("¡Importación completada con éxito!") + "<br>" + final_message,
            title=_("Importación Exitosa"),
            indicator="green"
        )
    else:
        frappe.msgprint(
            _("No se importaron transacciones.") + "<br>" + final_message, title=_("Resultado de la Importación"))

    return {"status": "success", "created": transactions_created}
