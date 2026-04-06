"""
Patch para suprimir el mecanismo automático de Prepared Report de Frappe.

PROBLEMA: Frappe activa prepared_report=1 en BD cuando un reporte tarda más
de 15 segundos. Eso lo condena permanentemente al modo asíncrono (background),
afectando a TODOS los usuarios aunque luego ejecuten el reporte con filtros
ligeros y rápidos.

SOLUCIÓN en dos capas:
  - Capa 2 (este archivo):
    * _patched_execute_script_report: reemplaza el método original SIN el
      threading.Timer que escribe prepared_report=1 en BD. El reporte siempre
      corre en modo interactivo sin importar cuánto tarde.
    * run (registrado vía override_whitelisted_methods en hooks.py): fuerza
      ignore_prepared_report=True para que Frappe nunca consulte el flag de BD.

  - Capa 1 (tasks.py + hooks.py):
    Scheduler cada 15 minutos que resetea cualquier prepared_report=1 que
    haya llegado a BD por paths alternativos no interceptados.
"""
import datetime
import json

import frappe
import frappe.desk.query_report as _qr_module
from frappe.core.doctype.report import report as _report_module


def _patched_execute_script_report(self, filters) -> list:
    """
    Reemplaza Report.execute_script_report suprimiendo el threading.Timer que
    activa prepared_report=1 en la BD cuando el reporte tarda más de 15s.

    El reporte siempre se ejecuta en modo directo (interactivo). La Capa 1
    actúa como red de seguridad adicional si algún path alternativo escribe
    prepared_report=1 en BD.
    """
    start_time = datetime.datetime.now()
    res = []

    try:
        if self.is_standard == "Yes":
            res = self.execute_module(filters)
        else:
            res = self.execute_script(filters)
    finally:
        execution_time = (datetime.datetime.now() - start_time).total_seconds()
        frappe.cache.hset("report_execution_time", self.name, execution_time)

    return res


@frappe.whitelist()
def run(
    report_name,
    filters=None,
    user=None,
    ignore_prepared_report=False,
    custom_columns=None,
    is_tree=False,
    parent_field=None,
    are_default_filters=True,
):
    """
    Override de frappe.desk.query_report.run registrado en override_whitelisted_methods.

    Fuerza ignore_prepared_report=True para que Frappe nunca active el modo
    background, independientemente del valor de prepared_report en la BD.

    Sin type hints en los parámetros: Frappe v15 valida con Pydantic antes de
    llamar la función, y 'filters' llega como JSON string desde el cliente JS.
    Los type hints causarían un FrappeTypeError 417 en cada request.
    """
    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except (ValueError, TypeError):
            filters = None

    return _qr_module.run(
        report_name,
        filters=filters,
        user=user,
        ignore_prepared_report=True,
        custom_columns=custom_columns,
        is_tree=is_tree,
        parent_field=parent_field,
        are_default_filters=are_default_filters,
    )


def apply() -> None:
    """Aplica el patch de execute_script_report. El override de run se registra en hooks.py."""
    _report_module.Report.execute_script_report = _patched_execute_script_report
