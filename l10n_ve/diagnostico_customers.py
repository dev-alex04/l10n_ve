"""
Script de diagnóstico de integridad de datos de Customers.
Solo lectura — no modifica ningún registro.

Ejecutar con:
    bench --site galanet.domina.plus execute resources.l10n_ve.diagnostico_customers.run
"""
import frappe


def run() -> None:
    """Ejecuta los 5 diagnósticos de integridad de Customer master."""
    _diagnostico_duplicados()
    _diagnostico_ids_numericos()
    _diagnostico_typos()
    _diagnostico_espacios()
    _diagnostico_sin_fiscal()


def _diagnostico_duplicados() -> None:
    """Diagnóstico 1: Customers con sufijo '-1', '-2', etc."""
    print("=" * 80)
    print('DIAGNÓSTICO 1: Customers con sufijo "-1", "-2", etc.')
    print("=" * 80)

    dupes: list[dict] = frappe.db.sql("""
        SELECT
            c.name AS customer_id,
            c.customer_name,
            c.creation,
            (SELECT COUNT(*) FROM `tabSales Invoice` si
             WHERE si.customer = c.name AND si.docstatus = 1) AS facturas,
            (SELECT COUNT(*) FROM `tabGL Entry` gle
             WHERE gle.party = c.name AND gle.is_cancelled = 0) AS gl_entries,
            (SELECT COALESCE(SUM(gle.debit - gle.credit), 0) FROM `tabGL Entry` gle
             WHERE gle.party = c.name AND gle.is_cancelled = 0) AS saldo_neto
        FROM `tabCustomer` c
        WHERE c.name REGEXP '- [0-9]+$'
        ORDER BY c.name
    """, as_dict=True)

    if dupes:
        for d in dupes:
            original: str = d["customer_id"].rsplit(" - ", 1)[0]
            orig_exists: bool = bool(frappe.db.exists("Customer", original))
            print(f"""
  Customer:   {d['customer_id']}
  Nombre:     {d['customer_name']}
  Creado:     {d['creation']}
  Facturas:   {d['facturas']}
  GL Entries: {d['gl_entries']}
  Saldo:      {d['saldo_neto']:,.2f} VEF
  Original:   {original} -> {'✅ EXISTE' if orig_exists else '❌ NO EXISTE'}
  ---""")
    else:
        print("  No se encontraron duplicados con sufijo.")
    print()


def _diagnostico_ids_numericos() -> None:
    """Diagnóstico 2: Customers con ID numérico como nombre."""
    print("=" * 80)
    print("DIAGNÓSTICO 2: Customers con ID numérico como nombre")
    print("=" * 80)

    numerics: list[dict] = frappe.db.sql("""
        SELECT
            c.name, c.customer_name, c.creation,
            (SELECT COUNT(*) FROM `tabSales Invoice` si
             WHERE si.customer = c.name AND si.docstatus = 1) AS facturas
        FROM `tabCustomer` c
        WHERE c.name REGEXP '^[0-9.,]+$'
           OR c.customer_name REGEXP '^[0-9.,]+$'
        LIMIT 20
    """, as_dict=True)

    if numerics:
        for n in numerics:
            print(f"  ID: {n['name']} | Nombre: {n['customer_name']} | "
                  f"Facturas: {n['facturas']} | Creado: {n['creation']}")
    else:
        print("  No se encontraron IDs numéricos como nombre.")
    print()


