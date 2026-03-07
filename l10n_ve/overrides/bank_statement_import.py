import frappe
from frappe import _
from frappe.utils import flt, getdate, escape_html, get_link_to_form
from datetime import datetime
import time
from typing import Any
import csv
import os
import unicodedata
import io
import openpyxl
import xlrd
from bs4 import BeautifulSoup
from erpnext.accounts.doctype.bank_statement_import.bank_statement_import import BankStatementImport

HTML_LIKE_XLS_ERRORS = (
    "Expected BOF record; found b'<table",
    "found b'<html",
    "startswith first arg must be str",
)

BATCH_SIZE = 500

EXCLUSION_KEYWORDS = (
    "total", "saldo", "final", "resumen",
    "importe", "debito total", "saldo final",
)


class CustomBankStatementImport(BankStatementImport):
    def validate(self):
        try:
            super().validate()
        except Exception as e:
            error_msg = str(e)
            if any(err in error_msg for err in HTML_LIKE_XLS_ERRORS):
                frappe.log_error(
                    title=_("XLS con formato HTML detectado en validación"),
                    message=error_msg
                )
            else:
                raise


@frappe.whitelist()
def get_preview_from_template(
    data_import: str,
    import_file: str = None,
    google_sheets_url: str = None,
) -> dict[str, Any]:
    """Genera una vista previa del archivo importado, soportando XLS con HTML."""
    try:
        doc = frappe.get_doc("Bank Statement Import", data_import)
        doc.check_permission("read")
        return doc.get_preview_from_template(import_file, google_sheets_url)
    except Exception:
        error_msg = str(frappe.get_traceback())
        is_html_xls = any(err in error_msg for err in HTML_LIKE_XLS_ERRORS)

        if not is_html_xls or not import_file:
            raise

        file_path = _validate_file_path(import_file)
        data = _parse_html_as_table(file_path)

        if data:
            return {"columns": data[0], "data": data[1:]}

        raise


