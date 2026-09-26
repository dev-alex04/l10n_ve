"""Producto 'Recargo por IGTF (3%)' sembrado por el setup.

Lo delicado no es que el ítem se cree, sino QUE NO se le cuelgue una alícuota que no le
corresponde: es un producto exento que va en documentos fiscales.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from l10n_ve.setup import create_igtf_surcharge_item

ITEM_CODE = (
    "Recargo por Impuesto a las Grandes Transacciones Financieras (3%) "
    "aplicado a la factura afectada"
)
GROUP_NAME = "Recargos Fiscales"


def _item():
    """El Item por su `item_name`: con item_naming_by = «Naming Series», ERPNext le pone el
    número de la serie al `name` y también al `item_code`; el texto solo queda en `item_name`."""
    return frappe.get_doc("Item", frappe.db.get_value("Item", {"item_name": ITEM_CODE}, "name"))

# Sin cobertura a proposito: el camino "sitio sin arbol de Item Group" --que la
# funcion omite en vez de cortar-- no tiene test. Ejercitarlo pide interceptar
# `frappe.db.get_value`, y `frappe.db` es un LocalProxy sobre el que el patch no
# llega al `exists` que la funcion usa por dentro: el mock pasa de largo y el test
# verifica lo contrario de lo que dice. Mejor sin test que con uno que miente.


class TestIGTFSurchargeItem(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # `create_igtf_surcharge_item` hace `frappe.db.commit()`, y el arbol de Item
        # Group commitea por su cuenta al recalcular lft/rgt. Con eso el rollback de
        # FrappeTestCase no alcanza y el item quedaba PERMANENTEMENTE en el site donde
        # corriera la suite --verificado: sobrevivia al tearDown--. Se neutraliza el
        # commit para que la transaccion de la prueba se pueda deshacer entera.
        parche = patch.object(frappe.db, "commit")
        self.addCleanup(parche.stop)
        parche.start()

        # El sitio del CI se crea con `bench new-site` + `install-app` y NUNCA corre el
        # asistente, asi que no tiene arbol de Item Group y la funcion se omite sola.
        # Se siembra la raiz para poder ejercitar la creacion en cualquier sitio; con el
        # commit parcheado se deshace con el resto de la transaccion.
        self.root_group = frappe.db.get_value(
            "Item Group", {"is_group": 1, "parent_item_group": ["is", "not set"]}, "name"
        )
        if not self.root_group:
            raiz = frappe.new_doc("Item Group")
            raiz.item_group_name = "All Item Groups"
            raiz.is_group = 1
            raiz.insert(ignore_permissions=True)
            self.root_group = raiz.name

        # Idem con la unidad de medida por defecto, que el Item exige y en ese sitio
        # tampoco existe.
        if not frappe.db.get_single_value("Stock Settings", "stock_uom"):
            if not frappe.db.exists("UOM", "Unit"):
                frappe.get_doc({"doctype": "UOM", "uom_name": "Unit"}).insert(
                    ignore_permissions=True
                )
            frappe.db.set_single_value("Stock Settings", "stock_uom", "Unit")

    def test_creates_the_item_and_its_group(self):
        create_igtf_surcharge_item()

        self.assertTrue(frappe.db.exists("Item Group", GROUP_NAME))
        self.assertTrue(frappe.db.exists("Item", {"item_name": ITEM_CODE}))

        item = _item()
        self.assertEqual(item.item_group, GROUP_NAME)
        self.assertEqual(item.is_stock_item, 0)
        self.assertEqual(item.vat_exempt, 1)

    def test_marks_it_as_a_service_when_the_field_exists(self):
        """El indicador Bien/Servicio lo crea el #580; acá se tolera su ausencia."""
        create_igtf_surcharge_item()

        item = _item()
        if item.meta.has_field("goods_or_service"):
            self.assertEqual(item.goods_or_service, "2 - Servicio")

    def test_never_links_a_non_exempt_tax_template(self):
        """Lo que de verdad hay que proteger: es un producto EXENTO.

        Antes, sin plantilla 'Exento', se buscaba `title like "%E%"` con `limit=1` y se
        le colgaba una alicuota cualquiera.
        """
        create_igtf_surcharge_item()

        for fila in _item().taxes:
            self.assertIn("exent", fila.item_tax_template.lower())

    def test_does_not_invent_a_template_when_there_is_none(self):
        """Sin plantilla exenta no se asocia ninguna, en vez de elegir una arbitraria."""
        real = frappe.get_all

        def sin_plantillas(doctype, *a, **kw):
            # Solo se intercepta la busqueda de plantillas: un mock global de get_all
            # rompe el insert del Item, que lo usa por dentro.
            return [] if doctype == "Item Tax Template" else real(doctype, *a, **kw)

        with patch.object(frappe, "get_all", side_effect=sin_plantillas):
            create_igtf_surcharge_item()

        self.assertEqual(_item().taxes, [])

    def test_is_idempotent(self):
        create_igtf_surcharge_item()
        create_igtf_surcharge_item()

        self.assertEqual(
            frappe.db.count("Item", {"item_name": ITEM_CODE}),
            1,
            "una segunda corrida no debe duplicar el item",
        )
