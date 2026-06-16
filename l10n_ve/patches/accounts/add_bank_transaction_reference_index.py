"""
Patch: índice en Bank Transaction.reference_number para la validación anti-duplicado.

validate_bank_transaction_duplicate consulta por (reference_number, bank_account,
company) en cada inserción del import de extractos. Sin índice es un full scan por
fila importada (cientos por extracto). reference_number es el campo selectivo.

reference_number es Small Text (columna TEXT), así que no admite el add_index normal
de Frappe; se usa un índice de PREFIJO por SQL directo. Los números de referencia
bancaria son cortos (~12 dígitos), un prefijo de 50 los cubre por completo.

Idempotente: solo crea el índice si no existe.
"""
import frappe

_INDEX_NAME = "bank_txn_reference_number"


def execute() -> None:
    # PostgreSQL: índice normal con IF NOT EXISTS (no admite prefijo de longitud;
    # reference_number es corto, se indexa completo).
    if frappe.db.db_type == "postgres":
        frappe.db.sql(
            f'CREATE INDEX IF NOT EXISTS "{_INDEX_NAME}" ON "tabBank Transaction" (reference_number)'
        )
        return

    # MariaDB/MySQL: índice de prefijo (reference_number es TEXT), idempotente.
    existing = {
        r["Key_name"]
        for r in frappe.db.sql("SHOW INDEX FROM `tabBank Transaction`", as_dict=True)
    }
    if _INDEX_NAME in existing:
        return
    frappe.db.sql(
        f"ALTER TABLE `tabBank Transaction` ADD INDEX `{_INDEX_NAME}` (reference_number(50))"
    )
