"""
Marca las facturas que tienen una retención contabilizada sin su comprobante.

El campo ``missing_withholding_voucher`` lo mantiene el servidor de ahora en adelante
--en el `validate`, al cargar la metadata del comprobante y al contabilizar una
retención con ``fix_missing_withholding``-- pero las facturas que ya existen nacieron
sin él. Este backfill se lo calcula una vez.

Sin esto el aviso de la vista de lista queda apagado justo donde más hace falta: en el
histórico. Medido sobre una copia de producción, las facturas de julio de 2026 en
adelante con retención contabilizada eran 392, y a 200 les faltaba el número de algún
comprobante.

Por qué el campo existe
-----------------------
La vista de lista sólo puede leer campos del padre: no ve la tabla de impuestos, que es
el único lugar donde consta que la retención está contabilizada. Antes lo aproximaba
con ``total_withholding != 0 && !nro_iva && !nro_islr``, y esa heurística fallaba de dos
maneras: ``total_withholding`` no se recalcula nunca en Sales Invoice --66 facturas lo
tenían en 0 teniendo la fila de retención, y quedaban invisibles-- y el ``&&`` exigía
que faltaran los DOS números, así que 21 facturas a las que sólo les faltaba uno
figuraban como completas.

Uso
---
    bench --site <site> execute l10n_ve.scripts.backfill_missing_withholding_voucher.dry_run
    bench --site <site> execute l10n_ve.scripts.backfill_missing_withholding_voucher.execute
"""

import frappe
from frappe.utils import cint

from l10n_ve.overrides.sales_invoice import WITHHOLDING_VOUCHER_FIELD

#: Facturas por transacción. El backfill puede tocar decenas de miles de filas y una
#: sola transacción larga sostiene locks sobre toda la tabla.
BATCH_SIZE: int = 500


def dry_run() -> None:
    _run(dry=True)


def execute() -> None:
    _run(dry=False)


def _invoices_to_flag() -> set:
    """Facturas donde falta el número de comprobante de alguna retención contabilizada.

    Se evalúa por tipo y en SQL: cada tipo de retención se cruza contra el campo donde
    vive SU número. Comparar contra los dos campos juntos es lo que hacía la heurística
    vieja, y es lo que dejaba pasar a las que sólo tenían uno cargado.
    """
    faltantes: set = set()
    for charge_type, campo in WITHHOLDING_VOUCHER_FIELD.items():
        filas = frappe.db.sql(f"""
            SELECT DISTINCT si.name
            FROM `tabSales Invoice` si
            INNER JOIN `tabSales Taxes and Charges` t
                    ON t.parent = si.name
                   AND t.parenttype = 'Sales Invoice'
                   AND t.charge_type = %(charge_type)s
                   AND t.tax_amount != 0
            WHERE si.docstatus < 2
              AND COALESCE(TRIM(si.`{campo}`), '') = ''
        """, {"charge_type": charge_type}, pluck=True)
        faltantes.update(filas)
    return faltantes


def _currently_flagged() -> set:
    return set(frappe.db.get_all(
        "Sales Invoice",
        filters={"missing_withholding_voucher": 1, "docstatus": ("<", 2)},
        pluck="name",
    ))


def _run(dry: bool) -> None:
    modo: str = "DRY-RUN" if dry else "EJECUCIÓN"
    print(f"=== Aviso de comprobante de retención faltante — {modo} ===\n")

    if not frappe.db.has_column("Sales Invoice", "missing_withholding_voucher"):
        print("  El campo no existe todavía. Correr antes:")
        print("    bench --site <site> migrate")
        return

    deberian: set = _invoices_to_flag()
    marcadas: set = _currently_flagged()

    encender: set = deberian - marcadas
    apagar: set = marcadas - deberian

    print(f"  {len(deberian)} factura(s) con retención sin su comprobante")
    print(f"  {len(encender)} por marcar | {len(apagar)} por desmarcar "
          f"(ya tienen el número cargado)")

    if not encender and not apagar:
        print("\n  Todo al día.")
        return

    if dry:
        muestra: list = sorted(encender)[:10]
        if muestra:
            print("\n  Muestra de las que se marcarían:")
            for nombre in muestra:
                datos = frappe.db.get_value(
                    "Sales Invoice", nombre,
                    ["customer_name", "posting_date", "bill_no"], as_dict=True,
                )
                print(f"    {nombre:<24} {str(datos.customer_name)[:30]:<32} "
                      f"{datos.posting_date}  {datos.bill_no or '-'}")
        print("\n  Nada fue modificado. Para aplicarlo:")
        print("    bench --site <site> execute "
              "l10n_ve.scripts.backfill_missing_withholding_voucher.execute")
        return

    print()
    for valor, nombres in ((1, sorted(encender)), (0, sorted(apagar))):
        hechas: int = 0
        for inicio in range(0, len(nombres), BATCH_SIZE):
            lote: list = nombres[inicio:inicio + BATCH_SIZE]
            for nombre in lote:
                # update_modified=False: es un dato derivado, no una edición del
                # usuario. Mover el `modified` de miles de facturas ensucia el
                # historial y dispara los feeds de actividad sin que nada haya
                # cambiado en el documento.
                frappe.db.set_value(
                    "Sales Invoice", nombre,
                    "missing_withholding_voucher", valor,
                    update_modified=False,
                )
            frappe.db.commit()
            hechas += len(lote)
        if nombres:
            verbo: str = "marcada(s)" if valor else "desmarcada(s)"
            print(f"  {hechas} {verbo}")

    total: int = cint(frappe.db.count(
        "Sales Invoice", {"missing_withholding_voucher": 1, "docstatus": ("<", 2)}
    ))
    print(f"\n  Quedan {total} factura(s) avisadas.")