@frappe.whitelist()
def start_custom_import(docname: str) -> dict[str, Any]:
    """Inicia el proceso de importación en segundo plano."""
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

    frappe.msgprint(_("La importación se está procesando en segundo plano."
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


def _process_import_logic(doc, start_time: float) -> None:
    """Orquesta la lectura, mapeo e importación de transacciones bancarias."""
    file_path = _validate_file_path(doc.import_file)
    file_extension = os.path.splitext(doc.import_file)[1].lstrip('.')

    data = _read_file_data(file_path, file_extension)

    if not data or len(data) < 2:
        frappe.throw(_("No se pudieron leer los datos del archivo o el archivo está vacío."))

    column_to_field_map, header_row_index = _resolve_column_mapping(doc, data)

    transactions_data = data[header_row_index + 1:]
    header_indexes = {
        h: i for i, h in enumerate(data[header_row_index])
        if h in column_to_field_map
    }

    stats = _import_transactions(
        doc, transactions_data, column_to_field_map,
        header_indexes, header_row_index
    )

    _finalize_import(doc, stats, start_time)


def _validate_file_path(import_file: str) -> str:
    """Valida que la ruta del archivo esté dentro del sitio."""
    file_path = os.path.join(frappe.get_site_path(), import_file.lstrip('/'))
    if not os.path.abspath(file_path).startswith(os.path.abspath(frappe.get_site_path())):
        frappe.throw(_("Ruta de archivo inválida"))
    return file_path


def _read_file_data(file_path: str, extension: str) -> list[list]:
    """Lee el contenido del archivo según su extensión."""
    if extension == 'csv':
        return _read_csv(file_path)
    elif extension == 'xlsx':
        return _read_xlsx(file_path)
    elif extension == 'xls':
        return _read_xls(file_path)
    else:
        frappe.throw(_("Formato de archivo no soportado. Solo se aceptan CSV, XLS y XLSX."))


def _read_csv(file_path: str) -> list[list]:
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            return list(csv.reader(f))
    except (IOError, csv.Error) as e:
        frappe.throw(_("Error al leer el archivo CSV: {0}").format(escape_html(str(e))))


def _read_xlsx(file_path: str) -> list[list]:
    try:
        data = []
        workbook = openpyxl.load_workbook(file_path, read_only=True)
        for sheet in workbook:
            data.extend(
                ([cell if cell is not None else "" for cell in row])
                for row in sheet.iter_rows(values_only=True)
            )
        return data
    except Exception as e:
        frappe.throw(_("Error al leer el archivo XLSX: {0}").format(escape_html(str(e))))


def _read_xls(file_path: str) -> list[list]:
    """Lee un archivo XLS, con fallback a HTML si el formato es incorrecto."""
    try:
        workbook = xlrd.open_workbook(file_path)
    except Exception as e:
        if any(err in str(e) for err in HTML_LIKE_XLS_ERRORS):
            return _parse_html_as_table(file_path)
        frappe.throw(_("Error al leer el archivo XLS: {0}").format(escape_html(str(e))))

    data = []
    for sheet in workbook.sheets():
        for row_idx in range(sheet.nrows):
            data.append([
                _process_xls_cell(sheet, row_idx, col_idx, workbook.datemode)
                for col_idx in range(sheet.ncols)
            ])

    return data


def _process_xls_cell(sheet, row_idx: int, col_idx: int, datemode: int) -> str:
    """Procesa una celda XLS, convirtiendo fechas al formato dd/mm/YYYY."""
    cell_value = sheet.cell_value(row_idx, col_idx)
    if cell_value is None:
        return ""

    if sheet.cell_type(row_idx, col_idx) == xlrd.XL_CELL_DATE:
        date_tuple = xlrd.xldate_as_tuple(cell_value, datemode)
        return datetime(*date_tuple[:3]).strftime("%d/%m/%Y")

    return cell_value


def _parse_html_as_table(file_path: str) -> list[list]:
    """Parsea un archivo XLS que en realidad contiene HTML."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        soup = BeautifulSoup(content, "html.parser")
        table = soup.find("table")
        if table:
            data = []
            for row in table.find_all("tr"):
                cols = row.find_all(["td", "th"])
                data.append([ele.get_text(strip=True) for ele in cols])
            return data
        return []
    except Exception as e:
        frappe.throw(
            _("Error al leer el archivo XLS (HTML): {0}").format(escape_html(str(e)))
        )


def _normalize_text(text: str) -> str:
    """Normaliza texto removiendo acentos y convirtiendo a minúsculas."""
    return "".join(
        c for c in unicodedata.normalize('NFD', text.lower().strip())
        if unicodedata.category(c) != 'Mn'
    )


def _resolve_column_mapping(doc, data: list[list]) -> tuple[dict[str, str], int]:
    """Resuelve el mapeo de columnas y detecta la fila de encabezados."""
    if not doc.bank:
        frappe.throw(_("Por favor, seleccione un banco para la importación."))

    column_to_field_map = _get_bank_column_map(doc.bank)

    expected_headers = list(column_to_field_map.keys())
    normalized_expected = {_normalize_text(h): h for h in expected_headers}

    best_match_count = 0
    best_match_index = -1
    best_match_normalized = {}

    for i, row in enumerate(data):
        row_normalized = {
            _normalize_text(str(x)): str(x).strip()
            for x in row if x
        }
        match_count = sum(1 for h in normalized_expected if h in row_normalized)
        if match_count > best_match_count:
            best_match_count = match_count
            best_match_index = i
            best_match_normalized = row_normalized

    if best_match_index == -1:
        frappe.throw(
            _("No se encontró una fila de encabezados con todas las columnas"
              " requeridas: {0}").format(", ".join(expected_headers)),
            title=_("Encabezados no encontrados")
        )

    _validate_missing_headers(normalized_expected, best_match_normalized, column_to_field_map)

    final_map = {
        best_match_normalized[norm_h]: column_to_field_map[orig_h]
        for norm_h, orig_h in normalized_expected.items()
        if norm_h in best_match_normalized
    }

    return final_map, best_match_index


def _get_bank_column_map(bank_name: str) -> dict[str, str]:
    """Obtiene el mapeo de columnas configurado en el banco."""
    try:
        bank_doc = frappe.get_doc("Bank", bank_name)
        if hasattr(bank_doc, 'bank_transaction_mapping') and bank_doc.bank_transaction_mapping:
            return {
                mapping.file_field: mapping.bank_transaction_field
                for mapping in bank_doc.bank_transaction_mapping
            }

        bank_link = get_link_to_form("Bank", bank_name)
        frappe.throw(
            _("El banco {0} no tiene un mapeo de campos configurado. "
              "Por favor, vaya a la configuración del banco y defina las "
              "columnas en la tabla 'Mapeo de Transacciones Bancarias'.").format(bank_link),
            title=_("Configuración Requerida")
        )

    except frappe.DoesNotExistError:
        frappe.throw(_("El banco '{0}' no existe o no se pudo cargar.").format(bank_name))

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            _("Error al cargar el mapeo de transacciones bancarias "
              "del banco '{0}'").format(bank_name)
        )
        frappe.throw(
            _("Ocurrió un error al cargar la configuración "
              "del banco: {0}").format(escape_html(str(e)))
        )


def _validate_missing_headers(
    normalized_expected: dict[str, str],
    row_normalized: dict[str, str],
    column_to_field_map: dict[str, str],
) -> None:
    """Valida que no falten columnas obligatorias."""
    found = row_normalized.keys()
    missing = [
        f"{normalized_expected[norm_h]} "
        f"(para el campo: {column_to_field_map[normalized_expected[norm_h]]})"
        for norm_h in normalized_expected
        if norm_h not in found
    ]
    if missing:
        frappe.throw(
            _("No se encontraron las siguientes columnas obligatorias en el archivo:"
              "<br><b>{0}</b><br><br>Por favor, corrija el nombre de las columnas en el "
              "archivo o ajuste el mapeo en la configuración del banco.").format(
                "<br>".join(missing)
            ),
            title=_("Columnas Obligatorias Faltantes")
        )


def _should_exclude_row(row_data: list) -> bool:
    """Comprueba si una fila contiene alguna palabra clave de exclusión."""
    return any(
        keyword in _normalize_text(str(val))
        for val in row_data
        for keyword in EXCLUSION_KEYWORDS
    )


def _import_transactions(
    doc,
    transactions_data: list[list],
    column_to_field_map: dict[str, str],
    header_indexes: dict[str, int],
    header_row_index: int,
) -> dict:
    """Importa las transacciones y retorna estadísticas."""
    transactions_created = 0
    errors = []
    skipped_rows = []

    for i, row in enumerate(transactions_data):
        row_num = header_row_index + 2 + i
        try:
            if not any(row):
                skipped_rows.append(str(row_num))
                continue

            if _should_exclude_row(row):
                skipped_rows.append(str(row_num))
                continue

            if not _is_valid_row(row, column_to_field_map, header_indexes):
                skipped_rows.append(str(row_num))
                continue

            new_transaction = _build_bank_transaction(
                doc, row, column_to_field_map, header_indexes
            )

            if flt(new_transaction.withdrawal) > 0 and flt(new_transaction.deposit) > 0:
                errors.append(
                    _("Error en la fila {0}: La fila tiene valores "
                      "tanto en Débito como en Crédito.").format(row_num)
                )
                continue

            if not flt(new_transaction.withdrawal) and not flt(new_transaction.deposit):
                skipped_rows.append(str(row_num))
                continue

            if _is_duplicate_transaction(new_transaction):
                skipped_rows.append(
                    f"{row_num} ({_('Ref. Duplicada')}: {new_transaction.reference_number})"
                )
                continue

            new_transaction.allocated_amount = new_transaction.withdrawal
            new_transaction.unallocated_amount = new_transaction.deposit

            new_transaction.flags.ignore_permissions = True
            new_transaction.insert()
            new_transaction.submit()

            transactions_created += 1

            if transactions_created % BATCH_SIZE == 0:
                frappe.db.commit()
                _publish_progress(doc.name, transactions_created, skipped_rows)

        except Exception as e:
            errors.append(_("Error en la fila {0}: {1}").format(row_num, escape_html(str(e))))
            frappe.log_error(frappe.get_traceback(), _("Error en importación de extracto bancario"))

    return {
        "transactions_created": transactions_created,
        "errors": errors,
        "skipped_rows": skipped_rows,
    }


def _is_valid_row(
    row: list,
    column_to_field_map: dict[str, str],
    header_indexes: dict[str, int],
) -> bool:
    """Verifica que la fila tenga todas las columnas requeridas con valor."""
    for col_name in column_to_field_map:
        idx = header_indexes.get(col_name)
        if idx is None or idx >= len(row) or not str(row[idx]).strip():
            return False
    return True


def _build_bank_transaction(
    doc,
    row: list,
    column_to_field_map: dict[str, str],
    header_indexes: dict[str, int],
):
    """Crea un Bank Transaction a partir de una fila de datos."""
    new_transaction = frappe.new_doc("Bank Transaction")
    new_transaction.company = doc.company
    new_transaction.bank_account = doc.bank_account

    for col_name, field_name in column_to_field_map.items():
        idx = header_indexes.get(col_name)
        value = row[idx] if idx is not None and idx < len(row) else None

        if not value:
            continue

        if field_name in ("deposit", "withdrawal"):
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

    return new_transaction


def _is_duplicate_transaction(transaction) -> bool:
    """Verifica si la transacción ya existe en el sistema."""
    if not transaction.reference_number:
        return False

    filters = {
        "bank_account": transaction.bank_account,
        "reference_number": transaction.reference_number,
        "docstatus": ["!=", 2],
        "date": transaction.date,
    }
    if flt(transaction.withdrawal) > 0:
        filters["withdrawal"] = transaction.withdrawal
    elif flt(transaction.deposit) > 0:
        filters["deposit"] = transaction.deposit

    return bool(frappe.db.exists("Bank Transaction", filters))


def _publish_progress(doc_name: str, created: int, skipped_rows: list[str]) -> None:
    """Publica progreso parcial de la importación."""
    msg = _("Procesando... {0} transacciones creadas.").format(created)
    if skipped_rows:
        msg += "<br>" + _("Últimas omitidas: {0}").format(", ".join(skipped_rows[-5:]))

    frappe.log_error(
        title=_("Progreso de Importación {0}").format(doc_name),
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


def _finalize_import(doc, stats: dict, start_time: float) -> None:
    """Determina el status final y envía notificaciones."""
    transactions_created = stats["transactions_created"]
    errors = stats["errors"]
    skipped_rows = stats["skipped_rows"]

    duration = round(time.time() - start_time, 2)

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
            {"message": _("Proceso completado con errores.") + "<br>" + final_message,
             "title": _("Resultado de la Importación"), "indicator": "orange"},
            user=frappe.session.user
        )
    elif transactions_created > 0:
        frappe.publish_realtime(
            "msgprint",
            {"message": _("¡Importación completada con éxito!") + "<br>" + final_message,
             "title": _("Importación Exitosa"), "indicator": "green"},
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
