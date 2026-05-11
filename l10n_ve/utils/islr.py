"""Utilidades para el cálculo de retención ISLR (Venezuela).

Fuente única de verdad para resolver la alícuota del tabulador ISLR
y calcular el monto de retención. Consumido por:
- l10n_ve/controllers/taxes_mixin.py  (inyección de fila ISLR en factura)
- domina_isp/.../isp_payment_entry.py (cálculo de ISLR en ISP Payment Entry)
- domina_isp/.../index.py             (portal: tasa ISLR para display)
"""
import frappe
from frappe.utils import flt


def get_islr_aliquot(
    customer: str, company: str
) -> tuple | None:
    """Resuelve el tabulador ISLR y la alícuota aplicable.

    Busca el tabulador asignado al cliente y filtra la alícuota
    según el type_of_person de la compañía.

    Args:
        customer: Nombre del Customer.
        company: Nombre de la Company.

    Returns:
        (aliquot_row, tabulator_doc) o None si no aplica ISLR.
    """
    tabulator_name: str | None = frappe.get_cached_value(
        "Customer", customer, "tabulator_islr"
    )
    if not tabulator_name:
        return None

    tabulator = frappe.get_cached_doc("Tabulator ISLR", tabulator_name)
    if not tabulator.aliquot:
        return None

    type_of_person: str | None = frappe.get_cached_value(
        "Company", company, "type_of_person"
    )
    if not type_of_person:
        return None

    aliquot_info = next(
        (aq for aq in tabulator.aliquot
         if aq.types_of_person == type_of_person and aq.aliquot > 0),
        None
    )
    if not aliquot_info:
        return None

    return aliquot_info, tabulator


def calculate_islr_amount(total: float, aliquot_info) -> float:
    """Calcula el monto ISLR basándose en la alícuota del tabulador.

    Fórmula fiscal venezolana:
        base = total × (percentage_base / 100)
        islr = (base × aliquot / 100) − sustraendo

    Args:
        total: Monto base de la factura (net_total en moneda de referencia).
        aliquot_info: Fila de Tabulator ISLR Aliquots con percentage_base,
                      aliquot y subtracting.

    Returns:
        Monto ISLR redondeado a 2 decimales, mínimo 0.
    """
    tax_base: float = flt(total) * flt(aliquot_info.percentage_base) / 100
    islr: float = (tax_base * flt(aliquot_info.aliquot) / 100) - flt(aliquot_info.subtracting)
    return flt(max(islr, 0), 2)
