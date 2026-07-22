# Copyright (c) 2026, DominaERP and Contributors
# See license.txt

"""
Tests del monkey-patch de packed_items (l10n_ve.patches.stock.packed_item).

Contexto: al validar una Nota de Entrega NUEVA creada desde una Orden de
Venta para un producto conjunto, ERPNext reconstruia en blanco los
packed_items de todos los componentes menos el primero, perdiendo el
lote/serie/almacen ingresados a mano. La causa era que la tabla stale se
indexaba por `packed_item.idx` (1,2,3) pero se buscaba por
`main_item_row.idx` (siempre 1 para el bundle), asi que solo casaba el
primer componente.

El parche indexa por (parent_item, item_code, ocurrencia) SOLO para docs
nuevos (doc.is_new()); para docs ya guardados delega en las funciones
originales de ERPNext, que casan por `name` / `parent_detail_docname`
(identidad estable por linea) y nunca tuvieron el bug. Sobrescribir tambien
ese camino reasignaria lote/almacen equivocado en silencio al borrar o
reordenar lineas del mismo conjunto.

Suite unittest con dobles de prueba, sin BD.
"""

import unittest

import frappe

from l10n_ve.patches.stock.packed_item import (
    add_packed_item_row,
    get_indexed_packed_items_table,
)

BUNDLE = "BUNDLE-INT012"


def _row(
    item_code=None,
    parent_item=BUNDLE,
    idx=0,
    name=None,
    parent_detail_docname=None,
    batch_no=None,
    warehouse=None,
    serial_no=None,
):
    """Fila mock de packed_items / items (frappe._dict, atributos = None por defecto)."""
    return frappe._dict({
        "parent_item": parent_item,
        "item_code": item_code,
        "idx": idx,
        "name": name,
        "parent_detail_docname": parent_detail_docname,
        "batch_no": batch_no,
        "serial_no": serial_no,
        "warehouse": warehouse,
    })


class _FakeDoc:
    """Doble minimo de un documento de stock para probar el packing list.

    Expone solo lo que usan las funciones parcheadas: get('packed_items'),
    is_new(), append('packed_items', row) y el atributo _packed_seq.
    """

    def __init__(self, packed_items=None, is_new=True):
        self._packed_items = list(packed_items or [])
        self._is_new = is_new
        self._packed_seq = {}

    def get(self, key, default=None):
        if key == "packed_items":
            return self._packed_items
        return getattr(self, key, default)

    def is_new(self):
        return self._is_new

    def append(self, table, value):
        row = value if isinstance(value, frappe._dict) else frappe._dict(value or {})
        self._packed_items.append(row)
        return row


