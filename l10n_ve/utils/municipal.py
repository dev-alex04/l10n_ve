"""Utilidades para el cálculo de retención municipal ISAE (Venezuela).

Fuente única de verdad para resolver la alícuota desde VE Municipality Taxes
y calcular el monto de retención. Consumido por:
- domina_isp/.../isp_payment_entry.py  (cálculo en ISP Payment Entry)
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


def get_municipal_withholding_rate(
    customer: str, company: str  # noqa: ARG001
) -> float:
    """Retorna el porcentaje de retención municipal del cliente (ISAE).

    Lee directamente `custom_municipal_withholding_rate` del Customer.
    Si el campo no está seteado, intenta resolver la alícuota desde
    `custom_municipality_tax` → `VE Municipality Taxes.aliquot`.

    Args:
        customer: Nombre del Customer.
        company:  Nombre de la Company (reservado para compatibilidad futura).

    Returns:
        Alícuota como float (ej: 1.5 para 1.5 %). 0.0 si no aplica.
    """
    cust_rate: float | None
    cust_rate, municipality_tax = frappe.get_cached_value(
        "Customer",
        customer,
        ["municipal_withholding_rate", "municipality_tax"],
    ) or (None, None)

    rate = flt(cust_rate)
    if rate > 0:
        return rate

    # Fallback: leer desde el registro VE Municipality Taxes asignado
    if municipality_tax:
        rate = flt(frappe.get_cached_value("VE Municipality Taxes", municipality_tax, "aliquot"))

    return rate if rate > 0 else 0.0


def calculate_municipal_amount(
    net_total: float,
    rate: float,
    conversion_rate: float = 1.0,  # noqa: ARG001
) -> float:
    """Calcula el monto de retención municipal en moneda de referencia (USD).

    Fórmula simple: monto = net_total × (rate / 100)
    net_total debe venir ya en moneda de referencia (USD).

    Args:
        net_total:       Base imponible en USD.
        rate:            Porcentaje de retención (ej: 1.5).
        conversion_rate: Reservado para consistencia con islr.py.

    Returns:
        Monto de retención redondeado a 2 decimales, mínimo 0.
    """
    amount: float = flt(net_total) * flt(rate) / 100
    return flt(max(amount, 0), 2)
