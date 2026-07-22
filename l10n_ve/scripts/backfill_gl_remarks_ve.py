"""
Backfill de la descripción (``remarks``) venezolana en asientos del Mayor ya
existentes, para todos los tipos soportados (los de ``DOC_FIELDS``: Sales
Invoice, Purchase Invoice, Payment Entry y las notas fiscales VE).

El hook regional ``l10n_ve.overrides.gl_remarks.update_gl_dict_with_regional_fields``
solo afecta asientos NUEVOS. Este script reescribe los históricos usando exactamente
los mismos ``builders`` y el mismo ``apply_gl_remarks`` (UPDATE único por voucher)
que el hook de certificación — única fuente de verdad. Lee del documento solo los
campos necesarios (sin instanciar el doc completo) y no dispara hooks ni toca el
ledger/outstanding.

Idempotente: re-ejecutar produce el mismo texto y no vuelve a escribir. Nunca
sobreescribe:
  - líneas de stock / reversas / dimensión (prefijos protegidos),
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

from l10n_ve.overrides.gl_remarks import DOC_FIELDS, apply_gl_remarks, build_remarks_for

_COMMIT_EVERY: int = 500


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

            # El builder de PE detalla las facturas aplicadas; el doc vivo trae
            # doc.references, aquí se inyectan para igualar esa salida.
            if doctype == "Payment Entry":
                row["references"] = frappe.get_all(
                    "Payment Entry Reference",
                    filters={"parent": name},
                    fields=["reference_name"],
                )

            new_remark = build_remarks_for(doctype, row)
            if not new_remark:
                # Sin soporte o con nota manual → se respeta lo existente.
                continue

            # apply_gl_remarks: mismo filtro/UPDATE que el hook de certificación
            # (protegidas/anuladas/idempotencia en un solo statement).
            affected = apply_gl_remarks(doctype, name, new_remark, dry_run=dry_run)
            if affected:
                vouchers += 1
                lines += affected

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
