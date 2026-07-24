# Copyright (c) 2026, DominaERP and contributors
# For license information, please see license.txt

"""Reporte HQ de facturas de venta a escala.

Wrapper del Libro de Ventas (``sales_book``): reusa su cálculo fiscal íntegro
(base imponible, IVA por alícuota, notas de crédito, serie) y solo cambia la
ENTREGA (Prepared Report / generación en segundo plano para 14k–30k facturas)
y el ACCESO (rol dedicado). La única fuente de verdad fiscal sigue siendo
``sales_book``: aquí NO se reimplementa ningún cálculo.

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
