"""
Diagnóstico: ¿por qué descuadran los reportes fiscales con el Mayor General?

Uso:
  bench --site [site] execute l10n_ve.diagnostico_reportes.run --kwargs '{"company": "GALANET", "from_date": "2026-06-01", "to_date": "2026-06-30"}'

Solo resumen:
  bench --site [site] execute l10n_ve.diagnostico_reportes.run --kwargs '{"company": "GALANET", "from_date": "2026-06-01", "to_date": "2026-06-30", "detalle": false}'

Una cuenta específica:
  bench --site [site] execute l10n_ve.diagnostico_reportes.run --kwargs '{"company": "GALANET", "from_date": "2026-06-01", "to_date": "2026-06-30", "cuenta": "1110004"}'
"""

from __future__ import annotations

import frappe
from frappe.utils import flt


def run(company=None, from_date=None, to_date=None, detalle=True, cuenta=None):
    if not company:
        companies = frappe.db.sql_list("SELECT name FROM tabCompany ORDER BY name")
        if len(companies) == 1:
            company = companies[0]
            print(f"Usando única compañía disponible: {company}")
        else:
            frappe.throw(f"Debe especificar 'company'. Compañías disponibles: {companies}")
    if not from_date or not to_date:
        frappe.throw("Debe especificar 'from_date' y 'to_date'")

    _print_header(company, from_date, to_date)

    diagnostics = {
        "1110004": diagnosticar_iva_credito_fiscal,
        "2105002": diagnosticar_retenciones_iva,
        "2105003": diagnosticar_retenciones_islr,
        "2105001": diagnosticar_iva_debito_fiscal,
        "2105005": diagnosticar_igtf,
        "4101001": diagnosticar_ingresos_internet,
    }

    if cuenta:
        cuenta_clean = cuenta.strip()
        if cuenta_clean in diagnostics:
            diagnostics[cuenta_clean](company, from_date, to_date, detalle)
        else:
            frappe.msgprint(f"No hay diagnóstico implementado para la cuenta {cuenta_clean}")
        return

    for cuenta_key, func in diagnostics.items():
        func(company, from_date, to_date, detalle)
        print("─" * 80)


def run_default():
    """Entry point sin kwargs para bench execute."""
    import frappe
    companies = frappe.db.sql_list("SELECT name FROM tabCompany ORDER BY name")
    if not companies:
        print("No hay compañías en este sitio")
        return
    company = companies[0]
    print(f"Compañía autodetectada: {company}")
    if len(companies) > 1:
        print(f"  (También disponibles: {companies[1:]})")
    run(company=company, from_date="2026-06-01", to_date="2026-06-30", detalle=True)


def _print_header(company, from_date, to_date):
    print()
    print("═" * 80)
    print(f"  DIAGNÓSTICO DE DESCUA DRES — {company}")
    print(f"  Período: {from_date} al {to_date}")
    print("═" * 80)