def _diagnostico_typos() -> None:
    """Diagnóstico 3: Typos conocidos en Customer master."""
    print("=" * 80)
    print("DIAGNÓSTICO 3: Typos conocidos en Customer master")
    print("=" * 80)

    typos: list[tuple[str, str]] = [
        ("SOYUMA LEONON%", "Debería ser ZOYUMA LEONOR"),
        ("INAI GABRIELA%", "Debería ser SINAI GABRIELA"),
        ("%PADRO DE CADENAS%", "Debería ser PADRON"),
        ("Ermely Josefina morales%", "Case sensitivity - debería ser UPPER"),
        ("%GONZALEZ%GONZALEZ%", "Nombre concatenado doble"),
    ]

    for pattern, nota in typos:
        results: list[dict] = frappe.db.sql("""
            SELECT c.name, c.customer_name
            FROM `tabCustomer` c
            WHERE c.customer_name LIKE %s
        """, (pattern,), as_dict=True)

        if results:
            for r in results:
                print(f'  ⚠️  ID: {r["name"]} | '
                      f'Nombre: "{r["customer_name"]}" → {nota}')
        else:
            print(f'  ✅ Patrón "{pattern}" no encontrado '
                  f"(posiblemente ya corregido)")
    print()


def _diagnostico_espacios() -> None:
    """Diagnóstico 4: Customers con espacios leading/trailing o dobles."""
    print("=" * 80)
    print("DIAGNÓSTICO 4: Customers con espacios leading/trailing")
    print("=" * 80)

    spaces: list[dict] = frappe.db.sql("""
        SELECT
            c.name,
            c.customer_name,
            LENGTH(c.customer_name) AS len_original,
            LENGTH(TRIM(c.customer_name)) AS len_trimmed,
            (SELECT COUNT(*) FROM `tabSales Invoice` si
             WHERE si.customer = c.name AND si.docstatus = 1) AS facturas
        FROM `tabCustomer` c
        WHERE c.customer_name != TRIM(c.customer_name)
           OR c.customer_name LIKE '%%  %%'
        ORDER BY c.customer_name
    """, as_dict=True)

    print(f"  Total encontrados: {len(spaces)}")
    if spaces:
        for s in spaces[:20]:
            diff: int = s["len_original"] - s["len_trimmed"]
            has_double: bool = "  " in (s["customer_name"] or "")
            issues: list[str] = []
            if diff > 0:
                issues.append(f"{diff} espacios extra")
            if has_double:
                issues.append("doble espacio")
            print(f'  → "{s["customer_name"]}" '
                  f'({" + ".join(issues)}) | Facturas: {s["facturas"]}')
        if len(spaces) > 20:
            print(f"  ... y {len(spaces) - 20} más")
    print()


def _diagnostico_sin_fiscal() -> None:
    """Diagnóstico 5: Facturas sin bill_no/bill_control (mayo 2026)."""
    print("=" * 80)
    print("DIAGNÓSTICO 5: Facturas sin bill_no/bill_control (mayo 2026)")
    print("=" * 80)

    missing_fiscal: list[dict] = frappe.db.sql("""
        SELECT
            si.name, si.customer, si.customer_name, si.posting_date,
            si.base_grand_total, si.bill_no, si.bill_control
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.is_return = 0
          AND si.posting_date BETWEEN '2026-05-01' AND '2026-05-15'
          AND (si.bill_no IS NULL OR si.bill_no = ''
               OR si.bill_control IS NULL OR si.bill_control = '')
        ORDER BY si.posting_date, si.customer_name
    """, as_dict=True)

    total_missing: float = sum(r["base_grand_total"] or 0 for r in missing_fiscal)
    print(f"  Total facturas sin número fiscal: {len(missing_fiscal)}")
    print(f"  Monto total afectado: {total_missing:,.2f} VEF")

    if missing_fiscal:
        print()
        for r in missing_fiscal[:25]:
            bill: str = r["bill_no"] or "NULL"
            ctrl: str = r["bill_control"] or "NULL"
            print(f"  → {r['name']} | {r['posting_date']} | "
                  f"{r['customer_name']} | {r['base_grand_total']:,.2f} VEF | "
                  f"bill_no={bill} | bill_ctrl={ctrl}")
        if len(missing_fiscal) > 25:
            print(f"  ... y {len(missing_fiscal) - 25} más")
    print()
