"""Utilidades para el cálculo de retención municipal ISAE (Venezuela).

Fuente única de verdad para resolver la alícuota desde VE Municipality Taxes
y calcular el monto de retención. Consumido por l10n_ve (taxes_mixin, taxes_and_totals)
y aplicaciones del ecosistema como domina_isp (isp_payment_entry).
"""
from __future__ import annotations

import frappe
from frappe.utils import flt


def get_municipal_withholding_rate(
    customer: str, company: str = None  # noqa: ARG001
) -> float:
    """Retorna el porcentaje de retención municipal del cliente (ISAE).

    Lee directamente `municipal_withholding_rate` del Customer si es contribuyente especial.
    Si el campo no está seteado (> 0), intenta resolver la alícuota desde
    `municipality_tax` → `VE Municipality Taxes.aliquot`.

    Args:
        customer: Nombre del Customer.
        company:  Nombre de la Company (reservado para compatibilidad futura).

    Returns:
        Alícuota como float (ej: 1.5 para 1.5 %). 0.0 si no aplica o no es contribuyente especial.
    """
    is_special: int | None
    cust_rate: float | None
    municipality_tax: str | None
    is_special, cust_rate, municipality_tax = frappe.get_cached_value(
        "Customer",
        customer,
        ["is_special_taxpayer", "municipal_withholding_rate", "municipality_tax"],
    ) or (0, None, None)

    if not is_special:
        return 0.0

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
