# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Helpers y builders de mocks reutilizables para tests de impuestos VE.

Provee funciones factory para construir documentos, items, taxes y
alícuotas ISLR sin depender de la base de datos.
"""

import frappe
from frappe.utils import flt
from unittest.mock import MagicMock


def make_mock_item(
    net_amount: float = 100.0,
    base_net_amount: float | None = None,
    amount: float | None = None,
    vat_exempt: bool = False,
    idx: int = 1,
    qty: float = 1.0,
    item_code: str = "TEST-ITEM",
    item_name: str = "Test Item",
    **kw,
) -> frappe._dict:
    """Construye un item mock con los campos mínimos requeridos."""
    item = frappe._dict({
        "net_amount": net_amount,
        "base_net_amount": base_net_amount if base_net_amount is not None else net_amount,
        "amount": amount if amount is not None else net_amount,
        "vat_exempt": vat_exempt,
        "idx": idx,
        "qty": qty,
        "item_code": item_code,
        "item_name": item_name,
        **kw,
    })
    item.meta = MagicMock()
    item.meta.get_field = MagicMock(return_value=None)
    return item


def make_mock_tax(
    charge_type: str = "VAT",
    rate: float = 16.0,
    tax_amount: float = 0.0,
    base_tax_amount: float = 0.0,
    is_tax_withholding_account: bool = False,
    add_deduct_tax: str = "Add",
    row_id: int | None = None,
    percentage_base: float = 0.0,
    subtracting: float = 0.0,
    category: str = "Total",
    **kw,
) -> frappe._dict:
    """Construye una fila de tax mock con precision() simulado."""
    tax = frappe._dict({
        "charge_type": charge_type,
        "rate": rate,
        "tax_amount": tax_amount,
        "base_tax_amount": base_tax_amount,
        "tax_amount_for_current_item": 0.0,
        "grand_total_for_current_item": 0.0,
        "tax_amount_after_discount_amount": tax_amount,
        "base_tax_amount_after_discount_amount": base_tax_amount,
        "is_tax_withholding_account": is_tax_withholding_account,
        "add_deduct_tax": add_deduct_tax,
        "total": 0.0,
        "base_total": 0.0,
        "category": category,
        "item_wise_tax_detail": {},
        "row_id": row_id,
        "percentage_base": percentage_base,
        "subtracting": subtracting,
        "dont_recompute_tax": 0,
        **kw,
    })
    tax.precision = lambda field: 2
    return tax


class MockDoc:
    """Mock de frappe.Document sin conflicto con dict.items().

    frappe._dict hereda de dict, y dict.items() sobrescribe cualquier
    atributo 'items' asignado al diccionario. Este mock usa atributos
    simples para evitar ese conflicto.
    """

    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getattr__(self, key: str):
        """Retorna None para atributos inexistentes (simula frappe._dict)."""
        return None

    def get(self, key: str, default=None):
        """Simula frappe.Document.get()."""
        return getattr(self, key, default)

    def precision(self, field: str) -> int:
        """Simula frappe.Document.precision()."""
        return 2


def make_mock_doc(
    doctype: str = "Sales Invoice",
    currency: str = "USD",
    conversion_rate: float = 36.5,
    net_total: float = 1000.0,
    base_net_total: float | None = None,
    total: float | None = None,
    base_total: float | None = None,
    items: list | None = None,
    taxes: list | None = None,
    **kw,
) -> MockDoc:
    """Construye un doc mock completo para TaxesAndTotals."""
    base_net: float = base_net_total if base_net_total is not None else net_total * conversion_rate
    base_t: float = base_total if base_total is not None else (total or net_total) * conversion_rate

    meta = MagicMock()
    meta.get_field = MagicMock(return_value=True)

    return MockDoc(
        doctype=doctype,
        company="Test Company",
        currency=currency,
        conversion_rate=conversion_rate,
        net_total=net_total,
        base_net_total=base_net,
        total=total if total is not None else net_total,
        base_total=base_t,
        grand_total=0.0,
        base_grand_total=0.0,
        base_total_taxes_and_charges=0.0,
        base_rounded_total=0.0,
        base_rounding_adjustment=0.0,
        total_exempt=0.0,
        items=items or [],
        taxes=taxes or [],
        is_consolidated=True,
        tax_withholding_net_total=0.0,
        docstatus=0,
        meta=meta,
        **kw,
    )


def make_mock_aliquot(
    percentage_base: float = 100.0,
    aliquot: float = 5.0,
    subtracting: float = 0.0,
    types_of_person: str = "PNR",
) -> frappe._dict:
    """Construye una alícuota ISLR mock para calculate_islr_amount."""
    return frappe._dict({
        "percentage_base": percentage_base,
        "aliquot": aliquot,
        "subtracting": subtracting,
        "types_of_person": types_of_person,
    })


def make_taxes_and_totals(doc: frappe._dict):
    """Crea instancia de TaxesAndTotals sin ejecutar __init__ de ERPNext.

    Usa __new__ para evitar side effects del constructor padre.
    """
    from l10n_ve.controllers.taxes_and_totals import TaxesAndTotals

    calc = TaxesAndTotals.__new__(TaxesAndTotals)
    calc.doc = doc
    return calc
