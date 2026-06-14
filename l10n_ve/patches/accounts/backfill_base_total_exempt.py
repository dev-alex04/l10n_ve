"""
Parche de migración: Poblar base_total_exempt (VEF) en documentos históricos.

Negocio: base_total_exempt es la fuente de verdad en bolívares del monto
exento. Se calcula como la suma de base_net_amount de las líneas exentas
(misma base y redondeo per-ítem que base_net_total), evitando el drift de
céntimos que producía recalcular total_exempt * conversion_rate en el Libro
de Ventas y el payload HKA.

Orden de migración: los Custom Fields de Sales/Purchase Invoice se sincronizan
en sync_fixtures, que corre DESPUÉS de los patches post_model_sync. Por eso se
crean aquí explícitamente (idempotente) para garantizar que la columna exista
antes del backfill, incluso en el primer migrate de un sitio nuevo. Las VE
NC/ND son campos de doctype, ya creados por sync_all antes de este patch.

La fórmula vive en l10n_ve.scripts.backfill_base_total_exempt (única fuente de
verdad). Idempotente: solo escribe donde total_exempt > 0 y base_total_exempt
sigue en 0; escribe un solo campo, sin disparar hooks (no toca GL ni ledger).
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from l10n_ve.scripts.backfill_base_total_exempt import execute as _backfill

# Def mínima para garantizar la columna; la posición (insert_after) y los flags
# de presentación los aplica luego sync_fixtures desde custom_field.json (la
# fuente autoritativa). Sin insert_after se evita depender de que total_exempt
# —también custom field, sincronizado después— ya exista en un sitio nuevo.
_BASE_TOTAL_EXEMPT_FIELD: dict = {
    "fieldname": "base_total_exempt",
    "label": "Total Exento (Base)",
    "fieldtype": "Currency",
    "options": "Company:company:default_currency",
    "read_only": 1,
}


def execute() -> None:
    create_custom_fields(
        {
            "Sales Invoice": [_BASE_TOTAL_EXEMPT_FIELD],
            "Purchase Invoice": [_BASE_TOTAL_EXEMPT_FIELD],
        },
        ignore_validate=True,
    )
    _backfill(dry_run=False)
