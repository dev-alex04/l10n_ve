import frappe
from frappe import _
from frappe.utils import flt, getdate, escape_html
from datetime import datetime
import time
from typing import Any
from frappe.utils import get_link_to_form
import csv
import os
import unicodedata
import io
import openpyxl
import xlrd
from bs4 import BeautifulSoup
from erpnext.accounts.doctype.bank_statement_import.bank_statement_import import BankStatementImport


class CustomBankStatementImport(BankStatementImport):
    def validate(self):
        try:
            super().validate()
        except Exception as e:
            error_msg = str(e)
            html_like_xls_errors = (
                "Expected BOF record; found b'\u003ctable",
                "found b'\u003chtml",
                "startswith first arg must be str",
            )
            if any(err in error_msg for err in html_like_xls_errors):
                pass
            else:
                raise e

@frappe.whitelist()
def get_preview_from_template(data_import, import_file=None, google_sheets_url=None):
    try:
        doc = frappe.get_doc("Bank Statement Import", data_import)
        doc.check_permission("read")
        return doc.get_preview_from_template(
            import_file, google_sheets_url
        )
    except Exception as e:
        error_msg = str(e)
        html_like_xls_errors = (
            "Expected BOF record; found b'\u003ctable",
            "found b'\u003chtml",
            "startswith first arg must be str",
        )
        if any(err in error_msg for err in html_like_xls_errors):
            if import_file:
                file_path = os.path.join(frappe.get_site_path(), import_file.lstrip('/'))
                if not os.path.abspath(file_path).startswith(os.path.abspath(frappe.get_site_path())):
                    frappe.throw(_("Ruta de archivo inválida"))

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    soup = BeautifulSoup(content, "html.parser")
                    table = soup.find("table")
                    if table:
                        data = []
                        rows = table.find_all("tr")
                        for row in rows:
                            cols = row.find_all(["td", "th"])
                            data.append([ele.get_text(strip=True) for ele in cols])
                        if data:
                            return {"columns": data[0], "data": data[1:]}
                except Exception as html_e:
                    frappe.log_error(title=_("Error parsing HTML in XLS preview"), message=frappe.get_traceback())
        raise e

@frappe.whitelist()
def start_custom_import(docname: str) -> dict[str, Any]:
    """
    Inicia el proceso de importación en segundo plano.
    """
    from frappe.utils.background_jobs import is_job_enqueued

    doc = frappe.get_doc("Bank Statement Import", docname)
    doc.check_permission("write")
    if not doc.import_file:
        frappe.throw(_("Por favor, adjunte el archivo del extracto bancario primero."))

    job_id = f"bank_statement_import::{docname}"

    if is_job_enqueued(job_id):
        frappe.throw(_("Ya hay un proceso de importación en curso para este documento." 
                       " Por favor, espere a que termine."))

    frappe.enqueue(
        "l10n_ve.overrides.bank_statement_import.process_custom_import",
        queue="long",
        timeout=3600,
        job_id=job_id,
        docname=docname
    )

    frappe.msgprint(_("La importación se está procesando en segundo plano." \
                      " Recibirá una notificación al finalizar."))

    return {"status": "queued"}


def process_custom_import(docname: str) -> None:
    start_time = time.time()
    frappe.log_error(
        title=_("Inicio de importación de extracto"),
        message=f"Procesando documento: {docname}"
    )
    try:
        doc = frappe.get_doc("Bank Statement Import", docname)
        _process_import_logic(doc, start_time)
    except frappe.exceptions.ValidationError:
        frappe.db.rollback()
        doc = frappe.get_doc("Bank Statement Import", docname)
        doc.status = "Error"
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.log_error(frappe.get_traceback(), _("Error de validación en importación"))
        frappe.publish_realtime(
            "msgprint",
            {"message": _("Error de validación durante la importación. Revise los logs."),
             "title": _("Error de Importación"), "indicator": "red"},
            user=frappe.session.user
        )
    except Exception:
        frappe.db.rollback()
        doc = frappe.get_doc("Bank Statement Import", docname)
        doc.status = "Error"
        doc.save(ignore_permissions=True)
        
        frappe.db.commit()
        frappe.log_error(frappe.get_traceback(), _("Error crítico en importación de extracto bancario"))
        frappe.publish_realtime(
            "msgprint",
            {"message": _("Ocurrió un error crítico durante la importación. Revise los logs."),
             "title": _("Error de Importación"), "indicator": "red"},
            user=frappe.session.user
        )