class TestPackedItemPatch(unittest.TestCase):
    def test_new_doc_indexes_by_occurrence(self):
        """Doc nuevo: la clave usa (parent_item, item_code, ocurrencia)."""
        rows = [
            _row(item_code="SKU010", idx=1, batch_no="L10T-010"),
            _row(item_code="SKU011", idx=2, batch_no="L10T-011"),
            _row(item_code="SKU012", idx=3, batch_no="L10T-012"),
        ]
        doc = _FakeDoc(packed_items=rows, is_new=True)

        table = get_indexed_packed_items_table(doc)

        self.assertEqual(
            set(table.keys()),
            {(BUNDLE, "SKU010", 1), (BUNDLE, "SKU011", 1), (BUNDLE, "SKU012", 1)},
        )
        self.assertEqual(doc._packed_seq, {})  # contador reiniciado por run

    def test_new_doc_preserves_batch_for_all_components(self):
        """Bug original: doc nuevo desde SO conserva lote/almacen en los 3
        componentes, no solo en el primero."""
        stale_rows = [
            _row(item_code="SKU010", idx=1, batch_no="L10T-010", warehouse="WH-A"),
            _row(item_code="SKU011", idx=2, batch_no="L10T-011", warehouse="WH-B"),
            _row(item_code="SKU012", idx=3, batch_no="L10T-012", warehouse="WH-C"),
        ]
        doc = _FakeDoc(packed_items=stale_rows, is_new=True)

        stale = get_indexed_packed_items_table(doc)
        # reset_packing_list() vacia la tabla antes del loop de items:
        doc._packed_items = []

        main = _row(item_code=BUNDLE, idx=1, name="itm1")
        result = {}
        for comp, batch, wh in [
            ("SKU010", "L10T-010", "WH-A"),
            ("SKU011", "L10T-011", "WH-B"),
            ("SKU012", "L10T-012", "WH-C"),
        ]:
            pi = add_packed_item_row(
                doc=doc,
                packing_item=frappe._dict({"item_code": comp}),
                main_item_row=main,
                packed_items_table=stale,
                reset=True,
            )
            result[comp] = (pi.batch_no, pi.warehouse)

        self.assertEqual(result["SKU010"], ("L10T-010", "WH-A"))
        self.assertEqual(result["SKU011"], ("L10T-011", "WH-B"))  # antes del fix: (None, None)
        self.assertEqual(result["SKU012"], ("L10T-012", "WH-C"))  # antes del fix: (None, None)

    def test_saved_doc_indexes_by_name_identity(self):
        """Doc guardado: delega en la original, que indexa por
        parent_detail_docname (identidad por linea), no por ocurrencia."""
        rows = [
            _row(item_code="SKU010", parent_detail_docname="itm1", batch_no="A1"),
            _row(item_code="SKU010", parent_detail_docname="itm2", batch_no="A2"),
        ]
        doc = _FakeDoc(packed_items=rows, is_new=False)

        table = get_indexed_packed_items_table(doc)

        self.assertEqual(
            set(table.keys()),
            {(BUNDLE, "SKU010", "itm1"), (BUNDLE, "SKU010", "itm2")},
        )

    def test_saved_doc_keeps_own_batch_on_duplicate_line_edit(self):
        """Regresion: con el mismo conjunto en dos lineas, borrar una y
        revalidar debe conservar el lote/almacen PROPIO de la linea que
        sobrevive (identidad por name), no heredar el de la borrada."""
        row_itm1 = _row(
            item_code="SKU010", parent_detail_docname="itm1", name="pk1",
            batch_no="A1", warehouse="WH1",
        )
        row_itm2 = _row(
            item_code="SKU010", parent_detail_docname="itm2", name="pk2",
            batch_no="A2", warehouse="WH2",
        )
        stale = {
            (BUNDLE, "SKU010", "itm1"): row_itm1,
            (BUNDLE, "SKU010", "itm2"): row_itm2,
        }
        doc = _FakeDoc(packed_items=[], is_new=False)

        survivor_main = _row(item_code=BUNDLE, name="itm2")
        pi = add_packed_item_row(
            doc=doc,
            packing_item=frappe._dict({"item_code": "SKU010"}),
            main_item_row=survivor_main,
            packed_items_table=stale,
            reset=True,
        )

        self.assertEqual(pi.batch_no, "A2")  # su propio lote
        self.assertEqual(pi.warehouse, "WH2")
        self.assertNotEqual(pi.batch_no, "A1")  # no el de la linea borrada

    def test_counter_reset_between_runs(self):
        """_packed_seq se reinicia en cada llamada a
        get_indexed_packed_items_table (una vez por run)."""
        rows = [_row(item_code="SKU010", idx=1)]
        doc = _FakeDoc(packed_items=rows, is_new=True)

        get_indexed_packed_items_table(doc)
        add_packed_item_row(
            doc,
            frappe._dict({"item_code": "SKU010"}),
            _row(item_code=BUNDLE, idx=1),
            {},
            reset=False,
        )
        self.assertEqual(doc._packed_seq, {(BUNDLE, "SKU010"): 1})

        # segunda pasada: el contador vuelve a cero
        get_indexed_packed_items_table(doc)
        self.assertEqual(doc._packed_seq, {})


if __name__ == "__main__":
    unittest.main()
