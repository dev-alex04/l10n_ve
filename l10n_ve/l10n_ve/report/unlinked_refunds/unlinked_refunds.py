# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""Clientes cuyos cobros ofrecen un anticipo que ya se devolvió.

Una fila por cliente descuadrado, con lo que se puede corregir de un botón y lo que hay que
revisar a mano. El diagnóstico vive en `l10n_ve.overrides.advance_refund_audit`.
"""

import frappe
from frappe import _

from l10n_ve.overrides.advance_refund_audit import FIX_ROLES, scan


def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
    filters = frappe._dict(filters or {})
    cases: list[dict] = scan(
        company=filters.get("company"), party=filters.get("customer")
    )
    # Quién mira no es siempre quién corrige: desde que el reporte se abrió a los roles de
    # finanzas, hay gente que lo consulta sin estar en FIX_ROLES. A esa no se le ofrece el
    # botón, que le daría un error de permiso al apretarlo.
    may_fix: bool = bool(set(frappe.get_roles()) & set(FIX_ROLES))
    return _columns(), [_row(case, may_fix) for case in cases]


def _columns() -> list[dict]:
    return [
        {
            "fieldname": "party",
            "label": _("Cliente"),
            "fieldtype": "Link",
            "options": "Customer",
            "width": 260,
        },
        {
            "fieldname": "offered",
            "label": _("Ofrecen los cobros"),
            "fieldtype": "Currency",
            "width": 150,
        },
        {
            "fieldname": "ledger",
            "label": _("Dice el mayor"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "difference",
            "label": _("Diferencia"),
            "fieldtype": "Currency",
            "width": 140,
        },
        {
            "fieldname": "situation",
            "label": _("Situación"),
            "fieldtype": "Data",
            "width": 190,
        },
        {
            "fieldname": "refunds",
            "label": _("Reembolso"),
            "fieldtype": "Data",
            "width": 230,
        },
        {
            "fieldname": "action",
            "label": _("Acción"),
            "fieldtype": "Data",
            "width": 220,
        },
    ]


def _row(case: dict, may_fix: bool) -> dict:
    if case["problem"]:
        situation = _("Revisar a mano")
    elif case["undo"]:
        situation = _("Deuda escondida")
    else:
        situation = _("Crédito fantasma")

    return {
        "party": case["party"],
        "party_name": case["party_name"],
        "offered": case["offered"],
        "ledger": case["ledger"],
        "difference": case["difference"],
        "situation": situation,
        "refunds": ", ".join(r["name"] for r in case["refunds"])
        or _("sin identificar"),
        "action": "",
        # Lo que necesita el botón, y no se muestra como columna.
        "company": case["company"],
        "advance_account": case["advance_account"],
        "can_fix": 0 if case["problem"] else 1,
        "may_fix": 1 if may_fix else 0,
        "problem": case["problem"] or "",
    }
