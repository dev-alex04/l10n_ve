"""Corrige referencias huérfanas a cuentas contables post-migración plan 2026.

La migración replace_chart_of_accounts usó frappe.delete_doc(force=True) en la
Fase 4, lo cual eliminó cuentas sin verificar si estaban referenciadas en
Company defaults, Tax Templates, Bank Accounts, etc. Este patch repara las
15 referencias rotas detectadas en Galanet Solution C.A.
"""
import frappe


COMPANY: str = "Galanet Solution C.A."

# Correcciones con remapeo a cuenta destino válida
CORRECTIONS: list[dict] = [
    # ── Company defaults (core) ──
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "default_payable_account",
        "old": "21012 - Cuentas por Pagar Proveedores - Galanet",
        "new": "2103001 - Cuentas Por Pagar Proveedores - Galanet",
    },
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "disposal_account",
        "old": "71015 - Otros Ingresos Extraordinarios - Galanet",
        "new": "7101006 - Otros Ingresos Extraordinarios - Galanet",
    },
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "default_advance_paid_account",
        "old": "11051 - Anticipo Proveedores - Galanet",
        "new": "1107001 - Anticipo Proveedores - Galanet",
    },

    # ── Company defaults (l10n_ve custom fields) ──
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "purchase_vat_account",
        "old": "11074 - Iva Crédito Fiscal - Galanet",
        "new": "1110004 - Iva Credito Fiscal - Galanet",
    },
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "purchase_vat_withholding_account",
        "old": "21032 - Retenciones de IVA Proveedores - Galanet",
        "new": "2105002 - Retenciones de IVA Proveedores - Galanet",
    },

    # ── Purchase Taxes and Charges Templates (IVA Crédito Fiscal) ──
    {
        "doctype": "Purchase Taxes and Charges",
        "filters": {
            "parenttype": "Purchase Taxes and Charges Template",
            "account_head": "11074 - Iva Crédito Fiscal - Galanet",
        },
        "field": "account_head",
        "old": "11074 - Iva Crédito Fiscal - Galanet",
        "new": "1110004 - Iva Credito Fiscal - Galanet",
    },

    # ── Tax Withholding Account (Retenciones IVA) ──
    {
        "doctype": "Tax Withholding Account",
        "filters": {
            "account": "21032 - Retenciones de IVA Proveedores - Galanet",
        },
        "field": "account",
        "old": "21032 - Retenciones de IVA Proveedores - Galanet",
        "new": "2105002 - Retenciones de IVA Proveedores - Galanet",
    },

    # ── Bank Account: Banco de Venezuela ──
    {
        "doctype": "Bank Account",
        "filters": {
            "account": "11022 - Banco de Venezuela Cte. 1347 - Galanet",
        },
        "field": "account",
        "old": "11022 - Banco de Venezuela Cte. 1347 - Galanet",
        "new": "1102001 - Banco de Venezuela Bs. Cte. 1347 DC-01 - Galanet",
    },

    # ── Bank Account: Bancamiga Joynet ──
    {
        "doctype": "Bank Account",
        "filters": {
            "account": "01720110781100812393 - BANCAMIGA JOYNET 2393 - Galanet",
        },
        "field": "account",
        "old": "01720110781100812393 - BANCAMIGA JOYNET 2393 - Galanet",
        "new": "1102023 - Bancamiga Bs Cte 2393 MIR-04 - Galanet",
    },

    # ── Mode of Payment Account: Bancamiga Joynet ──
    {
        "doctype": "Mode of Payment Account",
        "filters": {
            "default_account": "01720110781100812393 - BANCAMIGA JOYNET 2393 - Galanet",
        },
        "field": "default_account",
        "old": "01720110781100812393 - BANCAMIGA JOYNET 2393 - Galanet",
        "new": "1102023 - Bancamiga Bs Cte 2393 MIR-04 - Galanet",
    },
]

# Campos huérfanos sin equivalente en plan 2026 → se limpian
FIELDS_TO_CLEAR: list[dict] = [
    {
        "doctype": "Company",
        "filters": {"name": COMPANY},
        "field": "default_discount_account",
        "old": "41015 - Descuentos en Ventas - Galanet",
    },
]


def execute() -> None:
    if not frappe.db.exists("Company", COMPANY):
        print(f"⏭ Compañía '{COMPANY}' no existe, omitiendo patch")
        return

    fixed: int = 0
    skipped: int = 0
    errors: int = 0

    print(f"── Corrigiendo referencias huérfanas en {COMPANY} ──")

    # Fase 1: Correcciones con remapeo
    for correction in CORRECTIONS:
        target_account: str = correction["new"]

        if not frappe.db.exists("Account", target_account):
            print(f"  ✗ Cuenta destino no existe: {target_account}")
            errors += 1
            continue

        current_value: str | None = frappe.db.get_value(
            correction["doctype"],
            correction["filters"],
            correction["field"]
        )

        if current_value != correction["old"]:
            skipped += 1
            continue

        try:
            frappe.db.set_value(
                correction["doctype"],
                correction["filters"],
                correction["field"],
                target_account,
                update_modified=False
            )
            fixed += 1
            print(
                f"  ✓ {correction['doctype']}.{correction['field']}: "
                f"{correction['old'][:40]}... → {target_account[:40]}..."
            )
        except Exception as e:
            errors += 1
            print(f"  ✗ {correction['doctype']}.{correction['field']}: {e}")

    # Fase 2: Limpieza de campos sin equivalente
    for clear_entry in FIELDS_TO_CLEAR:
        current_value = frappe.db.get_value(
            clear_entry["doctype"],
            clear_entry["filters"],
            clear_entry["field"]
        )

        if current_value != clear_entry["old"]:
            skipped += 1
            continue

        try:
            frappe.db.set_value(
                clear_entry["doctype"],
                clear_entry["filters"],
                clear_entry["field"],
                "",
                update_modified=False
            )
            fixed += 1
            print(
                f"  ✓ {clear_entry['doctype']}.{clear_entry['field']}: "
                f"{clear_entry['old'][:40]}... → (limpiado, sin equivalente)"
            )
        except Exception as e:
            errors += 1
            print(f"  ✗ {clear_entry['doctype']}.{clear_entry['field']}: {e}")

    if fixed > 0:
        frappe.db.commit()

    print(f"── Resultado: {fixed} corregidas, {skipped} sin cambio, {errors} errores ──")
