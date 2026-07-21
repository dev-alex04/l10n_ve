import frappe

import erpnext.stock.doctype.packed_item.packed_item as packed_item_module
import erpnext.stock.doctype.delivery_note.delivery_note as delivery_note_module
import erpnext.selling.doctype.sales_order.sales_order as sales_order_module

# Referencias a las funciones originales de ERPNext
original_get_indexed_packed_items_table = packed_item_module.get_indexed_packed_items_table
original_add_packed_item_row = packed_item_module.add_packed_item_row
original_make_packing_list = packed_item_module.make_packing_list


def get_indexed_packed_items_table(doc):
    """
    MONKEYPATCH l10n_ve:
    Indexa la tabla de packed_items con una clave estable y consistente con
    add_packed_item_row, basada en (parent_item, item_code, ocurrencia) en lugar
    de `packed_item.idx` / `main_item_row.idx` / `parent_detail_docname`.

    El codigo original usaba `packed_item.idx` (idx de la fila empaquetada: 1,2,3)
    frente a `main_item_row.idx` (idx del item padre, siempre 1 para el bundle),
    por lo que solo coincidian en el primer componente. Eso hacia que al validar
    una Nota de Entrega nueva creada desde una Orden de Venta para un conjunto,
    el sistema borrara los lotes/series y el almacen ingresados manualmente en
    todos los componentes excepto el primero.

    Usar un contador de ocurrencia por (parent_item, item_code) evita depender
    de `parent_detail_docname` (que es None para docs nuevos mientras el doc aun
    no tiene name asignado) y funciona igual para docs nuevos y ya guardados.
    """
    indexed_table = {}
    counters = {}
    for packed_item in doc.get("packed_items"):
        base = (packed_item.parent_item, packed_item.item_code)
        counters[base] = counters.get(base, 0) + 1
        key = (packed_item.parent_item, packed_item.item_code, counters[base])
        indexed_table[key] = packed_item

    return indexed_table


def add_packed_item_row(doc, packing_item, main_item_row, packed_items_table, reset):
    """
    MONKEYPATCH l10n_ve:
    Usa la misma clave por ocurrencia que get_indexed_packed_items_table para
    que la fila ya existente (con su batch_no / serial_no / warehouse) sea
    reutilizada y no reconstruida en blanco al validar un doc nuevo.
    """
    base = (main_item_row.item_code, packing_item.item_code)

    # ocurrencia de este componente entre las filas ya agregadas en este run
    seq_map = getattr(doc, "_packed_seq", {})
    seq_map[base] = seq_map.get(base, 0) + 1
    doc._packed_seq = seq_map

    key = (main_item_row.item_code, packing_item.item_code, seq_map[base])

    exists, pi_row = False, {}
    if packed_items_table.get(key):
        pi_row, exists = packed_items_table.get(key), True

    if not exists:
        pi_row = doc.append("packed_items", {})
    elif reset:  # add row if row exists but table is reset
        pi_row.idx, pi_row.name = None, None
        pi_row = doc.append("packed_items", pi_row)

    return pi_row


def make_packing_list(doc):
    """
    MONKEYPATCH l10n_ve:
    Reinicia el contador de ocurrencia por run antes de delegar a la funcion
    original de ERPNext (que usa las versiones parcheadas de
    get_indexed_packed_items_table / add_packed_item_row).
    """
    doc._packed_seq = {}
    return original_make_packing_list(doc)


# Patch the module-level functions
packed_item_module.get_indexed_packed_items_table = get_indexed_packed_items_table
packed_item_module.add_packed_item_row = add_packed_item_row
packed_item_module.make_packing_list = make_packing_list

# ALSO patch the local bindings in delivery_note and sales_order modules
# so that their local `make_packing_list` references point to our patched version
delivery_note_module.make_packing_list = make_packing_list
sales_order_module.make_packing_list = make_packing_list

# Sentinel: confirma que el parche CORREGIDO (v2, por ocurrencia) esta cargado.
# Revisalo despues de `bench restart`:  cat /tmp/l10n_ve_packed_patch_active
try:
    from datetime import datetime

    with open("/tmp/l10n_ve_packed_patch_active", "w") as _f:
        _f.write("v2-counter " + datetime.now().isoformat())
except Exception:
    pass