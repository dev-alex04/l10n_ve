"""
Backfill de ``base_total_with_vat`` ("Total Base + IVA (Bs)") en documentos fiscales
históricos, de ventas y de compras.

El campo lo calcula ``TaxesMixin._set_base_total_with_vat`` al validar, así que solo
afecta a documentos NUEVOS. Este script cubre los ya emitidos, con la misma regla:
toma el ``base_total`` de la primera fila de impuestos con ``charge_type='VAT'`` (que
es la base imponible + IVA, ANTES de las filas de retención) y, si el documento no
tiene fila VAT, cae a ``base_net_total``.

Por qué hace falta (dos huecos distintos):

1. Compras: ``base_total_with_vat`` no existía en Purchase Invoice — se agregó junto
   con este script. Ningún documento de compra tiene el valor.
2. Ventas: el patch ``l10n_ve.patches.accounts.populate_base_total_with_vat`` quedó
   registrado como ejecutado pero no llegó a poblar nada, porque en ``bench migrate``
   los patches corren ANTES de sincronizar los fixtures (frappe/migrate.py:
   ``run_schema_updates`` → patches, y recién después ``post_schema_updates`` →
   ``sync_fixtures``). Como el Custom Field aún no existía, su guarda
   ``has_column(...)`` lo hizo salir sin trabajo, y un patch solo corre una vez.

OJO con el nombre de la tabla hija: ventas usa ``Sales Taxes and Charges`` y compras
``Purchase Taxes and Charges``. Aplicar el SQL de ventas a un documento de compra no
falla: el JOIN simplemente no machea y el fallback dejaría ``base_net_total``, es
decir el monto SIN IVA. Por eso cada doctype declara su tabla.

Alcance: borradores y emitidos (``docstatus < 2``); los anulados se dejan como están.
Los borradores igual se recalculan al guardar, pero así el campo se ve correcto de una.

Idempotente: solo toca documentos cuyo valor esté en 0, así que re-ejecutar no reescribe
nada.

Uso:
    # simula (no escribe) — por defecto
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_base_total_with_vat.execute

    # ejecuta
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_base_total_with_vat.execute \
        --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe

# {doctype: tabla hija de impuestos}
DOCTYPES: dict[str, str] = {
    "Sales Invoice": "Sales Taxes and Charges",
    "VE Sales Credit Note": "Sales Taxes and Charges",
    "VE Sales Debit Note": "Sales Taxes and Charges",
    "Purchase Invoice": "Purchase Taxes and Charges",
    "VE Purchase Credit Note": "Purchase Taxes and Charges",
    "VE Purchase Debit Note": "Purchase Taxes and Charges",
}


def execute(dry_run: bool = True) -> None:
    modo = "SIMULACIÓN (no escribe)" if dry_run else "EJECUCIÓN"
    print(f"\n=== Backfill base_total_with_vat — {modo} ===")

    total = 0
    for doctype, taxes_table in DOCTYPES.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.db.has_column(doctype, "base_total_with_vat"):
            print(f"  {doctype:26} sin el campo (¿falta migrar los fixtures?), se omite")
            continue

        # Se excluyen los documentos sin base imponible (borradores vacíos): su valor
        # correcto ES 0, así que contarlos como pendientes haría que el saneo nunca
        # converja a "al día" y reporte trabajo inexistente en cada corrida.
        pendientes = frappe.db.count(
            doctype,
            {"docstatus": ["<", 2], "base_total_with_vat": 0, "base_net_total": ["!=", 0]},
        )
        if not pendientes:
            print(f"  {doctype:26} al día")
            continue

        print(f"  {doctype:26} {pendientes} documento(s) por poblar")
        total += pendientes
        if not dry_run:
            _populate(doctype, taxes_table)

    if dry_run:
        print(f"\nTotal a poblar: {total}. Re-ejecuta con --kwargs \"{{'dry_run': False}}\" para aplicar.")
    else:
        frappe.db.commit()
        print(f"\nListo: {total} documento(s) poblados.")


def _populate(doctype: str, taxes_table: str) -> None:
    """Puebla el campo con el base_total de la fila VAT; sin fila VAT, base_net_total."""
    frappe.db.sql(
        f"""
        UPDATE `tab{doctype}` doc
        INNER JOIN `tab{taxes_table}` tax
            ON tax.parent = doc.name
            AND tax.parenttype = %(doctype)s
            AND tax.charge_type = 'VAT'
            AND tax.idx = (
                SELECT MIN(t2.idx)
                FROM `tab{taxes_table}` t2
                WHERE t2.parent = doc.name
                    AND t2.parenttype = %(doctype)s
                    AND t2.charge_type = 'VAT'
            )
        SET doc.base_total_with_vat = tax.base_total
        WHERE doc.docstatus < 2
            AND IFNULL(doc.base_total_with_vat, 0) = 0
        """,
        {"doctype": doctype},
    )

    # Sin fila VAT (documento exento): base + IVA == base.
    frappe.db.sql(
        f"""
        UPDATE `tab{doctype}`
        SET base_total_with_vat = base_net_total
        WHERE docstatus < 2
            AND IFNULL(base_total_with_vat, 0) = 0
            AND IFNULL(base_net_total, 0) != 0
        """
    )
