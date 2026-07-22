import frappe

import erpnext.stock.doctype.packed_item.packed_item as packed_item_module

# Parche validado contra ERPNext v15.106.0. Si una actualizacion de ERPNext
# cambia las firmas de get_indexed_packed_items_table / add_packed_item_row,
# re-verificar este parche.

# Referencias a las funciones originales de ERPNext
original_get_indexed_packed_items_table = packed_item_module.get_indexed_packed_items_table
original_add_packed_item_row = packed_item_module.add_packed_item_row


def get_indexed_packed_items_table(doc):
    """
    MONKEYPATCH l10n_ve:
    Solo aplica a documentos NUEVOS (doc.is_new()): indexa la tabla de
    packed_items con una clave estable y consistente con add_packed_item_row,
    basada en (parent_item, item_code, ocurrencia) en lugar de `packed_item.idx`
    / `main_item_row.idx`.

    El codigo original usaba `packed_item.idx` (idx de la fila empaquetada: 1,2,3)
    frente a `main_item_row.idx` (idx del item padre, siempre 1 para el bundle),
    por lo que solo coincidian en el primer componente. Eso hacia que al validar
    una Nota de Entrega nueva creada desde una Orden de Venta para un conjunto,
    el sistema borrara los lotes/series y el almacen ingresados manualmente en
    todos los componentes excepto el primero.

    Usar un contador de ocurrencia por (parent_item, item_code) evita depender
    de `parent_detail_docname` (que es None para docs nuevos mientras el doc aun
    no tiene name asignado).

    Para documentos ya guardados (is_new()==False) se delega a la funcion
    original, que indexa por `parent_detail_docname` / `main_item_row.name`
    (identidad estable y unica por linea) y nunca tuvo este bug. Sobrescribir
    tambien ese camino romperia la identidad por `name` ante borrar/reordenar
    lineas del mismo conjunto, asignando lote/almacen equivocado en silencio.

    El reset del contador por run vive aqui porque esta funcion se llama una
    sola vez al inicio de make_packing_list (antes del loop de items).
    """
    doc._packed_seq = {}

    if not doc.is_new():
        return original_get_indexed_packed_items_table(doc)

    indexed_table, counters = {}, {}
    for packed_item in doc.get("packed_items"):
        base = (packed_item.parent_item, packed_item.item_code)
        counters[base] = counters.get(base, 0) + 1
        key = (packed_item.parent_item, packed_item.item_code, counters[base])
        indexed_table[key] = packed_item

    return indexed_table


def add_packed_item_row(doc, packing_item, main_item_row, packed_items_table, reset):
    """
    MONKEYPATCH l10n_ve:
    Solo aplica a documentos NUEVOS (doc.is_new()): usa la misma clave por
    ocurrencia que get_indexed_packed_items_table para que la fila ya existente
    (con su batch_no / serial_no / warehouse) sea reutilizada y no reconstruida
    en blanco al validar un doc nuevo.

    Para documentos guardados delega en la original (identidad por `name`).
    """
    if not doc.is_new():
        return original_add_packed_item_row(
            doc, packing_item, main_item_row, packed_items_table, reset
        )

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


# Parchear las funciones a nivel de modulo
packed_item_module.get_indexed_packed_items_table = get_indexed_packed_items_table
packed_item_module.add_packed_item_row = add_packed_item_row