# ─────────────────────────────────────────────────────────────────────────────
# 1. IVA CRÉDITO FISCAL (1110004)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_iva_credito_fiscal(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 1110004 — IVA CRÉDITO FISCAL")
    print()

    # GL total en el período
    gl_total = frappe.db.sql("""
        SELECT SUM(debit - credit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%1110004%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0

    # Total desde Purchase Book (impuesto)
    pb_total = _get_purchase_book_iva_total(company, from_date, to_date)
    diff = gl_total - pb_total

    print(f"    Mayor General (GL):    {_fmt(gl_total)}")
    print(f"    Purchase Book (reporte): {_fmt(pb_total)}")
    print(f"    Diferencia:             {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) GL entries de voucher_type NO esperado (JEs, Payment Entry, etc) ----
    rows_otros_origenes = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%1110004%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type NOT IN ('Purchase Invoice', 'VE Purchase Credit Note', 'VE Purchase Debit Note', 'Sales Invoice')
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_otros_origenes:
        total_otros = sum(flt(r.debit or 0) - flt(r.credit or 0) for r in rows_otros_origenes)
        print(f"  ─── A) GL entries de ORIGEN NO ESPERADO (no vienen de Purchase Invoice) ───")
        print(f"      Total: {_fmt(total_otros)}")
        for r in rows_otros_origenes:
            monto = flt(r.debit or 0) - flt(r.credit or 0)
            print(f"      [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(monto)}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()
    else:
        print("  ✓ Todos los GL entries vienen de Purchase Invoice/NC/ND")

    # ---- B) Purchase Invoices sin datos fiscales ----
    rows_sin_fiscal = frappe.db.sql("""
        SELECT pi.name, pi.posting_date, pi.supplier, pi.supplier_name,
               pi.bill_no, pi.bill_control, pi.base_grand_total
        FROM `tabPurchase Invoice` pi
        WHERE pi.company = %s
          AND pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
          AND (pi.bill_no IS NULL OR pi.bill_no = '' OR pi.bill_control IS NULL OR pi.bill_control = '')
        ORDER BY pi.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_sin_fiscal:
        total_sf = sum(flt(r.base_grand_total) for r in rows_sin_fiscal)
        print(f"  ─── B) Purchase Invoices SIN bill_no/bill_control (tienen GL, no aparecen en Libro de Compras si el libro filtra por datos fiscales) ───")
        print(f"      Cantidad: {len(rows_sin_fiscal)}, Total base: {_fmt(total_sf)}")
        for r in rows_sin_fiscal:
            print(f"      [{r.posting_date}] {r.name} - {r.supplier_name}: bill_no={r.bill_no}, control={r.bill_control}, total={_fmt(r.base_grand_total)}")
        print()
    else:
        print("  ✓ Todas las PIs tienen bill_no y bill_control")

    # ---- C) Purchase Invoices con posteo en GL pero fuera del rango de fechas del Purchase Book ----
    rows_fuera_rango = frappe.db.sql("""
        SELECT gle.voucher_no, gle.posting_date, gle.debit, gle.credit
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%1110004%%'
          AND gle.company = %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type = 'Purchase Invoice'
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.voucher_no NOT IN (
              SELECT DISTINCT name FROM `tabPurchase Invoice`
              WHERE company = %s
                AND docstatus = 1
                AND posting_date BETWEEN %s AND %s
          )
        ORDER BY gle.posting_date
    """, (company, from_date, to_date, company, from_date, to_date), as_dict=True)

    if rows_fuera_rango:
        total_fr = sum(flt(r.debit or 0) - flt(r.credit or 0) for r in rows_fuera_rango)
        print(f"  ─── C) GL entries de PI que NO están en el Purchase Book del período ───")
        print(f"      Total: {_fmt(total_fr)}")
        for r in rows_fuera_rango:
            monto = flt(r.debit or 0) - flt(r.credit or 0)
            print(f"      [{r.posting_date}] PI {r.voucher_no}: {_fmt(monto)}")
        print()

    # ---- D) Si Purchase Book da 0, debug profundo ----
    if pb_total == 0:
        _debug_purchase_book_cero(company, from_date, to_date)

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# 2. RETENCIONES IVA PROVEEDORES (2105002)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_retenciones_iva(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 2105002 — RETENCIONES DE IVA PROVEEDORES")
    print()

    gl_total = frappe.db.sql("""
        SELECT SUM(credit - debit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%2105002%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0

    rr_total = _get_retenciones_iva_total(company, from_date, to_date)
    diff = gl_total - rr_total

    print(f"    Mayor General (GL):      {_fmt(gl_total)}")
    print(f"    Reporte Retenciones IVA: {_fmt(rr_total)}")
    print(f"    Diferencia:              {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) GL entries que NO vienen de Purchase Invoice (JEs, etc) ----
    rows_otros = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%2105002%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type NOT IN ('Purchase Invoice', 'VE Purchase Credit Note', 'VE Purchase Debit Note')
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_otros:
        total_otros = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_otros)
        print(f"  ─── A) GL entries de origen NO esperado (JEs / Payment Entry) ───")
        print(f"      Total: {_fmt(total_otros)}")
        for r in rows_otros:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(monto)}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()

    # ---- B) Purchase Invoices con retención IVA en GL pero SIN VAT Withholding Voucher ----
    rows_sin_voucher = frappe.db.sql("""
        SELECT pi.name, pi.posting_date, pi.supplier_name, pi.bill_no,
               ABS(SUM(ptc.base_tax_amount)) AS monto_retencion
        FROM `tabPurchase Invoice` pi
        INNER JOIN `tabPurchase Taxes and Charges` ptc
            ON ptc.parent = pi.name AND ptc.charge_type = 'VAT Withholding'
        WHERE pi.company = %s
          AND pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
          AND pi.name NOT IN (
              SELECT DISTINCT wvi.purchase_invoice
              FROM `tabVAT Withholding Voucher Item` wvi
              INNER JOIN `tabVAT Withholding Voucher` wv ON wvi.parent = wv.name
              WHERE wv.docstatus = 1
          )
        GROUP BY pi.name, pi.posting_date, pi.supplier_name, pi.bill_no
        ORDER BY pi.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_sin_voucher:
        total_sv = sum(flt(r.monto_retencion) for r in rows_sin_voucher)
        print(f"  ─── B) Purchase Invoices CON retención IVA en GL pero SIN Comprobante de Retención emitido ───")
        print(f"      Cantidad: {len(rows_sin_voucher)}, Total retención: {_fmt(total_sv)}")
        print(f"      → Estas facturas crean GL entry al submit, pero el comprobante de retención")
        print(f"        aún no se ha creado (o está en borrador). El reporte de retenciones NO las muestra.")
        for r in rows_sin_voucher:
            print(f"      [{r.posting_date}] PI {r.name} - {r.supplier_name}: ret_IVA={_fmt(r.monto_retencion)}")
        print()

    if rr_total == 0 and gl_total > 0:
        _debug_retenciones_iva(company, from_date, to_date)

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# 3. RETENCIONES ISLR PROVEEDORES (2105003)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_retenciones_islr(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 2105003 — RETENCIONES DE ISLR PROVEEDORES")
    print()

    gl_total = frappe.db.sql("""
        SELECT SUM(credit - debit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%2105003%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0

    rr_total = _get_retenciones_islr_total(company, from_date, to_date)
    diff = gl_total - rr_total

    print(f"    Mayor General (GL):       {_fmt(gl_total)}")
    print(f"    Reporte Retenciones ISLR: {_fmt(rr_total)}")
    print(f"    Diferencia:               {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) GL entries de origen NO esperado ----
    rows_otros = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%2105003%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type NOT IN ('Purchase Invoice', 'VE Purchase Credit Note', 'VE Purchase Debit Note')
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_otros:
        total_otros = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_otros)
        print(f"  ─── A) GL entries de origen NO esperado (JEs / Payment Entry / otros) ───")
        print(f"      Total: {_fmt(total_otros)}")
        for r in rows_otros:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(monto)}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()

    # ---- B) Purchase Invoices con retención ISLR en GL pero SIN ISLR Withholding Voucher ----
    rows_sin_voucher = frappe.db.sql("""
        SELECT pi.name, pi.posting_date, pi.supplier_name, pi.bill_no,
               ABS(SUM(ptc.base_tax_amount)) AS monto_retencion
        FROM `tabPurchase Invoice` pi
        INNER JOIN `tabPurchase Taxes and Charges` ptc
            ON ptc.parent = pi.name AND ptc.charge_type = 'ISLR Withholding'
        WHERE pi.company = %s
          AND pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
          AND pi.name NOT IN (
              SELECT DISTINCT islr_item.purchase_invoice
              FROM `tabISLR Withholding Voucher Item` islr_item
              INNER JOIN `tabISLR Withholding Voucher` islr_v ON islr_item.parent = islr_v.name
              WHERE islr_v.docstatus = 1
          )
        GROUP BY pi.name, pi.posting_date, pi.supplier_name, pi.bill_no
        ORDER BY pi.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_sin_voucher:
        total_sv = sum(flt(r.monto_retencion) for r in rows_sin_voucher)
        print(f"  ─── B) Purchase Invoices CON retención ISLR en GL pero SIN Comprobante de Retención ───")
        print(f"      Cantidad: {len(rows_sin_voucher)}, Total retención: {_fmt(total_sv)}")
        for r in rows_sin_voucher:
            print(f"      [{r.posting_date}] PI {r.name} - {r.supplier_name}: ret_ISLR={_fmt(r.monto_retencion)}")
        print()

    if rr_total == 0 and gl_total > 0:
        _debug_retenciones_islr(company, from_date, to_date)

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# 4. IVA DÉBITO FISCAL (2105001)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_iva_debito_fiscal(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 2105001 — IVA DÉBITO FISCAL")
    print()

    gl_total = frappe.db.sql("""
        SELECT SUM(credit - debit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%2105001%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0

    sb_total = _get_sales_book_iva_total(company, from_date, to_date)
    diff = gl_total - sb_total

    print(f"    Mayor General (GL):   {_fmt(gl_total)}")
    print(f"    Sales Book (reporte): {_fmt(sb_total)}")
    print(f"    Diferencia:           {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) GL entries de origen NO esperado (JEs, etc) ----
    rows_otros = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%2105001%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type NOT IN ('Sales Invoice', 'VE Sales Credit Note', 'VE Sales Debit Note')
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_otros:
        total_otros = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_otros)
        print(f"  ─── A) GL entries de origen NO esperado (JEs / otros) ───")
        print(f"      Total: {_fmt(total_otros)}")
        for r in rows_otros:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(monto)}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()

    # ---- B) Sales Invoices sin bill_no/bill_control ----
    rows_sin_fiscal = frappe.db.sql("""
        SELECT si.name, si.posting_date, si.customer_name, si.bill_no, si.bill_control,
               si.base_grand_total
        FROM `tabSales Invoice` si
        WHERE si.company = %s
          AND si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
          AND (si.bill_no IS NULL OR si.bill_no = '' OR si.bill_control IS NULL OR si.bill_control = '')
        ORDER BY si.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_sin_fiscal:
        total_sf = sum(flt(r.base_grand_total) for r in rows_sin_fiscal)
        print(f"  ─── B) Sales Invoices SIN bill_no/bill_control (tienen GL, no aparecen en Libro de Ventas) ───")
        print(f"      Cantidad: {len(rows_sin_fiscal)}, Total: {_fmt(total_sf)}")
        for r in rows_sin_fiscal:
            print(f"      [{r.posting_date}] SI {r.name} - {r.customer_name}: bill_no={r.bill_no}, control={r.bill_control}")
        print()

    # ---- C) Con HKA activo: facturas sin certificación HKA ----
    hka_enabled = False
    try:
        hka_enabled = frappe.db.get_single_value("TFHKA Settings", "enabled", cache=True)
    except Exception:
        pass

    if hka_enabled:
        rows_no_hka = frappe.db.sql("""
            SELECT si.name, si.posting_date, si.customer_name, si.remarks
            FROM `tabSales Invoice` si
            WHERE si.company = %s
              AND si.docstatus = 1
              AND si.posting_date BETWEEN %s AND %s
              AND si.bill_no IS NOT NULL AND si.bill_no != ''
              AND si.bill_control IS NOT NULL AND si.bill_control != ''
              AND (si.remarks IS NULL OR si.remarks = '' OR LOCATE('"numeroControl"', si.remarks) = 0)
            ORDER BY si.posting_date
        """, (company, from_date, to_date), as_dict=True)

        if rows_no_hka:
            total_nh = sum(flt(r.remarks and 1 or 0) for r in rows_no_hka)  # placeholder
            print(f"  ─── C) HKA ACTIVO: Facturas SIN certificación HKA (en GL, no en Libro de Ventas) ───")
            print(f"      Cantidad: {len(rows_no_hka)}")
            for r in rows_no_hka[:20]:
                remarks_preview = (r.remarks or "")[:80]
                print(f"      [{r.posting_date}] SI {r.name} - {r.customer_name}")
            if len(rows_no_hka) > 20:
                print(f"      ... y {len(rows_no_hka) - 20} más")
            print()
    else:
        print("  → HKA NO activo, no aplica filtro de certificación")

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# 5. IGTF (2105005)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_igtf(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 2105005 — IGTF POR PAGAR")
    print()

    gl_total = frappe.db.sql("""
        SELECT SUM(credit - debit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%2105005%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0

    sb_igtf = _get_sales_book_igtf_total(company, from_date, to_date)
    diff = gl_total - sb_igtf

    print(f"    Mayor General (GL):      {_fmt(gl_total)}")
    print(f"    Sales Book / Reporte:    {_fmt(sb_igtf)}")
    print(f"    Diferencia:              {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) GL entries de IGTF que vienen de Payment Entry (no de SI) ----
    rows_payment = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.against_voucher, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%2105005%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type = 'Payment Entry'
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_payment:
        total_pay = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_payment)
        print(f"  ─── A) IGTF generado por Payment Entry (pago) — NO por Sales Invoice ───")
        print(f"      El reporte IGTF usa total_igtf de la factura; el GL lo crea al pagar.")
        print(f"      Si una factura se paga en varios abonos, el GL suma más que el reporte.")
        print(f"      Total en Payment Entries: {_fmt(total_pay)}")
        for r in rows_payment:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] PE {r.voucher_no}: {_fmt(monto)} → contra {r.against_voucher}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()

    # ---- B) IGTF de JEs directos ----
    rows_je = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%2105005%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type = 'Journal Entry'
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_je:
        total_je = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_je)
        print(f"  ─── B) IGTF de Journal Entries directos ───")
        print(f"      Total: {_fmt(total_je)}")
        for r in rows_je:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] JE {r.voucher_no}: {_fmt(monto)}")
        print()

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# 6. INGRESOS SERVICIOS DE INTERNET (4101001)
# ─────────────────────────────────────────────────────────────────────────────

def diagnosticar_ingresos_internet(company, from_date, to_date, detalle):
    print()
    print("  ▶ CUENTA 4101001 — INGRESOS SERVICIOS DE INTERNET")
    print()

    # GL total (creditos - debitos) en la cuenta 4101001
    gl_total = flt(frappe.db.sql("""
        SELECT SUM(credit - debit) AS total
        FROM `tabGL Entry`
        WHERE account LIKE '%%4101001%%'
          AND company = %s
          AND posting_date BETWEEN %s AND %s
          AND is_cancelled = 0
    """, (company, from_date, to_date))[0][0] or 0)

    # Total SI Items que contabilizan a cuenta 4101001 (neto en VEF)
    sb_total = flt(frappe.db.sql("""
        SELECT SUM(COALESCE(sii.base_amount, 0)
                   * CASE WHEN si.is_return = 1 THEN -1 ELSE 1 END) AS total
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
        WHERE si.company = %s
          AND si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
          AND COALESCE(sii.income_account, '') LIKE '%%4101001%%'
    """, (company, from_date, to_date))[0][0] or 0)

    diff = gl_total - sb_total

    print(f"    Mayor General (GL):      {_fmt(gl_total)}")
    print(f"    Sales Invoice Items:      {_fmt(sb_total)}")
    print(f"    Diferencia:               {_fmt(diff)}")
    print()

    if not detalle:
        return

    # ---- A) Facturas en GL pero sin bill_no/bill_control (no aparecen en Libro de Ventas) ----
    rows_sin_fiscal = frappe.db.sql("""
        SELECT si.name, si.posting_date, si.customer_name,
               si.bill_no, si.bill_control,
               (SELECT SUM(COALESCE(sii.base_amount, 0) * CASE WHEN si.is_return = 1 THEN -1 ELSE 1 END)
                FROM `tabSales Invoice Item` sii
                WHERE sii.parent = si.name
                  AND COALESCE(sii.income_account, '') LIKE '%%4101001%%') AS base_ingreso
        FROM `tabSales Invoice` si
        WHERE si.company = %s
          AND si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
          AND (si.bill_no IS NULL OR si.bill_no = '' OR si.bill_control IS NULL OR si.bill_control = '')
          AND EXISTS (
              SELECT 1 FROM `tabSales Invoice Item` sii2
              WHERE sii2.parent = si.name
                AND COALESCE(sii2.income_account, '') LIKE '%%4101001%%'
          )
        ORDER BY si.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_sin_fiscal:
        total_sf = sum(flt(r.base_ingreso) for r in rows_sin_fiscal)
        print(f"  ─── A) Facturas SIN bill_no/bill_control que afectan 4101001 ───")
        print(f"      Tienen GL pero NO aparecen en Libro de Ventas")
        print(f"      Cantidad: {len(rows_sin_fiscal)}, Total ingreso: {_fmt(total_sf)}")
        for r in rows_sin_fiscal:
            print(f"      [{r.posting_date}] SI {r.name} - {r.customer_name}: {_fmt(r.base_ingreso)}")
        print()

    # ---- B) JEs / otros documentos directos a la cuenta 4101001 ----
    rows_otros = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, gle.posting_date,
               gle.debit, gle.credit, gle.remarks
        FROM `tabGL Entry` gle
        WHERE gle.account LIKE '%%4101001%%'
          AND gle.company = %s
          AND gle.posting_date BETWEEN %s AND %s
          AND gle.is_cancelled = 0
          AND gle.voucher_type NOT IN ('Sales Invoice', 'VE Sales Credit Note', 'VE Sales Debit Note')
        ORDER BY gle.posting_date
    """, (company, from_date, to_date), as_dict=True)

    if rows_otros:
        total_otros = sum(flt(r.credit or 0) - flt(r.debit or 0) for r in rows_otros)
        print(f"  ─── B) GL entries de origen NO esperado (JEs / Payment Entry / otros) ───")
        print(f"      Total: {_fmt(total_otros)}")
        for r in rows_otros:
            monto = flt(r.credit or 0) - flt(r.debit or 0)
            print(f"      [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(monto)}")
            if r.remarks:
                print(f"        → {r.remarks[:120]}")
        print()

    # ---- C) Si HKA activo: facturas sin certificaci�n que afectan 4101001 ----
    hka_enabled = False
    try:
        hka_enabled = frappe.db.get_single_value("TFHKA Settings", "enabled", cache=True)
    except Exception:
        pass

    if hka_enabled:
        rows_no_hka = frappe.db.sql("""
            SELECT si.name, si.posting_date, si.customer_name,
                   (SELECT SUM(COALESCE(sii.base_amount, 0) * CASE WHEN si.is_return = 1 THEN -1 ELSE 1 END)
                    FROM `tabSales Invoice Item` sii
                    WHERE sii.parent = si.name
                      AND COALESCE(sii.income_account, '') LIKE '%%4101001%%') AS base_ingreso
            FROM `tabSales Invoice` si
            WHERE si.company = %s
              AND si.docstatus = 1
              AND si.posting_date BETWEEN %s AND %s
              AND si.bill_no IS NOT NULL AND si.bill_no != ''
              AND si.bill_control IS NOT NULL AND si.bill_control != ''
              AND (si.remarks IS NULL OR si.remarks = '' OR LOCATE('"numeroControl"', si.remarks) = 0)
              AND EXISTS (
                  SELECT 1 FROM `tabSales Invoice Item` sii2
                  WHERE sii2.parent = si.name
                    AND COALESCE(sii2.income_account, '') LIKE '%%4101001%%'
              )
            ORDER BY si.posting_date
        """, (company, from_date, to_date), as_dict=True)

        if rows_no_hka:
            total_nh = sum(flt(r.base_ingreso) for r in rows_no_hka)
            print(f"  ─── C) HKA ACTIVO: Facturas SIN certificaci�n HKA que afectan 4101001 ───")
            print(f"      Cantidad: {len(rows_no_hka)}, Total ingreso: {_fmt(total_nh)}")
            for r in rows_no_hka[:20]:
                print(f"      [{r.posting_date}] SI {r.name} - {r.customer_name}: {_fmt(r.base_ingreso)}")
            if len(rows_no_hka) > 20:
                print(f"      ... y {len(rows_no_hka) - 20} m�s")
            print()

    return diff


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG: Retenciones IVA / ISLR returning 0
# ─────────────────────────────────────────────────────────────────────────────

def _debug_retenciones_iva(company, from_date, to_date):
    print(f"  ─── C) DEBUG: Reporte Retenciones IVA da 0. Verificando causas ───")

    # C1) Verificar empresa field en VAT Withholding Voucher
    empresas = frappe.db.sql("""
        SELECT DISTINCT empresa FROM `tabVAT Withholding Voucher`
        WHERE docstatus=1 ORDER BY empresa
    """, as_dict=True)
    print(f"      C1) Valores de 'empresa' en VAT Withholding Voucher:")
    for r in empresas:
        match = "✓ COINCIDE" if r.empresa == company else "✗ DIFIERE"
        print(f"          '{r.empresa}' {match}")

    # C2) Verificar la query del reporte de retenciones
    total_items = frappe.db.sql("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(COALESCE(child.tax_amount_vat,0)),0) AS total
        FROM `tabVAT Withholding Voucher Item` child
        INNER JOIN `tabVAT Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.empresa = %s AND parent.docstatus = 1
    """, (company,), as_dict=True)
    print(f"      C2) Items con empresa='{company}': cnt={total_items[0].cnt}, total={_fmt(total_items[0].total)}")

    # C3) Sin filtro de empresa
    total_all = frappe.db.sql("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(COALESCE(child.tax_amount_vat,0)),0) AS total
        FROM `tabVAT Withholding Voucher Item` child
        INNER JOIN `tabVAT Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.docstatus = 1
    """, as_dict=True)
    print(f"      C3) Todos los items (sin filtro empresa): cnt={total_all[0].cnt}, total={_fmt(total_all[0].total)}")

    # C4) Verificar fechas (issue_date)
    fechas = frappe.db.sql("""
        SELECT MIN(issue_date) AS min_d, MAX(issue_date) AS max_d
        FROM `tabVAT Withholding Voucher`
        WHERE empresa=%s AND docstatus=1
    """, (company,), as_dict=True)
    if fechas and fechas[0].min_d:
        print(f"      C4) issue_date range for empresa='{company}': {fechas[0].min_d} to {fechas[0].max_d}")
    else:
        print(f"      C4) No hay vouchers con empresa='{company}' y docstatus=1")

    # C5) GL entries que generan el saldo
    gl_src = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, posting_date,
               SUM(credit-debit) AS monto
        FROM `tabGL Entry` gle
        WHERE account LIKE '%%2105002%%' AND company=%s
          AND posting_date BETWEEN %s AND %s AND is_cancelled=0
        GROUP BY gle.voucher_type, gle.voucher_no, posting_date
        ORDER BY posting_date
    """, (company, from_date, to_date), as_dict=True)
    print(f"      C5) GL entries que componen el saldo de 2105002:")
    for r in gl_src[:10]:
        print(f"          [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(r.monto)}")
    if len(gl_src) > 10:
        print(f"          ... y {len(gl_src)-10} más")

    print()


def _debug_retenciones_islr(company, from_date, to_date):
    print(f"  ─── C) DEBUG: Reporte Retenciones ISLR da 0. Verificando causas ───")

    empresas = frappe.db.sql("""
        SELECT DISTINCT empresa FROM `tabISLR Withholding Voucher`
        WHERE docstatus=1 ORDER BY empresa
    """, as_dict=True)
    print(f"      C1) Valores de 'empresa' en ISLR Withholding Voucher:")
    for r in empresas:
        match = "✓ COINCIDE" if r.empresa == company else "✗ DIFIERE"
        print(f"          '{r.empresa}' {match}")

    total_items = frappe.db.sql("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(COALESCE(child.islr_amount,0)),0) AS total
        FROM `tabISLR Withholding Voucher Item` child
        INNER JOIN `tabISLR Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.empresa = %s AND parent.docstatus = 1
    """, (company,), as_dict=True)
    print(f"      C2) Items con empresa='{company}': cnt={total_items[0].cnt}, total={_fmt(total_items[0].total)}")

    total_all = frappe.db.sql("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(COALESCE(child.islr_amount,0)),0) AS total
        FROM `tabISLR Withholding Voucher Item` child
        INNER JOIN `tabISLR Withholding Voucher` parent ON child.parent = parent.name
        WHERE parent.docstatus = 1
    """, as_dict=True)
    print(f"      C3) Todos los items (sin filtro empresa): cnt={total_all[0].cnt}, total={_fmt(total_all[0].total)}")

    fechas = frappe.db.sql("""
        SELECT MIN(posting_date) AS min_d, MAX(posting_date) AS max_d
        FROM `tabISLR Withholding Voucher`
        WHERE empresa=%s AND docstatus=1
    """, (company,), as_dict=True)
    if fechas and fechas[0].min_d:
        print(f"      C4) posting_date range for empresa='{company}': {fechas[0].min_d} to {fechas[0].max_d}")
    else:
        print(f"      C4) No hay vouchers con empresa='{company}' y docstatus=1")

    gl_src = frappe.db.sql("""
        SELECT gle.voucher_type, gle.voucher_no, posting_date,
               SUM(credit-debit) AS monto
        FROM `tabGL Entry` gle
        WHERE account LIKE '%%2105003%%' AND company=%s
          AND posting_date BETWEEN %s AND %s AND is_cancelled=0
        GROUP BY gle.voucher_type, gle.voucher_no, posting_date
        ORDER BY posting_date
    """, (company, from_date, to_date), as_dict=True)
    print(f"      C5) GL entries que componen el saldo de 2105003:")
    for r in gl_src[:5]:
        print(f"          [{r.posting_date}] {r.voucher_type} {r.voucher_no}: {_fmt(r.monto)}")
    if len(gl_src) > 5:
        print(f"          ... y {len(gl_src)-5} más")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG: Purchase Book returning 0
# ─────────────────────────────────────────────────────────────────────────────

def _debug_purchase_book_cero(company, from_date, to_date):
    """Rastrea por qué el Purchase Book no devuelve filas."""
    print(f"  ─── D) DEBUG: Purchase Book da 0 filas. Rastreando causas ───")

    # D1) PIs sin bill_no/bill_control (el Purchase Book NO filtra por esto, pero verificamos)
    rows_sin_fiscal = frappe.db.sql("""
        SELECT COUNT(*) AS cnt, COALESCE(SUM(base_grand_total),0) AS total
        FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1
          AND posting_date BETWEEN %s AND %s
          AND (bill_no IS NULL OR bill_no='' OR bill_control IS NULL OR bill_control='')
    """, (company, from_date, to_date), as_dict=True)
    if rows_sin_fiscal and rows_sin_fiscal[0].cnt > 0:
        print(f"      D1) PIs sin datos fiscales: {rows_sin_fiscal[0].cnt} ({_fmt(rows_sin_fiscal[0].total)})")
    else:
        print(f"      D1) Todas las PIs tienen datos fiscales ✓")

    # D2) Verificar rango de fechas: el Purchase Book usa loose_from_date (3 meses antes)
    from frappe.utils import add_months
    loose_from_date = add_months(from_date, -3)
    pis_loose = frappe.db.sql("""
        SELECT COUNT(*) AS cnt FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1 AND is_return=0
          AND posting_date BETWEEN %s AND %s
    """, (company, loose_from_date, to_date), as_dict=True)
    print(f"      D2) PIs (is_return=0) en rango amplio [{loose_from_date} - {to_date}]: {pis_loose[0].cnt}")

    # D3) El Purchase Book filtra con COALESCE(wv.delivery_date, pi.posting_date) BETWEEN from_date AND to_date
    # Verificar cuántas PIs tienen delivery_date vs posting_date
    pis_eff = frappe.db.sql("""
        SELECT pi.name, pi.posting_date, pi.bill_no, pi.base_grand_total,
            (SELECT wv.delivery_date FROM `tabVAT Withholding Voucher Item` wvi
             INNER JOIN `tabVAT Withholding Voucher` wv ON wvi.parent=wv.name AND wv.docstatus=1
             WHERE wvi.purchase_invoice=pi.name LIMIT 1) AS delivery_date
        FROM `tabPurchase Invoice` pi
        WHERE pi.company=%s AND pi.docstatus=1 AND pi.is_return=0
          AND pi.posting_date BETWEEN %s AND %s
        ORDER BY pi.posting_date
    """, (company, loose_from_date, to_date), as_dict=True)

    if pis_eff:
        en_rango = 0
        fuera_rango = 0
        con_delivery = 0
        sin_delivery = 0
        for r in pis_eff:
            eff_date = r.delivery_date or r.posting_date
            if str(eff_date) >= from_date and str(eff_date) <= to_date:
                en_rango += 1
            else:
                fuera_rango += 1
            if r.delivery_date:
                con_delivery += 1
            else:
                sin_delivery += 1
        print(f"      D3) Fecha efectiva (delivery|posting) en rango [{from_date} - {to_date}]:")
        print(f"          En rango: {en_rango}, Fuera de rango: {fuera_rango}")
        print(f"          Con delivery_date (tienen retención): {con_delivery}, Sin: {sin_delivery}")
        if fuera_rango > 0:
            print(f"          Muestras fuera de rango:")
            for r in pis_eff:
                eff_date = r.delivery_date or r.posting_date
                if not (str(eff_date) >= from_date and str(eff_date) <= to_date):
                    print(f"            PI {r.name} post={r.posting_date} delivery={r.delivery_date} eff={eff_date} bill={r.bill_no} total={_fmt(r.base_grand_total)}")
    else:
        print(f"      D3) No hay PIs en el rango amplio")

    # D4) Verificar supplier_warehouse (aunque no está en la query actual)
    pis_wh = frappe.db.sql("""
        SELECT COUNT(*) AS cnt FROM `tabPurchase Invoice`
        WHERE company=%s AND docstatus=1 AND is_return=0
          AND posting_date BETWEEN %s AND %s
          AND supplier_warehouse IS NOT NULL AND supplier_warehouse != ''
    """, (company, loose_from_date, to_date), as_dict=True)
    if pis_wh[0].cnt > 0:
        print(f"      D4) PIs con supplier_warehouse no vacío: {pis_wh[0].cnt} (esto NO es filtro actualmente)")
    else:
        print(f"      D4) No hay PIs con supplier_warehouse ✓")

    # D5) Tax accounts en PIs: verificar que existan Purchase Taxes and Charges para el período
    taxes_count = frappe.db.sql("""
        SELECT COUNT(DISTINCT ptc.parent) AS cnt
        FROM `tabPurchase Taxes and Charges` ptc
        INNER JOIN `tabPurchase Invoice` pi ON ptc.parent = pi.name
        WHERE pi.company=%s AND pi.docstatus=1 AND pi.is_return=0
          AND pi.posting_date BETWEEN %s AND %s
    """, (company, loose_from_date, to_date), as_dict=True)
    print(f"      D5) PIs con Purchase Taxes and Charges: {taxes_count[0].cnt}")

    # D6) NC y ND de compras
    nc = frappe.db.sql("""
        SELECT COUNT(*) AS cnt FROM `tabVE Purchase Credit Note`
        WHERE company=%s AND docstatus=1 AND posting_date BETWEEN %s AND %s
    """, (company, loose_from_date, to_date), as_dict=True)
    nd = frappe.db.sql("""
        SELECT COUNT(*) AS cnt FROM `tabVE Purchase Debit Note`
        WHERE company=%s AND docstatus=1 AND posting_date BETWEEN %s AND %s
    """, (company, loose_from_date, to_date), as_dict=True)
    print(f"      D6) VE Purchase Credit Notes: {nc[0].cnt}, VE Purchase Debit Notes: {nd[0].cnt}")

    print()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(val):
    """Formato numérico legible."""
    return f"{flt(val):,.2f}"


def _get_purchase_book_iva_total(company, from_date, to_date):
    """Suma del IVA (crédito fiscal) según la lógica del Purchase Book."""
    try:
        from l10n_ve.l10n_ve.report.purchase_book.purchase_book import get_query_data
        filters = {"company": company, "from_date": from_date, "to_date": to_date}
        data = get_query_data(filters)
        return sum(
            flt(r.get("impuesto_general", 0))
            + flt(r.get("impuesto_reducida", 0))
            + flt(r.get("impuesto_adicional", 0))
            for r in data
        )
    except Exception:
        return 0


def _get_sales_book_iva_total(company, from_date, to_date):
    """Suma del IVA (débito fiscal) según la lógica del Sales Book."""
    try:
        from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data
        filters = {"company": company, "from_date": from_date, "to_date": to_date}
        main_data, adjustment_data = get_sales_data(filters)
        total = 0
        for row in main_data + adjustment_data:
            if row.get("is_void"):
                continue
            total += (
                flt(row.get("iva_general_taxpayer", 0))
                + flt(row.get("iva_general_non_taxpayer", 0))
                + flt(row.get("iva_reduced_taxpayer", 0))
                + flt(row.get("iva_reduced_non_taxpayer", 0))
                + flt(row.get("iva_additional_taxpayer", 0))
                + flt(row.get("iva_additional_non_taxpayer", 0))
            )
        return total
    except Exception:
        return 0


def _get_sales_book_igtf_total(company, from_date, to_date):
    """Suma del IGTF según el Sales Book."""
    try:
        from l10n_ve.l10n_ve.report.sales_book.sales_book import get_sales_data
        filters = {"company": company, "from_date": from_date, "to_date": to_date}
        main_data, adjustment_data = get_sales_data(filters)
        return sum(
            flt(row.get("total_igtf", 0))
            for row in main_data + adjustment_data
            if not row.get("is_void") and abs(flt(row.get("total_igtf", 0))) > 0.001
        )
    except Exception:
        return 0


def _get_retenciones_iva_total(company, from_date, to_date):
    """Suma de retenciones IVA según el reporte."""
    try:
        data = frappe.db.sql("""
            SELECT COALESCE(SUM(COALESCE(child.tax_amount_vat, 0)), 0) AS total
            FROM `tabVAT Withholding Voucher Item` child
            INNER JOIN `tabVAT Withholding Voucher` parent
                ON child.parent = parent.name
            WHERE parent.empresa = %s
              AND parent.issue_date BETWEEN %s AND %s
              AND parent.docstatus = 1
        """, (company, from_date, to_date), as_dict=True)
        return flt(data[0].total) if data else 0
    except Exception:
        return 0


def _get_retenciones_islr_total(company, from_date, to_date):
    """Suma de retenciones ISLR según el reporte."""
    try:
        data = frappe.db.sql("""
            SELECT COALESCE(SUM(COALESCE(child.islr_amount, 0)), 0) AS total
            FROM `tabISLR Withholding Voucher Item` child
            INNER JOIN `tabISLR Withholding Voucher` parent
                ON child.parent = parent.name
            WHERE parent.empresa = %s
              AND parent.posting_date BETWEEN %s AND %s
              AND parent.docstatus = 1
        """, (company, from_date, to_date), as_dict=True)
        return flt(data[0].total) if data else 0
    except Exception:
        return 0


def _get_conatel_total(company, from_date, to_date):
    """Suma de ingresos CONATEL (base imponible VES)."""
    try:
        curr = frappe.get_cached_value("Company", company, "default_currency")
        data = frappe.db.sql("""
            SELECT COALESCE(SUM(
                COALESCE(sii.base_amount, 0)
                * CASE WHEN si.is_return = 1 THEN -1 ELSE 1 END
                * CASE WHEN si.currency != COALESCE(%(curr)s, 'VES')
                       THEN COALESCE(si.conversion_rate, 1) ELSE 1 END
            ), 0) AS total
            FROM `tabSales Invoice Item` sii
            INNER JOIN `tabSales Invoice` si ON sii.parent = si.name
            LEFT JOIN `tabItem` i ON sii.item_code = i.name
            WHERE si.company = %s
              AND si.docstatus = 1
              AND si.posting_date BETWEEN %s AND %s
              AND COALESCE(i.is_conatel_service, 0) = 1
        """, {
            "company": company,
            "from_date": from_date,
            "to_date": to_date,
            "curr": curr,
        }, as_dict=True)
        return flt(data[0].total) if data else 0
    except Exception:
        return 0
