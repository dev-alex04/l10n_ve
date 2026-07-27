# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Reporte HQ de facturas de venta (consolidado para casa matriz).

Wrapper del Libro de Ventas (``sales_book``): reusa su cálculo fiscal íntegro
(base imponible, IVA por alícuota, notas de crédito, serie) y solo cambia el
ACCESO (rol dedicado ``VE Sales Book HQ``), sin tocar el libro que contabilidad
usa para declarar. La única fuente de verdad fiscal sigue siendo ``sales_book``:
aquí NO se reimplementa ningún cálculo.

NOTA — ``prepared_report`` va en 0 a propósito: l10n_ve **suprime** el sistema
de Prepared Report en toda la app (``hooks.py`` override de
``frappe.desk.query_report.run`` -> ``patches/frappe/report_session_patch.py``
fuerza ``ignore_prepared_report=True``; además el cron
``tasks.reset_all_prepared_reports`` limpia el flag cada 15 min). Activarlo aquí
sería inerte. Medido: ~2s para 10.712 filas en modo interactivo, así que no hace
falta. Si algún día se requiere asincronía, el patrón de la casa es un doctype +
background job que adjunta el archivo (ver ``VE Fiscal Document Download``).

Fase 1 (esta): passthrough puro — misma salida que el Libro de Ventas.
Fase 2 (diferida): agregar columnas (serie-número, municipio/sucursal) y el
rollup padre-hijo, SIEMPRE como post-proceso en este módulo, nunca tocando
``sales_book.py``. El total autoritativo se toma del ``report_summary`` del
Libro (que excluye las filas de ajuste); por eso NO se usa ``add_total_row``.
"""

from l10n_ve.l10n_ve.report.sales_book.sales_book import execute as _sales_book_execute


def execute(filters=None):
    # Reusa el cálculo fiscal del Libro de Ventas tal cual:
    # (columns, data, message, chart, report_summary).
    return _sales_book_execute(filters)
