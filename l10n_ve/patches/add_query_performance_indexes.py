"""
Patch: índices compuestos de rendimiento para consultas frecuentes.

Los índices de columna única se declaran con "search_index": 1 en el JSON del
DocType y Frappe los crea al migrar. Los índices COMPUESTOS no se expresan en el
JSON, así que se crean aquí.

- VE Digital Invoice Log: tabla de logs sin índices que crece sin límite.
    * (sales_invoice, document_type, status): JOIN de deduplicación y los LEFT JOIN
      de los módulos de integración (tasks.py, *_integration.py).
    * (status, creation): casi toda query de limpieza filtra status='Error' y opera
      sobre creation (rango / MAX / orden).
- VE Deposit: transaccional de alto volumen (import de extractos). (company,
  posting_date) cubre el filtro por empresa + orden por fecha del list view.
- VE Conatel Tax Declaration: (company, status) para listados de declaraciones.
- VE Disclosure Note: (company, fiscal_year) para navegación por período.

Idempotente: cada índice se crea solo si no existe.
"""
import frappe

# (doctype, index_name, [columns])
_INDEXES = [
    ("VE Digital Invoice Log", "vdil_invoice_doc_status", ["sales_invoice", "document_type", "status"]),
    ("VE Digital Invoice Log", "vdil_status_creation", ["status", "creation"]),
    ("VE Deposit", "vdep_company_posting_date", ["company", "posting_date"]),
    ("VE Conatel Tax Declaration", "vconatel_company_status", ["company", "status"]),
    ("VE Disclosure Note", "vdisc_company_fiscal_year", ["company", "fiscal_year"]),
    ("Sales Invoice", "si_company_posting_date_docstatus", ["company", "posting_date", "docstatus"]),
]


def execute() -> None:
    for doctype, index_name, columns in _INDEXES:
        table = f"tab{doctype}"

        # PostgreSQL: CREATE INDEX IF NOT EXISTS es idempotente de fábrica.
        if frappe.db.db_type == "postgres":
            cols = ", ".join(f'"{c}"' for c in columns)
            frappe.db.sql(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table}" ({cols})')
            continue

        # MariaDB/MySQL: no hay ADD INDEX IF NOT EXISTS portable, se verifica antes.
        existing = {
            r["Key_name"]
            for r in frappe.db.sql(f"SHOW INDEX FROM `{table}`", as_dict=True)
        }
        if index_name in existing:
            continue

        cols = ", ".join(f"`{c}`" for c in columns)
        frappe.db.sql(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({cols})")
