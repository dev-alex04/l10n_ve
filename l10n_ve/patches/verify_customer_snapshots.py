"""
Verificación post-patch: confirma que los snapshots de customer_name
se actualizaron correctamente en Sales Invoice, Credit Note y Debit Note.

Ejecución:
    bench --site domina.galanet execute l10n_ve.patches.verify_customer_snapshots.execute
"""
import frappe


def execute() -> None:
    """Verifica que no queden snapshots con espacios sucios."""

    print("=" * 80)
    print("VERIFICACIÓN: Snapshots de customer_name en documentos")
    print("=" * 80)

    # Sales Invoice
    dirty_si: list[dict] = frappe.db.sql("""
        SELECT si.name, si.customer, si.customer_name
        FROM `tabSales Invoice` si
        WHERE si.customer_name != TRIM(si.customer_name)
           OR si.customer_name LIKE '%%  %%'
        LIMIT 20
    """, as_dict=True)
    print(f"\n  Sales Invoice con customer_name sucio: {len(dirty_si)}")
    for r in dirty_si:
        print(f"    → {r['name']} | \"{r['customer_name']}\"")

    # VE Sales Credit Note
    dirty_cn: list[dict] = frappe.db.sql("""
        SELECT nc.name, nc.customer, nc.customer_name
        FROM `tabVE Sales Credit Note` nc
        WHERE nc.customer_name != TRIM(nc.customer_name)
           OR nc.customer_name LIKE '%%  %%'
        LIMIT 20
    """, as_dict=True)
    print(f"\n  Credit Notes con customer_name sucio: {len(dirty_cn)}")
    for r in dirty_cn:
        print(f"    → {r['name']} | \"{r['customer_name']}\"")

    # VE Sales Debit Note
    dirty_dn: list[dict] = frappe.db.sql("""
        SELECT nd.name, nd.customer, nd.customer_name
        FROM `tabVE Sales Debit Note` nd
        WHERE nd.customer_name != TRIM(nd.customer_name)
           OR nd.customer_name LIKE '%%  %%'
        LIMIT 20
    """, as_dict=True)
    print(f"\n  Debit Notes con customer_name sucio: {len(dirty_dn)}")
    for r in dirty_dn:
        print(f"    → {r['name']} | \"{r['customer_name']}\"")

    # Customer master
    dirty_cust: list[dict] = frappe.db.sql("""
        SELECT c.name, c.customer_name
        FROM `tabCustomer` c
        WHERE c.customer_name != TRIM(c.customer_name)
           OR c.customer_name LIKE '%%  %%'
    """, as_dict=True)
    print(f"\n  Customers con customer_name sucio: {len(dirty_cust)}")
    for r in dirty_cust:
        print(f"    → {r['name']} | \"{r['customer_name']}\"")

    total: int = len(dirty_si) + len(dirty_cn) + len(dirty_dn) + len(dirty_cust)
    if total == 0:
        print("\n✅ Todo limpio. No quedan snapshots con espacios.")
    else:
        print(f"\n⚠️  Quedan {total} registros por limpiar.")
