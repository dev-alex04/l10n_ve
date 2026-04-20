"""
Auditoría de paridad montos HKA vs ERP.

Fase 1: Construye el payload actual y lo compara contra base_* de la factura.
Fase 2: Si Fase 1 OK, busca el log exitoso de HKA y compara el payload
         enviado históricamente contra el payload recién construido.
         Incluye resumen acumulado de diferencias en VEF y USD.

Uso:
    bench --site [sitio] execute \
        l10n_ve.scripts.audit_hka_payload_mismatch.run

Salida:
    Solo facturas con discrepancias de montos + resumen de impacto.
"""
import json
import sys

import frappe
from frappe.utils import flt

from l10n_ve.digital_invoice.payload_builder import TFHKAPayloadBuilder
from l10n_ve.digital_invoice.tfhka_integration import (
    _validate_invoice_integrity,
    _validate_payload_vs_invoice,
    get_active_billing_series,
)

_TOLERANCE: float = 0.02

_TOTALES_FIELDS: list[str] = [
    "montoGravadoTotal",
    "montoExentoTotal",
    "subtotal",
    "totalIVA",
    "montoTotalConIVA",
    "totalAPagar",
]


def _print_progress(
    current: int, total: int,
    mismatches_p1: int, mismatches_p2: int,
    skipped: int, phase: str,
) -> None:
    """Barra de progreso inline."""
    pct: float = (current / total) * 100 if total else 0
    bar_len: int = 30
    filled: int = int(bar_len * current // total) if total else 0
    bar: str = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(
        f"\r  {bar} {pct:5.1f}% ({current}/{total}) "
        f"| F1:❌{mismatches_p1} F2:❌{mismatches_p2} ⏭{skipped} [{phase}]"
    )
    sys.stdout.flush()


def _extract_totales(payload: dict, section: str = "totales") -> dict:
    """Extrae totales o totalesOtraMoneda del payload."""
    return (
        payload
        .get("documentoElectronico", {})
        .get("encabezado", {})
        .get(section, {})
    ) or {}


def _get_sent_payload(invoice_name: str) -> dict | None:
    """Busca el payload enviado exitosamente a HKA."""
    log_payload: str | None = frappe.db.get_value(
        "VE Digital Invoice Log",
        filters={
            "sales_invoice": invoice_name,
            "endpoint": "Emision",
            "status": "Success",
        },
        fieldname="payload_sent",
        order_by="creation DESC",
    )

    if not log_payload:
        return None

    try:
        return json.loads(log_payload)
    except (json.JSONDecodeError, AttributeError):
        return None


def _compare_section(
    sent: dict, current: dict, currency_label: str
) -> tuple[list[str], dict[str, float]]:
    """Compara campos de Totales entre payload enviado y actual.

    Retorna (errores, {campo: diferencia_absoluta}).
    """
    errors: list[str] = []
    diffs: dict[str, float] = {}

    for field in _TOTALES_FIELDS:
        sent_val: float = flt(sent.get(field, 0))
        curr_val: float = flt(current.get(field, 0))
        diff: float = sent_val - curr_val
        abs_diff: float = abs(diff)

        if abs_diff > _TOLERANCE:
            diffs[field] = diff
            errors.append(
                f"[{currency_label}] {field}: "
                f"enviado={sent_val:.2f}, actual={curr_val:.2f} "
                f"(Δ {diff:+.2f})"
            )

    return errors, diffs


def run() -> None:
    """Punto de entrada principal."""
    invoices: list[dict] = frappe.db.get_all(
        "Sales Invoice",
        filters={
            "docstatus": ["in", [1, 2]],
            "bill_no": ["is", "set"],
        },
        fields=["name", "branch", "company"],
        order_by="posting_date ASC",
    )

    total: int = len(invoices)
    mismatches_p1: int = 0
    mismatches_p2: int = 0
    skipped: int = 0
    no_log: int = 0

    # Acumuladores de diferencias
    total_diff_vef: dict[str, float] = {f: 0.0 for f in _TOTALES_FIELDS}
    total_diff_usd: dict[str, float] = {f: 0.0 for f in _TOTALES_FIELDS}
    # Rangos de magnitud (sobre totalAPagar)
    range_trivial: int = 0     # < 0.05
    range_minor: int = 0       # 0.05 - 1.00
    range_material: int = 0    # > 1.00

    print(f"\n{'=' * 70}")
    print(f"  Auditoría HKA — {total} facturas con bill_no")
    print(f"  Fase 1: payload actual vs factura")
    print(f"  Fase 2: payload enviado vs payload actual (VEF + USD)")
    print(f"{'=' * 70}\n")

    for i, inv in enumerate(invoices, 1):
        _print_progress(i, total, mismatches_p1, mismatches_p2, skipped, "F1")

        try:
            doc = frappe.get_doc("Sales Invoice", inv.name)

            # --- FASE 1 ---
            integrity_errors: list[str] = _validate_invoice_integrity(doc)

            branch: str = doc.get("branch") or ""
            try:
                series_doc, branch_code = get_active_billing_series(
                    company=doc.company, branch=branch
                )
            except Exception:
                series_doc = None
                branch_code = ""

            try:
                builder = TFHKAPayloadBuilder(
                    doc,
                    series_doc=series_doc,
                    branch_code=branch_code,
                )
                payload: dict = builder.build_payload()
            except Exception:
                skipped += 1
                continue

            payload_errors: list[str] = _validate_payload_vs_invoice(payload, doc)
            all_p1_errors: list[str] = integrity_errors + payload_errors

            if all_p1_errors:
                mismatches_p1 += 1
                sys.stdout.write("\r" + " " * 90 + "\r")
                print(f"❌ F1 [{i}/{total}] {inv.name}")
                for err in all_p1_errors:
                    print(f"   • {err}")
                print()
                continue

            # --- FASE 2 ---
            _print_progress(i, total, mismatches_p1, mismatches_p2, skipped, "F2")

            sent_payload: dict | None = _get_sent_payload(inv.name)
            if sent_payload is None:
                no_log += 1
                continue

            sent_vef: dict = _extract_totales(sent_payload, "totales")
            curr_vef: dict = _extract_totales(payload, "totales")
            vef_errors, vef_diffs = _compare_section(sent_vef, curr_vef, "VEF")

            sent_usd: dict = _extract_totales(sent_payload, "totalesOtraMoneda")
            curr_usd: dict = _extract_totales(payload, "totalesOtraMoneda")
            usd_errors, usd_diffs = _compare_section(sent_usd, curr_usd, "USD")

            all_p2_errors: list[str] = vef_errors + usd_errors

            if all_p2_errors:
                mismatches_p2 += 1

                for field, diff in vef_diffs.items():
                    total_diff_vef[field] += diff
                for field, diff in usd_diffs.items():
                    total_diff_usd[field] += diff

                # Clasificar magnitud por totalAPagar VEF
                abs_pagar = abs(vef_diffs.get("totalAPagar", 0))
                if abs_pagar < 0.05:
                    range_trivial += 1
                elif abs_pagar <= 1.00:
                    range_minor += 1
                else:
                    range_material += 1

        except Exception:
            skipped += 1

    # --- RESUMEN ---
    sys.stdout.write("\r" + " " * 90 + "\r")
    print(f"\n{'=' * 70}")
    print(f"  RESUMEN GENERAL")
    print(f"{'=' * 70}")
    print(f"    Total:              {total}")
    print(f"    F1 — Discrepancias: {mismatches_p1} (payload actual vs factura)")
    print(f"    F2 — Discrepancias: {mismatches_p2} (payload enviado vs actual)")
    print(f"    Sin log HKA:        {no_log}")
    print(f"    Omitidas:           {skipped} (datos incompletos)")
    ok: int = total - mismatches_p1 - mismatches_p2 - skipped - no_log
    print(f"    OK:                 {ok}")

    if mismatches_p2 > 0:
        print(f"\n{'=' * 70}")
        print(f"  MAGNITUD DE DIFERENCIAS F2 (totalAPagar VEF)")
        print(f"{'=' * 70}")
        print(f"    < 0.05 VEF (despreciable): {range_trivial}")
        print(f"    0.05 - 1.00 VEF (menor):   {range_minor}")
        print(f"    > 1.00 VEF (material):      {range_material}")

        print(f"\n{'=' * 70}")
        print(f"  DIFERENCIA ACUMULADA F2 (enviado - actual)")
        print(f"{'=' * 70}")
        print(f"  {'Campo':<30} {'VEF':>15} {'USD':>15}")
        print(f"  {'-' * 60}")
        for field in _TOTALES_FIELDS:
            vef_val: float = total_diff_vef[field]
            usd_val: float = total_diff_usd[field]
            print(f"  {field:<30} {vef_val:>+15.2f} {usd_val:>+15.2f}")

    print(f"{'=' * 70}\n")

    # =================================================================== #
    # FASE 3: Montos ERP vs payload exitoso HKA (desde 16 de abril)       #
    # =================================================================== #

    cutoff_date: str = "2026-04-16"
    recent_invoices: list[dict] = frappe.db.get_all(
        "Sales Invoice",
        filters={
            "docstatus": ["in", [1, 2]],
            "bill_no": ["is", "set"],
            "posting_date": [">=", cutoff_date],
        },
        fields=["name", "base_net_total", "base_grand_total",
                "base_total_taxes_and_charges", "conversion_rate",
                "total", "grand_total"],
        order_by="posting_date ASC",
    )

    total_f3: int = len(recent_invoices)
    mismatches_f3: int = 0
    no_log_f3: int = 0
    mismatched_ids: list[dict] = []

    print(f"\n{'=' * 70}")
    print(f"  Fase 3: Montos ERP vs payload exitoso HKA")
    print(f"  Facturas desde {cutoff_date} — {total_f3} documentos")
    print(f"{'=' * 70}\n")

    for j, inv in enumerate(recent_invoices, 1):
        _print_progress(j, total_f3, mismatches_f3, 0, no_log_f3, "F3")

        sent_payload: dict | None = _get_sent_payload(inv.name)
        if sent_payload is None:
            no_log_f3 += 1
            continue

        sent_totales: dict = _extract_totales(sent_payload, "totales")
        if not sent_totales:
            no_log_f3 += 1
            continue

        # Obtener datos de impuestos de la factura
        doc = frappe.get_doc("Sales Invoice", inv.name)
        base_net: float = flt(doc.base_net_total)

        base_vat: float = 0.0
        for tax in doc.get("taxes", []):
            if tax.get("charge_type") == "VAT" and flt(tax.rate) > 0:
                base_vat += flt(tax.base_tax_amount)

        exempt_base: float = flt(doc.get("total_exempt", 0.0)) * flt(doc.conversion_rate or 1)

        # Mapeo ERP → campos HKA
        erp_values: dict[str, float] = {
            "subtotal": base_net,
            "montoGravadoTotal": base_net - exempt_base,
            "montoExentoTotal": exempt_base,
            "totalIVA": base_vat,
            "montoTotalConIVA": base_net + base_vat,
        }

        # Comparar contra payload enviado
        field_errors: list[str] = []
        for field, erp_val in erp_values.items():
            hka_val: float = flt(sent_totales.get(field, 0))
            diff: float = abs(hka_val - erp_val)
            if diff > _TOLERANCE:
                field_errors.append(
                    f"  {field}: ERP={erp_val:.2f}, HKA={hka_val:.2f} (Δ {diff:.2f})"
                )

        if field_errors:
            mismatches_f3 += 1
            mismatched_ids.append({
                "name": inv.name,
                "errors": field_errors,
            })

    # --- RESUMEN F3 ---
    sys.stdout.write("\r" + " " * 90 + "\r")
    print(f"\n{'=' * 70}")
    print(f"  RESUMEN FASE 3")
    print(f"{'=' * 70}")
    print(f"    Total (desde {cutoff_date}): {total_f3}")
    print(f"    Discrepancias:              {mismatches_f3}")
    print(f"    Sin log HKA:                {no_log_f3}")
    ok_f3: int = total_f3 - mismatches_f3 - no_log_f3
    print(f"    OK:                         {ok_f3}")

    if mismatched_ids:
        print(f"\n{'=' * 70}")
        print(f"  FACTURAS CON DISCREPANCIA (ERP vs HKA enviado)")
        print(f"{'=' * 70}")
        for entry in mismatched_ids:
            print(f"\n  ❌ {entry['name']}")
            for err in entry["errors"]:
                print(f"    {err}")

    print(f"\n{'=' * 70}\n")

