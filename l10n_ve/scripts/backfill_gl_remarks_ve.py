"""
Backfill de la descripción (``remarks``) venezolana en asientos del Mayor ya
existentes, para todos los tipos soportados (los de ``DOC_FIELDS``: Sales
Invoice, Purchase Invoice, Payment Entry y las notas fiscales VE).

El hook regional ``l10n_ve.overrides.gl_remarks.update_gl_dict_with_regional_fields``
solo afecta asientos NUEVOS. Este script reescribe los históricos usando exactamente
los mismos ``builders`` (única fuente de verdad), leyendo del documento solo los
campos necesarios (sin instanciar el doc completo) y actualizando ``GL Entry.remarks``
con ``frappe.db.set_value`` (no dispara hooks; no toca ledger ni outstanding).

Idempotente: re-ejecutar produce el mismo texto y no vuelve a escribir. Nunca
sobreescribe:
  - líneas de stock / reversas / dimensión (``PROTECTED_REMARK_PREFIXES``),
  - documentos con nota manual (el builder devuelve ``None`` y se saltan),
  - asientos anulados (``is_cancelled = 1``).

Uso:
    # simula (no escribe) — por defecto
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_gl_remarks_ve.execute

    # ejecuta
    bench --site [sitio] execute \
        l10n_ve.scripts.backfill_gl_remarks_ve.execute \
        --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe

from l10n_ve.overrides.gl_remarks import (
    DOC_FIELDS,
    PROTECTED_REMARK_PREFIXES,
    build_remarks_for,
)

_COMMIT_EVERY: int = 500


def _is_protected(remark: str) -> bool:
    return any(remark.startswith(prefix) for prefix in PROTECTED_REMARK_PREFIXES)


def execute(dry_run: bool = True) -> dict:
    """Reescribe remarks históricos. Por defecto simula (``dry_run=True``)."""
    grand_vouchers = 0
    grand_lines = 0

    for doctype, fields in DOC_FIELDS.items():
        names = frappe.get_all(doctype, filters={"docstatus": 1}, pluck="name")
        vouchers = 0
        lines = 0

        for index, name in enumerate(names, start=1):
            row = frappe.db.get_value(doctype, name, fields, as_dict=True)
            if not row:
                continue

            new_remark = build_remarks_for(doctype, row)
            if not new_remark:
                # Sin soporte o con nota manual → se respeta lo existente.
                continue

            gl_entries = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": doctype, "voucher_no": name, "is_cancelled": 0},
                fields=["name", "remarks"],
            )

            targets = [
                gle.name
                for gle in gl_entries
                if not _is_protected(gle.remarks or "") and (gle.remarks or "") != new_remark
            ]

            if targets:
                vouchers += 1
                lines += len(targets)
                if not dry_run:
                    for gle_name in targets:
                        frappe.db.set_value(
                            "GL Entry", gle_name, "remarks", new_remark, update_modified=False
                        )

            if not dry_run and index % _COMMIT_EVERY == 0:
                frappe.db.commit()

        if not dry_run:
            frappe.db.commit()

        grand_vouchers += vouchers
        grand_lines += lines
        print(f"  {doctype}: {lines} líneas en {vouchers} documentos")

    modo = "DRY-RUN (sin escribir)" if dry_run else "APLICADO"
    print(f"{modo}: {grand_lines} líneas en {grand_vouchers} documentos")
    return {"vouchers": grand_vouchers, "lines": grand_lines, "dry_run": dry_run}