def _process_import_logic(doc, start_time):
    file_path = os.path.join(frappe.get_site_path(), doc.import_file.lstrip('/'))
    if not os.path.abspath(file_path).startswith(os.path.abspath(frappe.get_site_path())):
        frappe.throw(_("Ruta de archivo inválida"))

    file_extension = os.path.splitext(doc.import_file)[1].lstrip('.')
    data = []

    if file_extension in ['csv']:
        try:
            with open(file_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                data = list(reader)

        except (IOError, csv.Error) as e:
            frappe.throw(_("Error al leer el archivo CSV: {0}").format(escape_html(str(e))))

    elif file_extension in ['xlsx']:
        try:
            workbook = openpyxl.load_workbook(file_path, read_only=True)
            for sheet in workbook:
                data.extend(
                    ([cell if cell is not None else "" for cell in row])
                    for row in sheet.iter_rows(values_only=True)
                )
        except Exception as e:
            frappe.throw(_("Error al leer el archivo XLSX: {0}").format(escape_html(str(e))))

    elif file_extension in ['xls']:
        try:
            workbook = xlrd.open_workbook(file_path)
            for sheet in workbook.sheets():
                for row_idx in range(sheet.nrows):
                    processed_row = []
                    for col_idx in range(sheet.ncols):
                        cell_value = sheet.cell_value(row_idx, col_idx)
                        if cell_value is None:
                            processed_row.append("")
                            continue

                        if sheet.cell_type(row_idx, col_idx) == xlrd.XL_CELL_DATE:
                            date_tuple = xlrd.xldate_as_tuple(cell_value, workbook.datemode)
                            processed_row.append(datetime(*date_tuple[:3]).strftime("%d/%m/%Y"))
                        else:
                            processed_row.append(cell_value)

                    data.append(processed_row)
                    
        except Exception as e:
            if "Expected BOF record; found b'<table" in str(e) or "found b'<html" in str(e):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    soup = BeautifulSoup(content, "html.parser")
                    table = soup.find("table")
                    if table:
                        rows = table.find_all("tr")
                        for row in rows:
                            cols = row.find_all(["td", "th"])
                            data.append([ele.get_text(strip=True) for ele in cols])
                except Exception as html_e:
                    frappe.throw(_("Error al leer el archivo XLS (HTML): {0}").format(escape_html(str(html_e))))
            else:
                frappe.throw(_("Error al leer el archivo XLS: {0}").format(escape_html(str(e))))

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
                           "del banco: {0}").format(escape_html(str(e))))
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
    BATCH_SIZE = 500

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
                        if field_name == "reference_number" and isinstance(value, str):
                            value = "".join(filter(str.isdigit, value))

                        new_transaction.set(field_name, value)

            if flt(new_transaction.withdrawal) > 0 and flt(new_transaction.deposit) > 0:
                errors.append(_("Error en la fila {0}: La fila tiene valores " \
                                "tanto en Débito como en Crédito.").format(row_num))
                continue

            if not flt(new_transaction.withdrawal) and not flt(new_transaction.deposit):
                skipped_rows.append(str(row_num))
                continue

            if new_transaction.reference_number:
                duplicate_filters = {
                    "bank_account": new_transaction.bank_account,
                    "reference_number": new_transaction.reference_number,
                    "docstatus": ["!=", 2],
                    "date": new_transaction.date
                }
                if flt(new_transaction.withdrawal) > 0:
                    duplicate_filters["withdrawal"] = new_transaction.withdrawal
                elif flt(new_transaction.deposit) > 0:
                    duplicate_filters["deposit"] = new_transaction.deposit

                if frappe.db.exists("Bank Transaction", duplicate_filters):
                    skipped_rows.append(f"{row_num} ({_('Ref. Duplicada')}: {new_transaction.reference_number})")
                    continue

            new_transaction.allocated_amount = new_transaction.withdrawal
            new_transaction.unallocated_amount = new_transaction.deposit

            new_transaction.flags.ignore_permissions = True
            new_transaction.insert()
            new_transaction.submit()

            transactions_created += 1

            if transactions_created % BATCH_SIZE == 0:
                frappe.db.commit()
                
                msg = _("Procesando... {0} transacciones creadas.").format(transactions_created)
                if skipped_rows:
                    msg += "<br>" + _("Últimas omitidas: {0}").format(", ".join(skipped_rows[-5:]))

                frappe.log_error(
                    title=_("Progreso de Importación {0}").format(doc.name),
                    message=msg.replace("<br>", "\n")
                )

                frappe.publish_realtime(
                    "msgprint",
                    {
                        "message": msg,
                        "title": _("Progreso"),
                        "indicator": "blue",
                        "alert": True
                    },
                    user=frappe.session.user
                )

        except Exception as e:
            errors.append(_("Error en la fila {0}: {1}").format(row_num, escape_html(str(e))))
            frappe.log_error(frappe.get_traceback(), _("Error en importación de extracto bancario"))

    end_time = time.time()
    duration = round(end_time - start_time, 2)

    if not errors and transactions_created > 0:
        doc.status = "Success"
    elif errors and transactions_created > 0:
        doc.status = "Partial Success"
    else:
        doc.status = "Error"

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    log_summary_parts = [
        f"Importación finalizada para {doc.name}.",
        f"Transacciones creadas: {transactions_created}",
        f"Filas omitidas: {len(skipped_rows)}"
    ]

    if skipped_rows:
        log_summary_parts.append(f"Detalle Omitidas: {', '.join(skipped_rows)}")

    log_summary_parts.append(f"Errores: {len(errors)}")
    log_summary_parts.append(f"Duración: {duration} segundos")

    log_summary = "\n".join(log_summary_parts)
    log_title = f"Fin de importación de extracto: {doc.status}"
    frappe.log_error(title=log_title, message=log_summary)

    summary_parts = []
    if transactions_created > 0:
        summary_parts.append(_("Transacciones creadas: {0}").format(transactions_created))

    if skipped_rows:
        max_display = 20
        skipped_str = ", ".join(skipped_rows[:max_display])
        if len(skipped_rows) > max_display:
            skipped_str += _("... y {0} más (ver Log de Errores)").format(len(skipped_rows) - max_display)

        summary_parts.append(_("Filas omitidas ({0}): {1}").format(
            len(skipped_rows), skipped_str
        ))

    if errors:
        summary_parts.append(_("Errores: <br>{0}").format("<br>".join(errors)))

    summary_parts.append(_("Duración: {0} segundos").format(duration))

    final_message = "<br>".join(summary_parts)

    notification_subject = _("Importación Finalizada: {0}").format(doc.status)
    subject_details = []
    if transactions_created > 0:
        subject_details.append(_("Creadas: {0}").format(transactions_created))
    if skipped_rows:
        subject_details.append(_("Omitidas: {0}").format(len(skipped_rows)))
    if errors:
        subject_details.append(_("Errores: {0}").format(len(errors)))

    if subject_details:
        notification_subject += " (" + ", ".join(subject_details) + ")"

    frappe.get_doc({
        "doctype": "Notification Log",
        "subject": notification_subject,
        "email_content": final_message,
        "for_user": doc.owner,
        "type": "Alert",
        "document_type": "Bank Statement Import",
        "document_name": doc.name,
        "attached_file": doc.import_file
    }).insert(ignore_permissions=True)

    frappe.publish_realtime("notification_priv", user=doc.owner)

    if errors:
        frappe.publish_realtime(
            "msgprint",
            {"message": _("Proceso completado con errores.") + "<br>" + final_message, "title": _("Resultado de la Importación"), "indicator": "orange"},
            user=frappe.session.user
        )
    elif transactions_created > 0:
        frappe.publish_realtime(
            "msgprint",
            {"message": _("¡Importación completada con éxito!") + "<br>" + final_message, "title": _("Importación Exitosa"), "indicator": "green"},
            user=frappe.session.user
        )
    else:
        message = _("No se importaron transacciones.")
        if final_message:
            message += "<br>" + final_message
        frappe.publish_realtime(
            "msgprint",
            {"message": message, "title": _("Resultado de la Importación")},
            user=frappe.session.user
        )
